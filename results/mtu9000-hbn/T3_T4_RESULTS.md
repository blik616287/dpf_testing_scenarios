# Test Case 3 & 4 — OVN+HBN (BGP/ECMP) Benchmark Results

**Date:** 2026-05-25
**Cluster:** `dpf-ovn-hbn` (DPF OVN offload + DOCA HBN, BGP/ECMP)
**Path:** iperf/netperf client pod on host .90 (gpu1 DPU) ⇄ server pod on host .253 (gpu2 DPU), both DPU-offloaded (OVN VF), cross-fabric over HBN ECMP.
**MTU:** pods 8940 (jumbo / "MTU 9000"); HBN SF ifaces 9216; uplinks p0/p1 9216.
**Tools:** iperf3 (throughput/UDP/jitter/PPS), netperf (RR/CRR/STREAM latency). Runs: 3 each, run-1 discarded as warmup, mean of runs 2-3, 20s/run.

---

## T3 Phase 1 — HBN validation  (live capture: `bgp-ecmp-state.txt`)

- **BGP:** all **4 eBGP uplink sessions Established** to leaf AS 65001, **128 prefixes received / 130 sent** each:
  - gpu1 (AS 65010, rtr-id 11.0.0.1): peers 172.16.97.240 (p0_if), 172.16.97.248 (p1_if) — up 20h59m
  - gpu2 (AS 65020, rtr-id 11.0.0.0): peers 172.16.97.244 (p0_if), 172.16.97.250 (p1_if)
- **ECMP:** every BGP route installed with **2 nexthops** (p0_if + p1_if, weight 1) — e.g. `10.10.10.0/23 via .240 p0_if / via .248 p1_if`; zebra nexthop-groups `Valid, Installed`.
- **OVS hardware offload:** active; jumbo line-rate (~37 Gbit/s) confirms eswitch offload (offloaded flows bypass kernel netdev counters — see per-uplink note below).

## T4 — ECMP scaling (iperf3 TCP, MTU 9000)

| Parallel flows | Throughput (Gbit/s) |
|---|---|
| 1  | 34.2 |
| 2  | 35.5 |
| 4  | 36.1 |
| 8  | 36.9 |
| 16 | **37.1** |
| 32 | 36.3 |

**Per-uplink distribution** — cross-node 16-flow run, physical-port byte delta (`per-uplink-distribution.txt`):
- gpu1 (.29): p0 = 47.10 GB (**50.0%**), p1 = 47.12 GB (**50.0%**)
- gpu2 (.20): p0 = 35.33 GB (**37.5%**), p1 = 58.89 GB (**62.5%**)
- ~94 GB moved in 20s (= 37.15 Gbit/s) split across **both** uplinks on **both** DPUs ⇒ cross-node ECMP confirmed.

*Interpretation:* this is a **single pod-pair** test — all flows share one src/dst VF, so it caps at the **per-VF/endpoint ceiling (~37 Gbit/s)** regardless of flow count. ECMP still *distributes* these flows across both uplinks (see split above), but a single pair cannot demonstrate the **aggregate** capacity of the 4 uplinks. For that, see the aggregation test below.

## T4 — 4-uplink BANDWIDTH AGGREGATION (multiple concurrent pod-pairs)  (`agg-bandwidth-test.txt`)

Single-pair throughput is endpoint-bound, so to exercise the 4 ECMP uplinks we run **N concurrent pod-pairs** (separate client pods on gpu1 → separate server pods on gpu2, each on its own DPU VF, each `-P 8`). Aggregate = sum of pairs.

| Concurrent pairs | 1 | 2 | 4 | 6 | 8 |
|---|---|---|---|---|---|
| Aggregate Gbit/s | 36.3 | 70.1 | 76.3 | 69.7 | **78.0** |

