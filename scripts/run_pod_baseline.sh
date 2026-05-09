#!/bin/bash
# Pod-to-pod baseline benchmark (Test Case 2 matrix)
# Runs benchmarks INSIDE the pod's network namespace via nsenter
# (workaround for kubelet TLS cert issue blocking kubectl exec)
#
# Cluster A (baseline): cilium native routing, pods talk over 40G fabric
# Pods: bench-client (gpu1) ↔ bench-server (gpu2)

set -u
export KUBECONFIG=/home/ubuntu/.kube/dpf-config
SSH="ssh -i /home/ubuntu/.ssh/dpu -o StrictHostKeyChecking=no"
GPU1=ubuntu@172.16.30.90
GPU2=ubuntu@172.16.30.253

OUT=/home/ubuntu/dpf_testing_scenarios/results/dpf-ovn-baseline
mkdir -p "$OUT"

log() { echo "[$(date +%H:%M:%S)] $*"; }

# Get pod PIDs (network namespace owners)
get_pid() {
  local host=$1; local podname=$2
  $SSH $host "sudo crictl --runtime-endpoint unix:///run/spectro/containerd/containerd.sock ps -q --name tools | head -1 | xargs -I{} sudo crictl --runtime-endpoint unix:///run/spectro/containerd/containerd.sock inspect -o json {} | python3 -c 'import json,sys; print(json.load(sys.stdin)[\"info\"][\"pid\"])'" 2>/dev/null | tail -1
}

CLIENT_PID=$(get_pid $GPU1 bench-client)
SERVER_PID=$(get_pid $GPU2 bench-server)

log "Bench pod PIDs: client=$CLIENT_PID (gpu1), server=$SERVER_PID (gpu2)"
if [ -z "$CLIENT_PID" ] || [ -z "$SERVER_PID" ]; then
  log "✗ Could not find pod PIDs — aborting"; exit 1
fi

# Get server pod IP from K8s
SERVER_IP=$(kubectl get pod bench-server -o jsonpath='{.status.podIP}' 2>/dev/null)
log "server pod IP: $SERVER_IP"
[ -z "$SERVER_IP" ] && { log "no server IP"; exit 1; }

# Helpers to run cmd inside pod's netns
ns_client() { $SSH $GPU1 "sudo nsenter -t $CLIENT_PID -n $1"; }
ns_server() { $SSH $GPU2 "sudo nsenter -t $SERVER_PID -n $1"; }

# Connectivity sanity
log "ping check"
ns_client "ping -c 2 -W 1 $SERVER_IP" >/dev/null && log "  ✓ pod→pod reachable" || { log "  ✗ NOT reachable"; exit 1; }

# Stop any leftover servers from prior runs
log "Cleaning prior servers"
ns_server "pkill iperf3 2>/dev/null; pkill netserver 2>/dev/null; pkill sockperf 2>/dev/null" || true
sleep 2

# Start persistent servers in server pod's netns
log "Starting servers"
ns_server "nohup iperf3 -s >/tmp/iperf3.log 2>&1 &"
ns_server "nohup netserver -p 12865 -L 0.0.0.0 >/tmp/netserver.log 2>&1 &"
ns_server "nohup sockperf server -i 0.0.0.0 -p 11111 >/tmp/sockperf.log 2>&1 &"
sleep 3
log "Servers running"

run_bench() {
  local name=$1 cmd=$2 run=$3
  local outfile="$OUT/${name}-run${run}"
  log "  ▶ $name run$run"
  $SSH $GPU1 "sudo nsenter -t $CLIENT_PID -n $cmd" > "${outfile}" 2>&1 &
  local CMDPID=$!
  # Capture mpstat on client side (for CPU usage of the host doing networking work)
  $SSH $GPU1 "mpstat -P ALL 1 62 2>&1" > "${outfile}.mpstat.txt" &
  wait $CMDPID
  sleep 30
}

NRUNS=5
DUR=60

log "===== Pod-to-pod benchmark matrix (5 runs, 60s each, ~80 min) ====="

for i in $(seq 1 $NRUNS); do
  log "=== Round $i / $NRUNS ==="
  run_bench "iperf3-tcp-1stream"     "iperf3 -c $SERVER_IP -t $DUR --json" $i
  run_bench "iperf3-tcp-8stream"     "iperf3 -c $SERVER_IP -t $DUR -P 8 --json" $i
  run_bench "iperf3-tcp-16stream"    "iperf3 -c $SERVER_IP -t $DUR -P 16 --json" $i
  run_bench "iperf3-udp-max"         "iperf3 -c $SERVER_IP -u -b 0 -t $DUR --json" $i
  run_bench "iperf3-udp-64b"         "iperf3 -c $SERVER_IP -u -b 0 -l 64 -t $DUR --json" $i
  run_bench "iperf3-udp-1400b"       "iperf3 -c $SERVER_IP -u -b 0 -l 1400 -t $DUR --json" $i
  run_bench "netperf-tcp-rr"         "netperf -H $SERVER_IP -t TCP_RR -l $DUR" $i
  run_bench "netperf-udp-rr"         "netperf -H $SERVER_IP -t UDP_RR -l $DUR" $i
  run_bench "netperf-tcp-stream-1b"  "netperf -H $SERVER_IP -t TCP_STREAM -l $DUR -- -m 1" $i
  run_bench "sockperf-pingpong"      "sockperf ping-pong -i $SERVER_IP -p 11111 -t $DUR --full-rtt" $i
  run_bench "netperf-tcp-crr"        "netperf -H $SERVER_IP -t TCP_CRR -l $DUR" $i
done

log "===== Stopping servers ====="
ns_server "pkill iperf3; pkill netserver; pkill sockperf" || true

log "===== DONE ====="
log "Results in $OUT (file count: $(ls $OUT | wc -l))"
