# Pod-VF EVPN Offload — Single-Pair Benchmark Report (v28)

**Cluster:** dpf-hbn-ovn-v28 (`6a61750690e4083e3960c8d4`)
**Date:** 2026-07-22
**Configuration:** DPF v25.10.1 + DOCA HBN (EVPN L2VNI) on BlueField-3, pod-VF hardware offload
**Profiles:** infra v14 (`6a615582`) + HBN v28 (`6a616821`) — the standalone, hands-off deploy set

This is the single-pair suite (matches the v27 methodology) run on the **standalone v28
deploy**. For the multi-pair fabric-saturation + multiport-ECMP numbers, see the companion
`AGGREGATE_REPORT.md` in this directory.

---

## 1. Executive summary

Customer-realistic workload: a pod on a worker node keeps its OVN-Kubernetes `eth0` and
receives an SR-IOV **VF as `net1`**, whose dataplane is **hardware eSwitch-offloaded** through
DOCA HBN over an **EVPN/VXLAN L2VNI**, BGP/ECMP-routed to the leaf. The DPU Arm cores stay
idle — the data plane is offload-only.

| Headline metric | v28 | v27 | v18 (ref) |
|-----------------|-----|-----|-----------|
| Pod-to-pod TCP, 8 streams | **34.91 Gbit/s** | 29.81 | 31.42 |
| Pod-to-pod TCP, 16 streams | **32.53** | 31.45 | 32.14 |
| Pod-to-pod TCP, 1 stream | 19.22 | 19.73 | 19.28 |
| Request/response latency (TCP_RR) | **62.19 µs** | 63.25 | 60.6 |
| Tail latency P50 / P99 / P99.9 (sockperf) | **30.1 / 49.3 / 73.8 µs** | 28.4 / 47.6 / 77.0 | 28.1 / 45.4 / 68.2 |
| Small-packet forwarding (64 B UDP) | **383.6 k PPS** | 382 k | 380 k |
| DPU Arm CPU during throughput | **92.6 % idle** (16 cores) | ~92 % | ~92–93 % |

v28 reaches — and on the jumbo 8-stream case **exceeds** — the v18/v27 baselines, from a profile
set that brings the whole stack up hands-off. The 8-stream **34.9 Gbit/s** is the best jumbo
single-pair result recorded, reflecting the `net1` MTU-9000 fix rendering correctly from the
profile (§6).

---

## 2. Test environment

**Hardware:** 2× bare-metal workers (gpu-sm01, gpu-sm02), each with a BlueField-3 DPU
(2× 40 GbE uplinks `p0`/`p1` to a Cisco Nexus leaf, AS65001, routed `/31` eBGP). Kamaji tenant
control-plane on a 3rd (VM) node.

**Fabric (all rendered from the profile, no live patching):**
- OVN-Kubernetes primary CNI (pod `eth0`); pod `net1` = SR-IOV VF (multus + sriov-dp, dynamic PF detection)
- Cluster-wide IPAM: **whereabouts**, flat tenant subnet `10.10.11.0/24`, `net1` MTU **9000 (jumbo)**
- DOCA HBN **EVPN**: VF representors → VLAN-11 access ports → **L2VNI** (VXLAN), stretched across both DPUs via a direct DPU-to-DPU `l2vpn-evpn` session; anycast SVI `10.10.11.1`
- BGP: each DPU ↔ leaf (2× routed `/31` eBGP + ECMP) and the DPU-to-DPU EVPN session — all Established, 128–129 prefixes each
- **Multiport eSwitch** enabled at boot → VXLAN ECMP across both 40 G uplinks (proven in `AGGREGATE_REPORT.md`)

**Traffic model:** pod-to-pod, cross-node, cross-DPU. Client pod `bc0` on gpu-sm01
(10.10.11.10) → server `bs0` on gpu-sm02 (10.10.11.15); pods L2-adjacent in the flat `/24`
via the L2VNI, `net1` VFs at MTU 9000.

---

## 3. Methodology