- **2 pairs ≈ 2× one pair** (70 vs 36) — confirms the single-pair limit was per-VF, not the fabric.
- Plateau **~76–78 Gbit/s** at 4+ pairs ≈ **2 × 40 GbE = the fabric ceiling** (each uplink ~38.5 Gbit/s = ~96 % of its 40 G line rate). ECMP delivers **~2× a single uplink**; the DPU offload pipeline is not the observed limiter (40 G uplinks saturate first). Uplinks are 40 G in this lab; BF-3 supports 200 G/port.
- **Per-uplink at 8-pair peak (193 GB/20s):** gpu1 rx p0=51% / p1=49%; gpu2 tx p0=50% / p1=50% — **all 4 uplinks balanced ~50/50 = ECMP aggregation across both DPUs.**

## T4 — Throughput / latency matrix (dpf-ovn-hbn, MTU 9000)

| Benchmark | Result |
|---|---|
| TCP single-stream (iperf3) | **37.2 Gbit/s** |
| TCP 8-stream | 36.9 Gbit/s |
| TCP 16-stream | 37.1 Gbit/s |
| TCP single-stream (netperf TCP_STREAM) | 31.3 Gbit/s |
| UDP max throughput (`-b 0`) | 15.6 Gbit/s (38% loss — uncapped flood) |
| UDP 1400-byte | 4.4 Gbit/s (5.4% loss) |
| UDP 64-byte (PPS) | 0.23 Gbit/s ≈ 450K pps |
| TCP_RR latency | 72.5 µs mean, 97 µs P99, 13.7K tran/s |
| UDP_RR latency | 66 µs mean, 92 µs P99, 15.0K tran/s |
| TCP_CRR (conn rate) | 412 µs, 2.4K conn/s |
| Jitter (UDP) | ~0.001–0.006 ms |

## T3 Phase 3 — Failover (real BGP-layer uplink kill)  (`failover-test.txt`)

8-stream cross-node flow, 45s. `p0_if` downed **inside the HBN container** at t≈10s (drops the eBGP session to leaf .240; hold-time 9s), restored at t≈28s:
- **BGP confirmed dropped:** during the window, peer **.240 (p0_if) → Active, 0 prefixes**; peer **.248 (p1_if) stayed Established, 128 prefixes** → genuine single-uplink operation.
- Throughput **held 36.3 Gbit/s on p1 alone** vs ~39 dual-uplink (**~7% drop, no collapse**) — a single pod-pair's ~37 Gbit/s is endpoint/VF-bound and fits within one 40 G uplink, so the surviving uplink carries it.
- Transients: **250 retransmits** at the drop, **485** when p0 rejoined ECMP (each <1s of loss).
- 45s aggregate: **191 GB, 36.4 Gbit/s, 883 retransmits**. After `p0_if up`, **.240 re-Established** (128 prefixes). **Failover is effectively seamless.**

> Note: an initial attempt downing the *host-side* p0 netdev did **not** drop the eBGP session (verified — timer never reset), so it was discarded; the result above is the valid BGP-layer test.

---

## Notes / scope

- **sockperf (P50/P99.9 tail latency)** — no pullable image in this environment; netperf P99 used for tail.
- **A/B comparison not produced**: only `dpf-ovn-hbn` is deployed (current rebuild). The Dataset-1 (baseline passthrough) and Dataset-2 (OVN-only accelerated) "A" columns require redeploying those cluster profiles (sequential teardown/redeploy per CLAUDE.md). This file is the complete **B = dpf-ovn-hbn** dataset + ECMP scaling + failover.
- Raw outputs (on host .90 `/root/bench-results/dpf-ovn-hbn/` **and** mirrored in this dir):
  - `ecmp-scaling/{1,2,4,8,16,32}flows-run{1,2,3}.json` — iperf3 scaling (18 runs)
  - `udp-{max,64,1400}-run{1,2,3}.json`, `netperf-{tcprr,udprr,tcpcrr,tcpstream}-run{1,2,3}.txt` — matrix
  - `bgp-ecmp-state.txt` — live BGP summary + ECMP routes + nexthop-groups + cumulative per-uplink
  - `per-uplink-distribution.txt` + `ecmp-16flow-uplinktest.json` — cross-node ECMP split
  - `failover-test.txt` — real BGP-layer uplink-failover run (per-second + BGP state transitions)
  - `agg-bandwidth-test.txt` — 4-uplink aggregation curve (1→8 concurrent pod-pairs) + peak per-uplink split
  - `t3_t4_results.csv` — parsed summary table
