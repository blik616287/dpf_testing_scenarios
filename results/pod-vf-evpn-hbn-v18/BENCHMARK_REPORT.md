# Pod-VF EVPN Offload — Benchmark Report

**Cluster:** dpf-hbn-ovn-v18 (`6a5f0b8c78c728f7e209ed28`)
**Date:** 2026-07-21
**Configuration:** DPF v25.10.1 + DOCA HBN (EVPN L2VNI) on BlueField-3, pod-VF hardware offload, multiport eSwitch ECMP

---

## 1. Executive summary

Customer-realistic workload: a pod on a worker node keeps its normal `eth0` (OVN-Kubernetes)
and receives an SR-IOV **VF as `net1`**, whose dataplane is **hardware eSwitch-offloaded**
through DOCA HBN over an **EVPN/VXLAN L2VNI**, BGP/ECMP-routed across **two 40 GbE uplinks**
per DPU. The DPU Arm cores stay idle (data plane is offload-only).

| Headline metric | Result |
|-----------------|--------|
| Pod-to-pod TCP (single pair, 16 streams) | **32.1 Gbit/s** |
| Pod-to-pod TCP aggregate (4 pairs, both uplinks) | **64.1 Gbit/s** |
| Bidirectional (FN-origin / DAK-origin) | **63 / 65 Gbit/s** |
| Request/response latency (TCP_RR) | **60.6 µs** |
| Tail latency P99 / P99.9 (sockperf) | **45.4 / 68.2 µs** |
| DPU Arm CPU during throughput | **~92–93 % idle** (HW offload) |
| Small-packet forwarding (64 B UDP) | **≈380 k PPS** |

---

## 2. Test environment

**Hardware:** 2× bare-metal workers (gpu-sm01, gpu-sm02), each with a BlueField-3 DPU
(2× 40 GbE uplinks `p0`/`p1` to a Cisco Nexus leaf, AS65001, routed /31 eBGP). Control-plane
VM on a 3rd host.

**Fabric (all from the baked profile):**
- OVN-Kubernetes primary CNI (pod `eth0`); pod `net1` = SR-IOV VF (multus + sriov-dp, dynamic PF detection)
- Cluster-wide IPAM: **whereabouts**, flat tenant subnet `10.10.11.0/24`, `net1` MTU 8900
- DOCA HBN **EVPN**: VF representors → VLAN-11 access ports → **L2VNI 10010** (VXLAN), stretched across both DPUs via a direct DPU-to-DPU `l2vpn-evpn` session; anycast SVI `10.10.11.1`
- **Multiport eSwitch** (`esw_multiport`) enabled at boot on both DPUs → VXLAN ECMP-hashes across both p0/p1
- BGP: each DPU ↔ leaf, 2× routed /31 eBGP + ECMP; DPU-to-DPU EVPN Established

**Traffic model:** pod-to-pod, cross-node, cross-DPU, over the EVPN fabric. Client pods on
gpu-sm01, server pods on gpu-sm02; each pod-pair is L2-adjacent in the flat /24 via the L2VNI.

---

## 3. Methodology

Per `TEST_CASES.md`: iperf3 (throughput/PPS), netperf (latency/conn-rate), sockperf (tail
latency). **5 runs per benchmark**, reported as **mean ± population stdev** (min/max in the
JSON). Single-pair benchmarks: `agg-c1` (10.10.11.10) → `agg-s1` (10.10.11.11). Aggregation:
4 concurrent pod-pairs. Raw per-run values in `benchmark-suite.json`.

---

## 4. Results — standard benchmark matrix (single pod-pair)

| # | Benchmark | Tool | Result (mean ± stdev) |
|---|-----------|------|-----------------------|
| 1 | TCP throughput, 1 stream | iperf3 | **19.28 ± 0.81 Gbit/s** |
| 2 | TCP throughput, 8 streams | iperf3 | **31.42 ± 1.56 Gbit/s** |
| 3 | TCP throughput, 16 streams | iperf3 | **32.14 ± 0.92 Gbit/s** |
| 4 | UDP throughput, max (`-b 0`) | iperf3 | 14.54 ± 1.22 Gbit/s (50 % loss — single-flow, pod-CPU-bound) |
| 5 | UDP 64-byte (PPS) | iperf3 | **379,804 ± 2,804 PPS** (0.19 Gbit/s) |
| 6 | UDP 1400-byte | iperf3 | 3.96 ± 0.03 Gbit/s (32–41 % loss, single flow) |
| 7 | TCP request/response latency | netperf TCP_RR | **60.59 ± 1.25 µs** (16,512 tps) |
| 8 | UDP request/response latency | netperf UDP_RR | **59.16 ± 1.20 µs** |
| 9 | TCP streaming latency, 1-byte | netperf TCP_STREAM | 6.92 ± 0.13 Mbit/s |
| 10 | Tail latency (sockperf) | sockperf | **P50 28.11 / P99 45.37 / P99.9 68.23 µs** |
| 11 | Sustained connections/sec | netperf TCP_CRR | **3,080 ± 68 conn/s** |

