# HBN Matrix v2 — n=5 × 60s (n=4 stats over runs 2-5), MTU 9000

Methodology now matches Test Sets 1-2 exactly: 5 runs × 60 s per test, 30 s idle between
runs, run 1 discarded as warmup. Host CPU AND DPU Arm CPU captured via continuous mpstat
on all 4 nodes (.90, .253 hosts; .29, .20 DPU Arms), sliced to per-test windows.

## Throughput / latency matrix (mean ± stdev over runs 2-5)

| Test                | metric       | mean ± σ            |
|---------------------|--------------|---------------------|
| iperf3 TCP 1-stream | Gbps         | 36.63 ± 0.40        |
| iperf3 TCP 8-stream | Gbps         | 36.96 ± 0.44        |
| iperf3 TCP 16-stream| Gbps         | 36.80 ± 0.65        |
| iperf3 UDP max      | Gbps_send    | 16.21 ± 0.38        |
| iperf3 UDP max      | loss %       | 41.66 ± 6.67        |
| iperf3 UDP 64 B     | Gbps_send    |  0.227 ± 0.003      |
| iperf3 UDP 64 B     | loss %       | 12.43 ± 2.66        |
| iperf3 UDP 1400 B   | Gbps_send    |  4.40 ± 0.04        |
| iperf3 UDP 1400 B   | loss %       |  8.12 ± 1.65        |
| netperf TCP_RR      | mean µs      | 72.05 ± 2.07        |
| netperf TCP_RR      | p99 µs       | 97.25 ± 1.50        |
| netperf TCP_RR      | trans/s      | 13858 ± 390         |
| netperf UDP_RR      | mean µs      | 66.22 ± 2.18        |
| netperf UDP_RR      | p99 µs       | 92.00 ± 1.63        |
| netperf UDP_RR      | trans/s      | 15079 ± 485         |
| netperf TCP_CRR     | conn/s       | 2398 ± 8            |
| netperf TCP_STREAM  | Mbps         | 31885 ± 270         |

## Host CPU (busy % = 100-idle, breakdown of "all" across 48 cores per host)

Idle baseline: .90 = 2.76 % busy; .253 = 0.16 % busy.

| Test                | .90 busy / sys+soft | .253 busy / sys+soft |
|---------------------|---------------------|----------------------|
| iperf3 TCP 1-stream | 5.05 / 2.89         | 2.86 / 2.66          |
| iperf3 TCP 8-stream | 5.94 / 3.97         | 4.05 / 3.85          |
| iperf3 TCP 16-stream| 6.35 / 4.26         | 4.11 / 3.93          |
| iperf3 UDP max      | 4.96 / 2.72         | 1.77 / 1.28          |
| iperf3 UDP 1400 B   | 5.04 / 2.59         | 2.83 / 2.11          |
| iperf3 UDP 64 B     | 4.99 / 2.56         | 3.12 / 2.32          |
| netperf TCP_RR      | 3.77 / 1.45         | 0.85 / 0.69          |
| netperf UDP_RR      | 3.62 / 1.35         | 0.82 / 0.65          |
| netperf TCP_CRR     | 3.76 / 1.37         | 0.46 / 0.34          |
| netperf TCP_STREAM  | 5.03 / 2.78         | 2.65 / 2.51          |

At TCP line rate the host adds only ~3–4 pts of %sys+%soft over idle = the dataplane work
is offloaded. (Pods are host-cluster, so %usr also reflects iperf3 itself — small.)

## DPU Arm CPU (busy % across 16 Arm cores per DPU)

Idle baseline: .29 (gpu1) = 7.77 % busy; .20 (gpu2) = 8.49 % busy.

The ~7–8 % idle floor is the steady-state of the DPU control-plane containers
(doca-hbn/FRR, ovnkube-node, multus, sriov-device-plugin, kubelet).

| Test                | .29 busy / sys+soft | .20 busy / sys+soft |
|---------------------|---------------------|---------------------|
| iperf3 TCP 1-stream | 7.89 / 0.80         | 8.08 / 0.92         |
| iperf3 TCP 8-stream | 7.82 / 0.78         | 7.98 / 0.86         |
| iperf3 TCP 16-stream| 7.84 / 0.79         | 8.04 / 0.88         |
| iperf3 UDP max      | 7.95 / 0.85         | 8.06 / 0.89         |
| iperf3 UDP 1400 B   | 7.83 / 0.79         | 8.02 / 0.89         |
| iperf3 UDP 64 B     | 7.94 / 0.85         | 8.03 / 0.87         |
| netperf TCP_RR      | 7.79 / 0.76         | 7.93 / 0.86         |
| netperf UDP_RR      | 7.93 / 0.84         | 8.05 / 0.88         |
| netperf TCP_CRR     | 8.11 / 0.83         | 10.46 / 0.94        |
| netperf TCP_STREAM  | 7.90 / 0.81         | 8.07 / 0.91         |

**Headline (the key finding):** the DPU Arm busy % under load is *indistinguishable* from
idle — load minus idle ≈ 0 across every test. %sys+%soft is <1 %. The Arm is **not** doing
the dataplane; the eswitch silicon is. Hardware offload is doing what it's supposed to.

(TCP_CRR on gpu2 sees a small bump to 10.5 % from the connection-setup churn the receiver
processes — still trivial.)
