# NVIDIA DPF on BlueField-3 — Pod-to-Pod Networking: Results Summary

**Setup:** NVIDIA DPF v25.10.1 on identical Supermicro servers with BlueField-3 DPUs, 40 GbE fabric. Four configurations measured, 11 benchmarks × 5 runs × 60 s each (run 1 = warmup; mean over runs 2–5, n=4); all tools (iperf3, netperf, sockperf, mpstat) run inside pods; hardware held constant across arms.

| Arm | Configuration | What it isolates |
|---|---|---|
| **Cilium** | Passthrough — Cilium eBPF on host kernel, DPU is a wire | Baseline (no DPU) |
| **OVN hw-offload OFF** | OVN dataplane on the DPU, but in software (OVS-DOCA on Arm) | DPU placement, no silicon |
| **OVN hw-offload ON** | OVN dataplane hardware-offloaded to the BlueField eswitch | Full DPU acceleration |
| **OVN + HBN** | OVN offload + DOCA HBN, BGP/ECMP over 4 uplinks | Multi-path aggregation + failover |

---

## Four-way results (n=4)

| Metric | Cilium | OVN hw-off | **OVN hw-on** | OVN + HBN |
|---|---:|---:|---:|---:|
| TCP single-stream (Gbps) | 20.5 | 18.3 | **27.1** | 36.6 |
| TCP 8 / 16-stream (Gbps) | 39.4 | 15.7 | **39.4** | 36.8 |
| UDP max send (Gbps)¹ | 9.2 | 22.6 | **23.9** | 16.2 |
| TCP_RR (trans/s) | 8,543 | 16,244 | **23,472** | 13,858 |
| UDP_RR (trans/s) | 10,154 | 17,161 | **26,834** | 15,079 |
| TCP_CRR (conn/s) | 1,392 | 4,500 | **5,370** | 2,398 |
| sockperf p99.9 latency (µs) | 327.7 | 108.7 | **63.9** | 132.9 |
| sockperf p99.99 latency (µs) | 963 | 186 | **104** | 277.5 |
| Host CPU at line rate² | 21 % | ~10 % | **~5 %** | ~6 % |

¹ UDP send-rate is sender-side; the single-threaded test receiver is the bottleneck in every arm, so effective received rate is lower. ² Host-CPU composition differs by pod placement (see Methodology); the dataplane indicator (`%sys`+`%soft`) is ~4 % for both OVN hw-on and HBN.

**Two comparisons matter:**

- **Full-stack value (Cilium → OVN hw-on):** host CPU **−77 %**, TCP_RR **+175 %**, TCP_CRR **+286 %**, p99.9 latency **−80 % (5.1×)**, p99.99 **−89 % (9.3×)**. *The DPU does the dataplane work, freeing host cores while delivering faster transactions and tighter tail latency.*
- **Silicon contribution (hw-offload OFF → ON, apples-to-apples — same cluster/CNI/pods, only the offload flag toggled):** multi-stream throughput **15.7 → 39.4 Gbps (+150 %)**, host CPU **−51 %**, p99.9 latency **−41 %**, and **1.7× more bits per DPU-Arm cycle**. *In software the DPU's OVS pipeline caps at ~15.7 Gbps; the eswitch silicon is what uncaps it to line rate.*

---

## OVN + HBN: multi-uplink aggregation, resilience, and the latency trade-off

- **Bandwidth aggregation:** a single pod pair reaches ~37 Gbps; with multiple concurrent pairs, total throughput scales to **~77 Gbps across the 4 uplinks (≈ 2× a single 40 GbE uplink)**, balanced ~50/50 over both uplinks on both DPUs.
- **Sub-second failover:** dropping one uplink's BGP session mid-test held throughput at **36.3 Gbps on the surviving uplink** — no collapse.
- **Host CPU stays low** (~6 %; no incremental DPU Arm CPU under load — bulk traffic is hardware-offloaded).
- **Latency trade-off (important, but bounded):** **Large/long-lived flows are ~100 % hardware-offloaded** — verified on the DPU eswitch during a 36.4 Gbps flow (≈100 % of bytes on the hardware `dp:doca` path), which is why throughput, aggregation, and DPU-CPU are at full offload levels. The penalty is confined to **small-packet RR and connection-churn (CRR)**: connection *setup* runs in software, and the OVN+HBN offloaded pipeline is deeper than plain VPC-OVN. Net effect — TCP_RR 13,858 vs hw-on 23,472; sockperf p99.9 132.9 µs vs hw-on 63.9 µs; TCP_CRR 2,398 vs 5,370 (hit hardest). Bulk-throughput workloads see no penalty.

**Choose by workload:** **OVN hw-on** for latency-sensitive RPC / connection-heavy services; **OVN + HBN** for throughput, multi-uplink bandwidth aggregation, and path resilience.

---

## Key context & caveats

- **40 GbE is a lab switchport choice, not a BlueField-3 limit** — BF-3 supports 200 GbE/port. Line-rate figures are *as configured in this lab*.
- **Host PCIe is Gen3** (older Supermicro chassis) — not a bottleneck at 40 G, but a Gen5 host would raise ceilings.
- **Tail-latency labels:** values above are the true p99.9 (sockperf `99.900` line); p99.99 is the deeper tail. (An earlier draft cited the p99.99 number as "p99.9" — corrected here.)
- **Pod placement differs:** Cilium and HBN pods run on the host cluster; the hw-off/hw-on arms run on the DPU tenant cluster. The fair cross-arm dataplane-CPU indicator is `%sys`+`%soft`.
- **Sample size n=4 per arm** — reported deltas far exceed run-to-run variance.
- **HBN deployment maturity:** standing up the HBN arm required substantial manual effort against several DPF v25.10.1 issues (~40–80 engineer-hours) and is **not yet reproducible from a single command**; the OVN (passthrough / hw-off / hw-on) path was operationally straightforward. Plan hardening work before HBN production adoption.

---

## Bottom line

**DPF VPC-OVN acceleration delivers clear, reproducible wins on identical hardware:** vs a host-kernel baseline, host CPU drops ~77 % at line rate, transaction/connection rates rise 2.7–3.9×, and tail latency drops 5.1× at p99.9 (9.3× at p99.99). Isolating the silicon alone, hardware offload takes OVN-on-DPU from 15.7 → 39.4 Gbps multi-stream while halving host CPU and cutting tail latency — at 1.7× better Arm-cycle efficiency. **HBN adds ~77 Gbps multi-uplink aggregation and sub-second failover**, with a latency trade-off on small-packet RPC workloads and added deployment complexity to plan for today.

*Full methodology, raw data, and analysis: `BENCHMARK_REPORT.md`.*
