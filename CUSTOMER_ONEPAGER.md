# NVIDIA DPF on BlueField-3 — Pod-to-Pod Acceleration: Results at a Glance

**What was tested:** NVIDIA DPF v25.10.1 pod-to-pod networking on identical Supermicro servers with BlueField-3 DPUs over a 40 GbE fabric, across three configurations:

| Configuration | Dataplane | Purpose |
|---|---|---|
| **A — Passthrough** | Cilium eBPF on the host kernel; DPU acts as a wire | Baseline (no DPU offload) |
| **B — VPC-OVN Accelerated** | OVN offloaded to the DPU's OVS-DOCA engine | DPU acceleration value |
| **B′ — OVN + HBN (ECMP)** | OVN offload + DOCA Host-Based Networking, BGP/ECMP over 4 uplinks | Multi-path aggregation + failover |

Methodology: 11 benchmarks × 5 runs × 60 s (run 1 = warmup; mean over runs 2–5, n=4), all tools (iperf3, netperf, sockperf, mpstat) run inside pods. Hardware held constant across all arms.

The data supports **two distinct comparisons** — both matter:

---

## 1. Full-stack value: host networking → DPU-accelerated (A → B)

*What you gain moving from a host-kernel CNI to DPU-offloaded OVN.*

| Metric | Passthrough (A) | VPC-OVN (B) | Improvement |
|---|---:|---:|---:|
| **Host CPU at line rate** | 21 % busy | ~5 % busy | **−77 %** |
| **TCP request/response rate** | 8,543/s | 23,472/s | **+175 %** |
| **TCP connection rate** | 1,392/s | 5,370/s | **+286 %** |
| **Tail latency (sockperf p99.9)** | 963 µs | 104 µs | **−89 % (9×)** |
| TCP single-stream | 20.5 Gbps | 27.1 Gbps | +33 % |
| TCP 8/16-stream | 39.4 Gbps | 39.4 Gbps | tied (40 GbE wire limit*) |

> **The DPU does the dataplane work, freeing host CPU cores — while delivering faster transactions and dramatically tighter tail latency.** At line rate both arms saturate the wire, so the win is freed host cores + lower latency, not higher peak Gbps.

## 2. Isolating the silicon: hardware offload OFF → ON (apples-to-apples)

*Same cluster, same CNI, same pods/IPs — only the `hw-offload` flag toggled. This isolates what the BlueField eswitch silicon contributes, independent of moving the dataplane to the DPU.*

| Metric | OVN sw (offload off) | OVN HW (offload on) | Improvement |
|---|---:|---:|---:|
| **TCP 8 / 16-stream** | 15.7 Gbps | 39.4 Gbps | **+150 %** |
| **Host CPU at line rate** | ~10 % busy | ~5 % busy | **−51 %** |
| **Tail latency (sockperf p99.9)** | 186 µs | 104 µs | **−44 %** |
| TCP single-stream | 18.3 Gbps | 27.1 Gbps | +48 % |
| TCP_RR | 16,244/s | 23,472/s | +44 % |
| UDP_RR | 17,161/s | 26,834/s | +56 % |
| TCP_CRR | 4,500/s | 5,370/s | +19 % |
| **DPU Arm efficiency** | 0.111 cores/Gbps | 0.064 cores/Gbps | **1.7× more bits/cycle** |

> **The eswitch silicon is what makes OVN-on-DPU viable at line rate.** In pure software the DPU's OVS pipeline caps multi-stream throughput at ~15.7 Gbps; hardware offload uncaps it to the full 39.4 Gbps wire while *halving* host CPU and *cutting tail latency by 44 %* — and moves 1.7× more traffic per DPU Arm cycle. This is the silicon contribution, cleanly separated from the dataplane-relocation benefit in comparison #1.

---

## 3. HBN / ECMP: multi-uplink aggregation + resilience (B′)

- **Bandwidth aggregation:** a single pod pair reaches ~37 Gbps; with multiple concurrent pairs, total throughput scales to **~77 Gbps across the 4 uplinks (≈ 2× a single 40 GbE uplink)**, balanced ~50/50 over both uplinks on both DPUs.
- **Sub-second failover:** when one uplink's BGP session was dropped mid-test, throughput **held at 36.3 Gbps on the surviving uplink** with no collapse.
- **Host CPU stays low** (~4–6 %, on par with VPC-OVN accelerated; **no incremental DPU Arm CPU** under load).
- **Trade-off — latency-sensitive workloads:** HBN's round-trip / connection-rate performance sits at the non-offloaded software level, not the hardware-offloaded level:

  | Metric | VPC-OVN HW | HBN |
  |---|---:|---:|
  | TCP_RR | 23,472/s | 13,858/s |
  | TCP_CRR | 5,370/s | 2,398/s |
  | sockperf UDP p99.9 | 104 µs | 133 µs |

  (Part of the OVN+HBN per-packet path falls to the software datapath; bulk throughput is unaffected.)

**Choose by workload:** HBN for **throughput / multi-uplink aggregation / path resilience**; VPC-OVN HW for **latency-sensitive RPC / connection-heavy** workloads.

---

## Important context for customers

- **40 GbE is a lab switchport configuration, not a BlueField-3 limit** — BF-3 supports 200 GbE/port; these are line-rate numbers *as configured in this lab*.
- **Host PCIe is Gen3** (older Supermicro chassis) — not a bottleneck at 40 G, but a Gen5 host would unlock higher ceilings.
- **UDP send-rate gains are sender-side**; the single-threaded test receiver is the bottleneck in every arm, so effective received rate is lower than the headline send rate.
- **Sample size n=4 per arm** — reported deltas far exceed run-to-run variance.
- **HBN deployment maturity:** the HBN (B′) configuration required substantial manual effort to stand up against several DPF v25.10.1 issues (on the order of 40–80 engineer-hours) and is **not yet reproducible from a single command**. The VPC-OVN (A/B) path was operationally straightforward. For HBN production adoption, plan for hardening work.

---

## Bottom line

**DPF VPC-OVN acceleration delivers clear, reproducible wins on identical hardware.** Against a host-kernel baseline (comparison #1): host CPU −77 %, transaction/connection rates +175 %/+286 %, tail latency −89 % (9×). Isolating the silicon alone (comparison #2): hardware offload takes OVN-on-DPU from 15.7 → 39.4 Gbps multi-stream, halves host CPU, cuts tail latency 44 %, and is 1.7× more Arm-cycle-efficient. The DPU pays for itself by freeing host cores while improving latency and connection scaling.

**HBN/ECMP adds multi-uplink bandwidth aggregation (~77 Gbps over 4 uplinks) and sub-second failover** — with a latency trade-off on small-packet RPC workloads and additional deployment complexity to plan for today.

*Full methodology, raw data, and detailed analysis: `BENCHMARK_REPORT.md`.*
