# sockperf UDP ping-pong — HBN (MTU 9000)

5 × 60s runs, runs 2-5 used (n=4), matching T1/T2 methodology (§3.1).
Image: `docker.io/cerotyki/sockperf:latest` (sockperf 3.7-no.git, Jan 2020), `LD_PRELOAD=""`.
Server: `sockperf server -i 0.0.0.0 -p 11111` in `sockperf-server` pod on gpu2.
Client: `sockperf ping-pong -i 10.233.66.17 -p 11111 -t 60 --full-rtt` from `sockperf-client` pod on gpu1.
~900K samples per run.

| Metric  | mean ± stdev (µs) |
|---------|-------------------:|
| mean RTT | 64.6 ± 2.9 |
| p50      | 64.6 ± 2.9 |
| p90      | 73.0 ± 1.0 |
| p99      | 88.7 ± 1.4 |
| **p99.9** | **132.85 ± 1.97** |
| p99.99   | 277.5 ± 21.7 |

Comparison to Test Sets 1-2 (sockperf p99.9):
  Cilium passthrough:  963 µs
  VPC-OVN HW:          104 µs
  **HBN (this):        133 µs**  (= +29 µs over VPC-OVN HW; consistent with the
                                   OVN+HBN per-packet software-path overhead
                                   identified in §7.9 — br-ovn flow chain partial offload)

Per-run details: run{1..5}.txt
