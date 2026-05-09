#!/bin/bash
# Run DPF baseline benchmark suite (Test Case 2 from TEST_CASES.md)
# Server: gpu2 (172.16.97.11), Client: gpu1 (172.16.97.10)
# All benchmarks run from gpu1 against gpu2.
#
# 11 benchmarks × 5 runs = 55 total runs, ~60s each + ~5s overhead.
# Total wall time: ~60-70 minutes.
#
# Results land in results/dpf-ovn-baseline/

set -u
SSH="ssh -i /home/ubuntu/.ssh/dpu -o StrictHostKeyChecking=no"
GPU1=ubuntu@172.16.30.90       # client (mgmt)
GPU2=ubuntu@172.16.30.253      # server (mgmt)
SERVER_IP=172.16.97.11         # gpu2 PF0 fabric IP
CLIENT_IP=172.16.97.10         # gpu1 PF0 fabric IP

OUT=/home/ubuntu/dpf_testing_scenarios/results/dpf-ovn-baseline
mkdir -p "$OUT"

log() { echo "[$(date +%H:%M:%S)] $*"; }

# Make sure host PFs are up + IPs are present (idempotent)
log "Configuring host PF IPs"
$SSH $GPU1 "sudo ip link set dev enp14s0f0np0 up; sudo ip addr replace 172.16.97.10/24 dev enp14s0f0np0; sudo ip neigh flush all" >/dev/null
$SSH $GPU2 "sudo ip link set dev enp14s0f0np0 up; sudo ip addr replace 172.16.97.11/24 dev enp14s0f0np0" >/dev/null

# Stop any leftover servers
log "Cleaning up any previous server processes"
$SSH $GPU2 "sudo pkill -f iperf3 -- -s; sudo pkill -f netserver; sudo pkill -f sockperf" 2>/dev/null
sleep 2

# Start servers on gpu2 (persistent for the whole run)
log "Starting servers on gpu2 (172.16.97.11)"
$SSH $GPU2 "nohup iperf3 -s -B 172.16.97.11 >/tmp/iperf3-server.log 2>&1 &"
$SSH $GPU2 "nohup netserver -p 12865 -L 172.16.97.11 >/tmp/netserver.log 2>&1 &"
sleep 3

# Verify servers up
log "Verifying servers"
$SSH $GPU2 "ss -lnp 2>/dev/null | grep -E ':5201|:12865'"

# Validate connectivity
log "Connectivity check"
if $SSH $GPU1 "ping -c 2 -W 1 $SERVER_IP >/dev/null 2>&1"; then
  log "  ✓ gpu1 → gpu2 reachable"
else
  log "  ✗ gpu1 → gpu2 NOT REACHABLE — aborting"
  exit 1
fi

# Helper to run a benchmark with mpstat parallel CPU capture
run_bench() {
  local name=$1; local cmd=$2; local run=$3; local mpstat_dur=$4
  local outfile="$OUT/${name}-run${run}"
  log "  ▶ $name run$run"
  # Start mpstat on gpu1 (client side; same on gpu2 we'd need separate)
  $SSH $GPU1 "mpstat -P ALL 1 $mpstat_dur > /tmp/mpstat.out 2>&1 &"
  # Run benchmark
  $SSH $GPU1 "$cmd" > "${outfile}" 2>&1
  # Wait for mpstat to finish
  sleep 2
  $SSH $GPU1 "cat /tmp/mpstat.out" > "${outfile}.mpstat.txt" 2>&1
  # Idle gap as per methodology
  sleep 30
}

NRUNS=5
DUR=60
MPSTAT_DUR=$((DUR + 2))

log "===== STARTING BENCHMARK MATRIX ====="
log "Cluster: dpf-ovn-baseline (passthrough), $NRUNS runs each, ${DUR}s per run"

for i in $(seq 1 $NRUNS); do
  log "=== Round $i / $NRUNS ==="
  run_bench "iperf3-tcp-1stream"   "iperf3 -c $SERVER_IP -t $DUR --json"           $i $MPSTAT_DUR
  run_bench "iperf3-tcp-8stream"   "iperf3 -c $SERVER_IP -t $DUR -P 8 --json"      $i $MPSTAT_DUR
  run_bench "iperf3-tcp-16stream"  "iperf3 -c $SERVER_IP -t $DUR -P 16 --json"     $i $MPSTAT_DUR
  run_bench "iperf3-udp-max"       "iperf3 -c $SERVER_IP -u -b 0 -t $DUR --json"   $i $MPSTAT_DUR
  run_bench "iperf3-udp-64b"       "iperf3 -c $SERVER_IP -u -b 0 -l 64 -t $DUR --json"   $i $MPSTAT_DUR
  run_bench "iperf3-udp-1400b"     "iperf3 -c $SERVER_IP -u -b 0 -l 1400 -t $DUR --json" $i $MPSTAT_DUR
  run_bench "netperf-tcp-rr"       "netperf -H $SERVER_IP -t TCP_RR -l $DUR -- -O 'min_latency,mean_latency,p50_latency,p90_latency,p99_latency,max_latency,stddev_latency,trans_rate'" $i $MPSTAT_DUR
  run_bench "netperf-udp-rr"       "netperf -H $SERVER_IP -t UDP_RR -l $DUR -- -O 'min_latency,mean_latency,p50_latency,p90_latency,p99_latency,max_latency,stddev_latency,trans_rate'" $i $MPSTAT_DUR
  run_bench "netperf-tcp-stream-1b" "netperf -H $SERVER_IP -t TCP_STREAM -l $DUR -- -m 1" $i $MPSTAT_DUR
  run_bench "sockperf-pingpong"    "sockperf ping-pong -i $SERVER_IP -t $DUR --full-rtt" $i $MPSTAT_DUR
  run_bench "netperf-tcp-crr"      "netperf -H $SERVER_IP -t TCP_CRR -l $DUR -- -O 'trans_rate'" $i $MPSTAT_DUR
done

log "===== STOPPING SERVERS ====="
$SSH $GPU2 "sudo pkill -f iperf3; sudo pkill -f netserver; sudo pkill -f sockperf" 2>/dev/null

log "===== DONE ====="
log "Results in $OUT"
ls -la $OUT | tail -20
