# Full Benchmark Suite + HBN Failover — Clean Deploy (v30, corrected profile)

**Cluster:** dpf-hbn-ovn-v30 (`6a62b35290e42331c67488d8`), deployed hands-off from
infra v14 (`6a615582`) + **HBN v30** (`6a62c4a290e424a8b5c22124`) — the corrected profile
(VF self-heal create-only fix + dynamic multiport).
**Date:** 2026-07-24

Ran on the clean, hands-off deploy (VFs 4/4 on both workers with no intervention). Includes the
throughput suite **and HBN uplink-failover tests** (the resilience of the 2×40 GbE ECMP fabric).

## 1. Single-pair (5 runs, mean ± σ) — parity with v28/v29

| Benchmark | v30 |
|-----------|-----|
| TCP 1 / 8 / 16 streams | 21.12 / 31.96 / 32.01 Gbit/s |
| UDP 64-byte PPS | 377,931 |
| TCP_RR / UDP_RR latency | 61.17 / 59.99 µs |
| TCP_CRR | 3,276 conn/s |
| sockperf P50 / P99 / P99.9 | 30.36 / 48.97 / 77.01 µs |

## 2. Bandwidth aggregation

- **Balanced 4-pair aggregate: 74.70 Gbit/s** (~93% of 2×40 GbE), retx ~0, symmetric (35.6 / 39.1).
- **Multiport ECMP: perfect 50/50 uplink split** — single-DPU egress p0 39.23 GB / p1 39.26 GB, ~45 Gbit/s
  (dynamic-PCI multiport from the profile, no hardcoded PCI).
- **DPU Arm 90.1% idle** during throughput (hardware offload).
- **Fix stress-test:** all **8 aggregate pods held `net1`@9000 throughout** — the exact scenario
  that the previous (broken) self-heal destroyed. The create-only fix holds under full VF load.

## 3. HBN uplink failover

HBN routes each DPU's two 40 GbE uplinks as routed `/31` eBGP with ECMP, and the mlx5 multiport
eSwitch load-balances VXLAN across both in hardware. Failover was induced by administratively
downing one uplink interface (`p0_if`) inside the DOCA HBN pod on the FN DPU, mid-flow, then
restoring it. **Verified the failure was real** via the DPU PHY counters: during `p0_if` down,
p0 tx froze (0 GB) and p1 carried 100% of the traffic.

*(An earlier attempt to fail the uplink via the host `p0` netdev did NOT work — the eSwitch kept
forwarding on p0, shown by throughput staying > 40 Gbit/s during the "failover". The valid method
is downing the HBN-side `p0_if`.)*

### 3.1 Single-pair (load < one uplink)

Continuous 16-stream flow, `p0` failed at t=12 s, restored at t=25 s:

| Phase | Throughput | Outage |
|-------|-----------|--------|
| Dual uplink | 32.5 Gbit/s | — |
| **Single uplink (failover)** | **31.8 Gbit/s (98%)** | **none** |
| Recovered | 32.3 Gbit/s | — |

A single pair (~32 Gbit/s) fits within one 40 GbE uplink, so losing an uplink had **no throughput
impact** — one brief ~1 s dip, no zero-throughput second. Seamless.

### 3.2 Aggregate (load > one uplink) — graceful degradation

Two-pair unidirectional FN egress (~50 Gbit/s, exceeds one uplink), `p0_if` down at t=15 s,
restored at t=28 s, with a concurrent 10 Hz ping:

| Phase | Throughput | Packet loss |
|-------|-----------|-------------|
| Dual uplink (pre) | 49.9 Gbit/s | — |
| **Single uplink (failover)** | **38.5 Gbit/s (77%, capped at ~40 G)** | **0% (0 / 400 pings, 0 missing)** |
| Recovered (post) | 50.3 Gbit/s (in ~2–3 s) | 0% |

**Zero packet loss across BOTH the failure and the recovery** (400/400 ICMP, sub-100 ms
convergence at 10 Hz). When the load exceeds one uplink, the fabric **degrades gracefully to the
surviving uplink's capacity** (~40 G) rather than dropping traffic, and **restores full aggregation
within ~2–3 s** of the uplink returning. BGP re-established both leaf sessions (129 prefixes each).

### 3.3 Resilience summary

- **No traffic loss on uplink failure or recovery** — the multiport eSwitch + ECMP reconverge
  sub-100 ms, in hardware.
- **Below one-uplink load:** full throughput continuity on failover.
- **Above one-uplink load:** graceful degradation to surviving-uplink capacity, full recovery on restore.
- **Control plane:** BGP/EVPN reconverge cleanly; both leaf uplink sessions return to 129 prefixes.

## 4. Deploy durability

Hands-off from the corrected profile: both DPUs joined, VFs **4/4 on both workers with no manual
re-materialize** (the self-heal now correctly gates on `sriov_numvfs != target`, so it never
destroys a VF handed to a pod), dynamic multiport active, fabric up. See the 0-touch verification
and the v30 fix note.

## Artifacts
- `single-pair-raw/` + `single-pair-stats.json` — 10 benchmarks × 5 runs
- `p0..p3.json` — balanced aggregate (74.70 Gbit/s)
- `failover/` — single-pair-failover.json, aggregate p0/p1.json (per-second), ping.txt