Notes:
- Single-pair TCP tops ~32 Gbit/s: one VXLAN flow's entropy + a single pod's TCP stack. The
  **fabric** capacity is shown by the aggregation below, not one pair.
- UDP `-b 0` loss is expected — a single unpaced UDP flow overruns the receiver pod's CPU;
  it is a pod-stack limit, not a fabric limit (the TCP aggregate proves the fabric headroom).

---

## 5. Results — multiport ECMP / fabric aggregate (the EVPN offload story)

**4 concurrent pod-pairs (each a distinct VF, distinct whereabouts IP, one flat /24):**

| Pair | Throughput |
|------|-----------|
| 0 | 18.0 Gbit/s |
| 1 | 18.4 Gbit/s |
| 2 | 9.6 Gbit/s |
| 3 | 18.2 Gbit/s |
| **Aggregate** | **64.1 Gbit/s** |

**Per-uplink split (hardware PHY counters) — VXLAN ECMP across both 40G uplinks, both directions:**

| Direction | Originating DPU | p0 | p1 | Total |
|-----------|-----------------|----|----|-------|
| Forward (client→server) | FN (gpu-sm01) | 23.8 | 39.5 | **63 Gbit/s** |
| Reverse (server→client) | DAK (gpu-sm02) | 36.9 | 28.5 | **65 Gbit/s** |

Both DPUs spread their self-originated VXLAN across **both** uplinks (enabled by multiport
eSwitch). Without it, traffic pinned to a single uplink and the aggregate capped at ~39 Gbit/s;
with it, the aggregate reaches ~64 Gbit/s — using the full 2×40G fabric while retaining the
EVPN automation (flat /24, any vfID, one NAD). Pod-to-pod connectivity: **0 % loss**.

---

## 6. Offload verification

During sustained pod-to-pod throughput (single-stream ~20 Gbit/s and 8/16-stream ~32 Gbit/s),
the **DPU Arm cores measured ~92–93 % idle** (`mpstat`). The BlueField-3 eSwitch forwards the
VF dataplane in hardware — the pod stays on the worker, the DPU CPU is not in the packet path.
This is the defining property of the offload model ("data plane is offload only").

---

## 7. Key findings

1. **Pod-VF hardware offload works end-to-end** — annotation → auto-attached VF (multus/sriov)
   → distinct cluster-wide IP (whereabouts) → EVPN L2VNI VXLAN → BGP/ECMP → peer pod, fully
   automated, zero manual steps in steady state.
2. **Multiport eSwitch recovers the second uplink** — the fabric aggregate goes from ~39 to
   ~64 Gbit/s once VXLAN ECMP-hashes across both p0/p1. Must be set at boot (documented DOCA
   requirement); confirmed bidirectionally on both DPUs.
3. **Low, tight latency** — TCP_RR 60.6 µs, sockperf P50/P99 = 28/45 µs, with small stdev
   across 5 runs — the hardware pipeline gives consistent latency.
4. **DPU offload confirmed** — Arm cores ~92 % idle at 32 Gbit/s.
5. **Single-flow ceilings are pod-side**, not fabric — the 4-pair aggregate (64 Gbit/s) and the
   two-uplink split prove the fabric has headroom well beyond any one pod/flow.

---

## 8. Artifacts

- `benchmark-suite.json` — all 11 benchmarks, 5 runs each, mean/stdev/min/max + raw values
- `mpesw-agg-pair0..3.json`, `e2e-fwd-*.json` — aggregation / bidirectional iperf3 output
- `tcp-1stream.json`, `tcp-4stream.json`, `tcp-8stream.json` — earlier single-pair captures
- `README.md` — fabric design, the multiport root-cause + fix, recovery notes
