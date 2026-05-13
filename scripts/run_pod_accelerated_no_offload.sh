#!/bin/bash
# Pod-to-pod VPC-OVN ACCELERATED benchmark — Test Case 2 matrix.
# Mirrors scripts/run_pod_baseline.sh but for the dpf-ovn-accelerated-no-offload cluster:
#   - Bench pods (bench-client-vpc, bench-server-vpc) run on the DPU tenant
#     cluster (one per DPU node) using image nicolaka/netshoot.
#   - Each pod has a secondary "net1" interface attached to bench-net (VPC-OVN).
#   - Traffic between net1 IPs traverses OVS-DOCA on the DPU and geneve over
#     the 40G fabric (p0).
#
# Tools (iperf3, netperf, sockperf, mpstat) run INSIDE the pod containers via
# `kubectl exec`. This is a true pod-to-pod measurement — no host-side nsenter
# trick — so values reflect what an application running in a tenant DPU pod
# would actually see.

set -u
SSH="ssh -i /home/ubuntu/.ssh/dpu -o StrictHostKeyChecking=no"
HOST=ubuntu@172.16.30.90
TKC=/tmp/tenant.kc
KEXEC="sudo kubectl --kubeconfig=$TKC -n default exec"

OUT=/home/ubuntu/dpf_testing_scenarios/results/dpf-ovn-accelerated-no-offload
mkdir -p "$OUT"

log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$OUT/run.log"; }

CLIENT=bench-client-vpc
SERVER=bench-server-vpc

# Resolve net1 (VPC-OVN) IPs from the pod network-status annotation.
get_net1_ip() {
  local pod=$1
  $SSH $HOST "TKC=$TKC; SERVER=\$(sudo kubectl --kubeconfig=\$TKC config view --raw -o jsonpath='{.clusters[0].cluster.server}'); sudo curl -sk --cert /tmp/cc.pem --key /tmp/ck.pem --max-time 6 \$SERVER/api/v1/namespaces/default/pods/$pod 2>/dev/null" | \
    python3 -c "import json,sys; p=json.load(sys.stdin); ns=p['metadata'].get('annotations',{}).get('k8s.v1.cni.cncf.io/network-status',''); import re; nets=json.loads(ns) if ns else []; print(next((n['ips'][0] for n in nets if n.get('name')=='default/bench-net'), ''))"
}

CLIENT_IP=$(get_net1_ip $CLIENT)
SERVER_IP=$(get_net1_ip $SERVER)
log "Bench pod net1 IPs: client=$CLIENT_IP server=$SERVER_IP"
[ -z "$CLIENT_IP" ] || [ -z "$SERVER_IP" ] && { log "missing net1 IPs"; exit 1; }

# Sanity ping client→server on net1 before starting the matrix.
log "ping check"
$SSH $HOST "$KEXEC $CLIENT -- ping -c 3 -W 2 -I net1 $SERVER_IP" >/dev/null 2>&1 \
  && log "  ✓ pod→pod reachable on VPC-OVN" \
  || { log "  ✗ NOT reachable on net1"; exit 1; }

# Stop any leftover servers in the server pod
log "Cleaning prior servers"
$SSH $HOST "$KEXEC $SERVER -- bash -c 'pkill iperf3 2>/dev/null; pkill netserver 2>/dev/null; pkill sockperf 2>/dev/null; true'" >/dev/null 2>&1
sleep 2

# Start persistent servers in server pod (bind to net1 IP so VPC-OVN is exercised)
log "Starting servers (bound to $SERVER_IP)"
$SSH $HOST "$KEXEC $SERVER -- bash -c 'nohup iperf3 -s -B $SERVER_IP >/tmp/iperf3.log 2>&1 &'" >/dev/null 2>&1
$SSH $HOST "$KEXEC $SERVER -- bash -c 'nohup netserver -p 12865 -L $SERVER_IP -D >/tmp/netserver.log 2>&1 &'" >/dev/null 2>&1
$SSH $HOST "$KEXEC $SERVER -- bash -c 'nohup sockperf server -i $SERVER_IP -p 11111 >/tmp/sockperf.log 2>&1 &'" >/dev/null 2>&1
sleep 4
log "Servers running"

run_bench() {
  local name=$1 cmd=$2 run=$3
  local outfile="$OUT/${name}-run${run}"
  log "  ▶ $name run$run"
  $SSH $HOST "$KEXEC $CLIENT -- bash -c '$cmd'" > "${outfile}" 2>&1 &
  local CMDPID=$!
  # mpstat inside the client POD (per-core cpu of the pod's view)
  $SSH $HOST "$KEXEC $CLIENT -- bash -c 'mpstat -P ALL 1 62 2>&1'" > "${outfile}.mpstat.txt" 2>&1 &
  wait $CMDPID
  sleep 30
}

NRUNS=5
DUR=60

log "===== Pod-to-pod VPC-OVN benchmark matrix (5 runs × 60s, ~80 min) ====="

for i in $(seq 1 $NRUNS); do
  log "=== Round $i / $NRUNS ==="
  run_bench "iperf3-tcp-1stream"     "iperf3 -c $SERVER_IP -B $CLIENT_IP -t $DUR --json" $i
  run_bench "iperf3-tcp-8stream"     "iperf3 -c $SERVER_IP -B $CLIENT_IP -t $DUR -P 8 --json" $i
  run_bench "iperf3-tcp-16stream"    "iperf3 -c $SERVER_IP -B $CLIENT_IP -t $DUR -P 16 --json" $i
  run_bench "iperf3-udp-max"         "iperf3 -c $SERVER_IP -B $CLIENT_IP -u -b 0 -t $DUR --json" $i
  run_bench "iperf3-udp-64b"         "iperf3 -c $SERVER_IP -B $CLIENT_IP -u -b 0 -l 64 -t $DUR --json" $i
  run_bench "iperf3-udp-1400b"       "iperf3 -c $SERVER_IP -B $CLIENT_IP -u -b 0 -l 1400 -t $DUR --json" $i
  run_bench "netperf-tcp-rr"         "netperf -H $SERVER_IP -L $CLIENT_IP -t TCP_RR -l $DUR" $i
  run_bench "netperf-udp-rr"         "netperf -H $SERVER_IP -L $CLIENT_IP -t UDP_RR -l $DUR" $i
  run_bench "netperf-tcp-stream-1b"  "netperf -H $SERVER_IP -L $CLIENT_IP -t TCP_STREAM -l $DUR -- -m 1" $i
  run_bench "sockperf-pingpong"      "sockperf ping-pong -i $SERVER_IP -p 11111 -t $DUR --full-rtt" $i
  run_bench "netperf-tcp-crr"        "netperf -H $SERVER_IP -L $CLIENT_IP -t TCP_CRR -l $DUR" $i
done

log "===== Stopping servers ====="
$SSH $HOST "$KEXEC $SERVER -- bash -c 'pkill iperf3; pkill netserver; pkill sockperf; true'" >/dev/null 2>&1

log "===== DONE ====="
log "Results in $OUT (file count: $(ls $OUT | wc -l))"
