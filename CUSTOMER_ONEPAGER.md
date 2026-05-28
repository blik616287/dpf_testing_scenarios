# NVIDIA DPF on BlueField-3 — Pod-to-Pod Acceleration: Results at a Glance

**What was tested:** NVIDIA DPF v25.10.1 pod-to-pod networking on identical Supermicro servers with BlueField-3 DPUs over a 40 GbE fabric, across three configurations:

| Configuration | Dataplane | Purpose |
|---|---|---|
| **A — Passthrough** | Cilium eBPF on the host kernel; DPU acts as a wire | Baseline (no DPU offload) |
| **B — VPC-OVN Accelerated** | OVN offloaded to the DPU's OVS-DOCA engine | DPU acceleration value |
| **B′ — OVN + HBN (ECMP)** | OVN offload + DOCA Host-Based Networking, BGP/ECMP over 4 uplinks | Multi-path aggregation + failover |

Methodology: 11 benchmarks × 5 runs × 60 s (run 1 = warmup; mean over runs 2–5, n=4), all tools (iperf3, netperf, sockperf, mpstat) run inside pods. Hardware held constant across all arms.

---

## Headline: DPU acceleration (A → B)

| Metric | Passthrough | VPC-OVN | Improvement |
|---|---:|---:|---:|
| **Host CPU at line rate** | 21 % busy | ~5 % busy | **−77 %** |
| **TCP request/response rate** | 8,543/s | 23,472/s | **+175 %** |
| **TCP connection rate** | 1,392/s | 5,370/s | **+286 %** |
| **Tail latency (sockperf p99.9)** | 963 µs | 104 µs | **−89 % (9×)** |
| TCP single-stream | 20.5 Gbps | 27.1 Gbps | +33 % |
| TCP 8/16-stream | 39.4 Gbps | 39.4 Gbps | tied (40 GbE wire limit*) |

> **The DPU does the dataplane work, freeing host CPU cores — while simultaneously delivering faster transactions and dramatically tighter tail latency.** At line rate both arms saturate the wire, so the win shows up as freed host cores and lower latency, not higher peak Gbps.

---

## HBN / ECMP: multi-uplink aggregation + resilience (B′)

- **Bandwidth aggregation:** a single pod pair reaches ~37 Gbps; with multiple concurrent pairs, total throughput scales to **~77 Gbps across the 4 uplinks (≈ 2× a single 40 GbE uplink)**, balanced ~50/50 over both uplinks on both DPUs.
- **Sub-second failover:** when one uplink's BGP session was dropped mid-test, throughput **held at 36.3 Gbps on the surviving uplink** with no collapse.
- **Host CPU stays low** (~4–6 %, on par with VPC-OVN accelerated; the DPU adds **no incremental Arm CPU** under load).
- **Trade-off — latency-sensitive workloads:** HBN's round-trip and connection-rate performance sits at the non-offloaded software level, not the hardware-offloaded level:

  | Metric | VPC-OVN HW | HBN |
  |---|---:|---:|
  | TCP_RR | 23,472/s | 13,858/s |
  | TCP_CRR | 5,370/s | 2,398/s |
  | sockperf UDP p99.9 | 104 µs | 133 µs |

  This is because part of the OVN+HBN per-packet path falls to the software datapath. Bulk throughput is unaffected.

**Choose by workload:** HBN for **throughput / multi-uplink aggregation / path resilience**; VPC-OVN HW for **latency-sensitive RPC / connection-heavy** workloads.

---

## Important context for customers

- **40 GbE is a lab switchport configuration, not a BlueField-3 limit** — BF-3 supports 200 GbE/port; these are line-rate numbers *as configured in this lab*.
- **Host PCIe is Gen3** (older Supermicro chassis) — not a bottleneck at 40 G, but a Gen5 host would unlock higher ceilings.
- **UDP send-rate gains are sender-side**; the single-threaded test receiver is the bottleneck in every arm, so effective received rate is lower than the headline send rate.
- **Sample size n=4 per arm** — reported deltas (+33 % to +286 %, −77 % to −89 %) far exceed run-to-run variance.
- **HBN deployment maturity:** the HBN (B′) configuration required substantial manual effort to stand up against several DPF v25.10.1 issues (on the order of 40–80 engineer-hours) and is **not yet reproducible from a single command**. The VPC-OVN (A/B) path was operationally straightforward. For HBN production adoption, plan for hardening work.

---

## Bottom line

**DPF VPC-OVN acceleration delivers clear, reproducible wins on identical hardware:** host CPU drops ~77 % at line rate, transaction/connection rates rise 2.7–3.9×, and tail latency drops 9×. The DPU pays for itself by freeing host cores while improving latency and connection scaling.

**HBN/ECMP adds multi-uplink bandwidth aggregation (~77 Gbps over 4 uplinks) and sub-second failover** — with a latency trade-off on small-packet RPC workloads and additional deployment complexity to plan for today.

*Full methodology, raw data, and detailed analysis: `BENCHMARK_REPORT.md`.*
