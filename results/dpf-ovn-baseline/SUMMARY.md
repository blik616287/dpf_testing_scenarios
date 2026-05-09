# DPF Baseline — Pod-to-Pod Benchmark Summary

**Date:** 2026-05-04 / 2026-05-05
**Cluster:** `dpf-ovn-baseline` (DPF Zero Trust passthrough mode)
**Path under test:** Pod ↔ pod via cilium native routing, traffic over 40G fabric (host CPU does cilium BPF datapath)
**Pod placement:** `bench-client` on gpu1 (control-plane), `bench-server` on gpu2 (worker)
**Methodology:** 5 runs per benchmark, 60 s each, 30 s idle gap; first run discarded as warmup → n=4 reported.

## Results table

| Benchmark | n | mean | stddev | min | max | notes |
|---|---:|---:|---:|---:|---:|---|
| **TCP 1-stream** (Gbps) | 4 | **20.48** | 0.30 | 20.17 | 20.90 | retx mean ~1k |
| **TCP 8-stream** (Gbps) | 4 | **39.40** | 0.08 | 39.33 | 39.47 | line rate |
| **TCP 16-stream** (Gbps) | 4 | **39.43** | 0.02 | 39.40 | 39.45 | line rate |
| **UDP max** (Gbps) | 4 | **9.19** | 0.12 | 9.02 | 9.28 | host CPU bound |
| **UDP 1400B** (Gbps) | 4 | 1.78 | 0.02 | 1.77 | 1.80 | |
| **UDP 64B** (Gbps) | 4 | 0.08 | 0.00 | 0.08 | 0.09 | small-packet PPS test |
| **UDP 64B PPS** (kpps) | 4 | **165** | 3 | — | — | host CPU bottlenecked here |
| **TCP_RR latency** (µs) | 4 | **117.1** | 3.3 | — | — | 8 543 trans/s avg |
| **UDP_RR latency** (µs) | 4 | **98.6** | 3.2 | — | — | 10 154 trans/s avg |
| **TCP_STREAM 1B** (Mbps) | 4 | 7.94 | 0.19 | 7.72 | 8.16 | system call overhead dominant |
| **TCP_CRR** (conn/s) | 4 | **1391.6** | 20.4 | 1366 | 1411 | ~720 µs per connection (TIME_WAIT bound) |
| **sockperf RTT mean** (µs) | 4 | 95.5 | 3.6 | 91.8 | 99.5 | |
| **sockperf p50** (µs) | 4 | 92.1 | 3.9 | 88.1 | 96.7 | |
| **sockperf p99** (µs) | 4 | **170.9** | 1.4 | 170.0 | 172.9 | |
| **sockperf p99.9** (µs) | 4 | 327.7 | 19.1 | 312.3 | 354.8 | tail |

## Reference: fabric ceiling (host-PF, no pod overhead)

For context — same benchmarks run host-PF to host-PF (no cilium, no pod, just bare 40G NICs through DPU passthrough chain):

| Benchmark | Pod-to-pod (this run) | Fabric ceiling (host-PF) | Cilium overhead |
|---|---:|---:|---:|
| TCP 8-stream | 39.40 Gbps | 39.61 Gbps | ~0.5 % |
| TCP 1-stream | 20.48 Gbps | 25.93 Gbps | ~21 % |
| sockperf p50 RTT | 92.1 µs | ~67 µs | +25 µs |

The 8-stream test is bottlenecked by the 40G fabric, not by cilium. 1-stream and small-packet/PPS tests show meaningful CPU bottlenecks where DPU acceleration is expected to help.

## Where DPF acceleration is expected to deliver uplift

Based on this baseline, the accelerated arm (DPU offloads dataplane) should improve:
- **TCP 1-stream**: should approach the fabric ceiling (~25+ Gbps vs 20.48 here)
- **UDP 64B PPS**: should significantly exceed 165 kpps (DPU silicon vs host CPU)
- **TCP_RR / UDP_RR latency**: should drop (fewer host CPU hops)
- **TCP_CRR**: should improve substantially (conntrack offloaded)
- **Host CPU during TCP 8-stream**: should drop from "multiple cores busy" to near-idle

## Test methodology footnotes

- Benchmarks run via `nsenter -t <pid> -n` from the host into the bench pod's network namespace (kubectl exec was unavailable due to apiserver→kubelet TLS cert issue; functionally equivalent — same network namespace, same kernel, same userspace binary).
- Host-installed iperf3 3.16 / netperf 2.7 / sockperf 3.7.
- Cilium 1.18.4 reconfigured from VXLAN tunnel mode → native routing on `enp14s0f0np0`, with explicit static routes for inter-node pod CIDRs (`100.64.0.0/24`, `100.64.1.0/24`) via the 40G fabric subnet (172.16.97.0/24). Traffic verified to use the 40G PF via PF byte-counter delta during a 5 s iperf3 (~25 GB transferred).

## Raw artifacts

`results/dpf-ovn-baseline/` contains:
- 55 benchmark output files (`.json` for iperf3, plain text for netperf/sockperf)
- 55 `.mpstat.txt` files with per-core CPU samples during each benchmark
- `system-info.txt` — host hardware/kernel/CNI inventory
- `run.log` — full timed log of the run