iperf3 (throughput/PPS), netperf (latency/conn-rate), sockperf (tail latency).
**5 runs per benchmark**, reported as **mean ± population stdev**. Raw per-run output in
`single-pair-raw/`; parsed stats in `benchmark-suite-stats.json`.

---

## 4. Results — benchmark matrix

| # | Benchmark | Tool | Result (mean ± stdev) |
|---|-----------|------|-----------------------|
| 1 | TCP throughput, 1 stream | iperf3 | **19.22 ± 1.24 Gbit/s** |
| 2 | TCP throughput, 8 streams | iperf3 | **34.91 ± 1.05 Gbit/s** |
| 3 | TCP throughput, 16 streams | iperf3 | **32.53 ± 1.38 Gbit/s** |
| 4 | UDP throughput, max (`-b 0`) | iperf3 | 12.60 ± 1.39 Gbit/s (54 % loss — single unpaced flow, pod-CPU-bound) |
| 5 | UDP 64-byte (PPS) | iperf3 | **383,557 ± 5,659 PPS** |
| 6 | UDP 1400-byte | iperf3 | 2.72 ± 0.06 Gbit/s |
| 7 | TCP request/response latency | netperf TCP_RR | **62.19 ± 2.92 µs** (16,075 tps) |
| 8 | UDP request/response latency | netperf UDP_RR | **57.98 ± 1.44 µs** |
| 9 | Sustained connections/sec | netperf TCP_CRR | **3,145 ± 179 conn/s** |
| 10 | Tail latency (sockperf) | sockperf | **P50 30.11 / P99 49.33 / P99.9 73.78 µs** |

Single-pair TCP tops ~33–35 Gbit/s — one VXLAN flow's entropy plus a single pod's TCP stack;
it's the pod/flow ceiling, not the fabric. The fabric itself sustains **77.7 Gbit/s** across
four balanced pairs (`AGGREGATE_REPORT.md`). The UDP throughput rows (max, 1400 B) are single
unpaced flows and are pod-CPU-bound; they are inherently noisy and not a fabric measure.

---

## 5. Offload verification

During sustained 16-stream pod-to-pod throughput the **DPU Arm cores measured 92.6 % idle**
(16 cores, ~7.4 % busy — `/proc/stat` delta on the DPU while iperf3 ran). Independently, the
uplink **software** byte counters stay near-zero while the **hardware** PHY counters carry the
full ~50 Gbit/s (`AGGREGATE_REPORT.md` §3) — the BlueField-3 eSwitch forwards the VF dataplane
in hardware; the pod stays on the worker and the DPU Arm is not in the packet path. This is the
defining property of the offload model.

---

## 6. Jumbo MTU (throughput)

`net1` came up **MTU 9000 on the pod with no manual step** — the `host-bf3-sriov-vfs` DaemonSet
raises PF0 and every VF to 9000 each loop (a VF cannot exceed its parent PF, so PF0 must be 9000
first). Fabric MTU has VXLAN headroom (`vlan11`/`vxlan48` = 9216, so inner 9000 + 50 B = 9050
fits with no fragmentation). This is what lifts the 8-stream case to 34.9 Gbit/s.

---

## 7. Durability

Every fix used to reach these numbers is in the profiles (infra v14 + HBN v28), so a fresh
deploy is hands-off through pod-VF — verified on this v28 cluster (both DPUs joined, BGP + EVPN
Established, VFs allocatable, `net1` jumbo, multiport active — all with zero live patching).
See `AGGREGATE_REPORT.md` §6 and the v27 report §7 for the full list of baked fixes; the only
profile change from this run was making the multiport-eSwitch service detect the uplink PCIs
dynamically.

---

## 8. Artifacts

- `benchmark-suite-stats.json` — all 10 benchmarks, mean/stdev/min/max
- `single-pair-raw/` — raw per-run iperf3 JSON + netperf/sockperf output (5 runs each)
- `AGGREGATE_REPORT.md` + `p0..p3.json` — 4-pair fabric saturation & multiport ECMP proof
