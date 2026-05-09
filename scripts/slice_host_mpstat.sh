#!/bin/bash
# Slice the persistent host mpstat captures into per-benchmark windows.
# Reads run.log timestamps (local TZ), converts to UTC, then extracts the
# 60s window for each test from /tmp/host-mpstat.txt on gpu1 and gpu2.
#
# Output:
#   results/dpf-ovn-accelerated/<test>-runN.host-gpu1.mpstat
#   results/dpf-ovn-accelerated/<test>-runN.host-gpu2.mpstat

set -u
SSH="ssh -i /home/ubuntu/.ssh/dpu -o StrictHostKeyChecking=no"
GPU1=ubuntu@172.16.30.90
GPU2=ubuntu@172.16.30.253
OUT=/home/ubuntu/dpf_testing_scenarios/results/dpf-ovn-accelerated

# Pull host mpstat captures locally
$SSH $GPU1 'cat /tmp/host-mpstat.txt' > /tmp/host-mpstat-gpu1.txt 2>/dev/null
$SSH $GPU2 'cat /tmp/host-mpstat.txt' > /tmp/host-mpstat-gpu2.txt 2>/dev/null
echo "  gpu1: $(wc -l < /tmp/host-mpstat-gpu1.txt) lines"
echo "  gpu2: $(wc -l < /tmp/host-mpstat-gpu2.txt) lines"

# Local TZ → UTC offset (script runs on the box where run.log was written).
# date "+%z" gives e.g. "-0700"; convert to seconds.
TZOFF=$(date +%z)
SIGN=${TZOFF:0:1}
HRS=${TZOFF:1:2}
MIN=${TZOFF:3:2}
OFFSEC=$(( ${HRS#0} * 3600 + ${MIN#0} * 60 ))
[ "$SIGN" = "-" ] && OFFSEC=$(( -OFFSEC ))
# Local time + (-OFFSEC) = UTC. So UTC = local - OFFSEC.
echo "  TZ offset: $TZOFF (UTC = local - ${OFFSEC}s)"

# Parse run.log: "[HH:MM:SS]   ▶ <test>-run<N>"
grep --text "▶" "$OUT/run.log" | while read -r line; do
  ts_local=$(echo "$line" | grep -oE '^\[[0-9:]+\]' | tr -d '[]')
  test=$(echo "$line" | sed -E 's/.*▶ (.+) run([0-9]+).*/\1/')
  run=$(echo  "$line" | sed -E 's/.*▶ .+ run([0-9]+).*/\1/')

  # Convert local "HH:MM:SS" today → UTC HH:MM:SS
  today=$(date +%Y-%m-%d)
  ts_utc=$(date -u -d "${today}T${ts_local} ${TZOFF}" +%H:%M:%S 2>/dev/null)
  [ -z "$ts_utc" ] && continue

  end_utc=$(date -u -d "${today}T${ts_local} ${TZOFF} + 60 seconds" +%H:%M:%S 2>/dev/null)

  # Extract the 60s window from each host mpstat
  for host in gpu1 gpu2; do
    src=/tmp/host-mpstat-${host}.txt
    dst="$OUT/${test}-run${run}.host-${host}.mpstat"
    awk -v start="$ts_utc" -v end="$end_utc" '
      $1 ~ /^[0-9][0-9]:[0-9][0-9]:[0-9][0-9]$/ {
        if ($1 >= start && $1 < end) inrange=1; else inrange=0
      }
      inrange { print }
    ' "$src" > "$dst"
  done
done

echo "  per-test slices written to $OUT/*.host-{gpu1,gpu2}.mpstat"
echo "  total: $(ls $OUT/*.host-*.mpstat 2>/dev/null | wc -l) files"
