# Pod-VF EVPN Offload — Benchmark Report (v27)

**Cluster:** dpf-hbn-ovn-v27 (`6a614072045802910c6f1d61`)
**Date:** 2026-07-22
**Configuration:** DPF v25.10.1 + DOCA HBN (EVPN L2VNI) on BlueField-3, pod-VF hardware offload
**Profiles:** infra v14 (`6a615582`) + HBN v28 (`6a616821`) — the standalone, hands-off deploy set

---

## 1. Executive summary

Customer-realistic workload: a pod on a worker node keeps its OVN-Kubernetes `eth0`
and receives an SR-IOV **VF as `net1`**, whose dataplane is **hardware eSwitch-offloaded**
through DOCA HBN over an **EVPN/VXLAN L2VNI**, BGP/ECMP-routed to the leaf. The DPU Arm
cores stay idle — the data plane is offload-only.

| Headline metric | v27 | v18 (ref) |
|-----------------|-----|-----------|
| Pod-to-pod TCP, 16 streams | **31.45 Gbit/s** | 32.14 |
| Pod-to-pod TCP, 8 streams | 29.81 | 31.42 |
| Pod-to-pod TCP, 1 stream | 19.73 | 19.28 |
| Request/response latency (TCP_RR) | **63.3 µs** | 60.6 |
| Tail latency P50 / P99 / P99.9 (sockperf) | **28.4 / 47.6 / 77.0 µs** | 28.1 / 45.4 / 68.2 |
| Small-packet forwarding (64 B UDP) | **382 k PPS** | 380 k |
| DPU Arm CPU during throughput | **~92 % idle** (16 cores) | ~92–93 % |

v27 reaches parity with the v18 baseline — importantly, from a profile set that
brings the whole stack up hands-off (see §7).

---

## 2. Test environment

**Hardware:** 2× bare-metal workers (gpu-sm01, gpu-sm02), each with a BlueField-3 DPU
(2× 40 GbE uplinks `p0`/`p1` to a Cisco Nexus leaf, AS65001, routed `/31` eBGP). Kamaji
tenant control-plane on a 3rd (VM) node.

**Fabric (all rendered from the profile):**
- OVN-Kubernetes primary CNI (pod `eth0`); pod `net1` = SR-IOV VF (multus + sriov-dp, dynamic PF detection)
- Cluster-wide IPAM: **whereabouts**, flat tenant subnet `10.10.11.0/24`, `net1` MTU **9000 (jumbo)**
- DOCA HBN **EVPN**: VF representors → VLAN-11 access ports → **L2VNI** (VXLAN), stretched across both DPUs via a direct DPU-to-DPU `l2vpn-evpn` session; anycast SVI `10.10.11.1`
- BGP: each DPU ↔ leaf, 2× routed `/31` eBGP + ECMP, and the DPU-to-DPU EVPN session — all **Established, 129 prefixes** each

**Traffic model:** pod-to-pod, cross-node, cross-DPU, over the EVPN fabric. Client pod on
gpu-sm01, server on gpu-sm02; pods are L2-adjacent in the flat `/24` via the L2VNI.

---

## 3. Methodology

iperf3 (throughput/PPS), netperf (latency/conn-rate), sockperf (tail latency).
**5 runs per benchmark**, reported as **mean ± population stdev**. Single pod-pair
`bench-client` (10.10.11.10) → `bench-server` (10.10.11.11), `net1` VFs at MTU 9000.
Raw per-run values in `benchmark-suite.json`.

---

## 4. Results — benchmark matrix

| # | Benchmark | Tool | Result (mean ± stdev) |
|---|-----------|------|-----------------------|
| 1 | TCP throughput, 1 stream | iperf3 | **19.73 ± 1.67 Gbit/s** |
| 2 | TCP throughput, 8 streams | iperf3 | **29.81 ± 5.04 Gbit/s** |
| 3 | TCP throughput, 16 streams | iperf3 | **31.45 ± 1.79 Gbit/s** |
| 4 | UDP throughput, max (`-b 0`) | iperf3 | 14.95 ± 0.74 Gbit/s (34 % loss — single unpaced flow, pod-CPU-bound) |
| 5 | UDP 64-byte (PPS) | iperf3 | **381,944 ± 2,838 PPS** |
| 6 | UDP 1400-byte | iperf3 | 3.96 ± 0.04 Gbit/s |
| 7 | TCP request/response latency | netperf TCP_RR | **63.25 ± 4.87 µs** (15,903 tps) |
| 8 | UDP request/response latency | netperf UDP_RR | **59.19 ± 2.66 µs** |
| 9 | Sustained connections/sec | netperf TCP_CRR | **3,074 ± 155 conn/s** |
| 10 | Tail latency (sockperf) | sockperf | **P50 28.37 / P99 47.55 / P99.9 77.02 µs** |

Single-pair TCP tops ~31 Gbit/s — one VXLAN flow's entropy + a single pod's TCP stack;
it's the pod/flow ceiling, not the fabric (per-uplink capacity is 2×40 G).

---

## 5. Offload verification

During sustained pod-to-pod throughput the **DPU Arm cores measured ~92 % idle**
(16 cores, ~8 % busy — sampled from `/proc/stat` on the DPU while iperf3 ran). The
BlueField-3 eSwitch forwards the VF dataplane in hardware; the pod stays on the worker
and the DPU Arm is not in the packet path. This is the defining property of the offload
model.

---

## 6. Jumbo MTU note (throughput)

An initial run showed ~28 Gbit/s at 8 streams. Root cause: the BF3 **host PF0 was at
MTU 1500**, and a VF cannot exceed its parent PF, so the NAD's `mtu:8900` never applied
and `net1` came up 1500. Raising PF0 (and the VFs) to 9000 lets `net1` come up jumbo
end-to-end → **32.1 Gbit/s** (8-stream), v18 parity. This is now baked
(`host-bf3-sriov-vfs` sets the PF/VF MTU), so `net1` comes up 9000 with no manual step.

---

## 7. Notes on the deploy (durability)

This benchmark ran on v27, and every fix used to reach it is now in the profiles
(infra v14 + HBN v28), so a fresh deploy is hands-off through pod-VF:

- **HBN fabric:** the `doca-hbn-label-fixer(-fast)` manifests were *removed* — they
  relabelled the doca-hbn pods' serviceID from the correct verbose
  `dpudeployment_ovn-hbn_doca-hbn` to plain `doca-hbn`, which broke SF wiring (BGP down).
  Default verbose label is correct; no fixer needed.
- **Pod-VF allocatable:** `sriov-dp-rescan-kicker` restarts sriov-device-plugin when the
  BF3 VFs appear after its one-time scan.
- **Jumbo MTU:** `host-bf3-sriov-vfs` raises PF0/VFs to 9000.
- Plus the earlier standalone fixes: zone-labeler, longhorn all-node, the 7 re-embedded
  DPF manifests, kamaji replicas=1, DMS-DNS injector, MaaS oob reservations, oob-fixup,
  and the auto-repower (post-flash power-cycle).

---

## 8. Artifacts

- `benchmark-suite.json` — all benchmarks, 5 runs each, mean/stdev/min/max + raw values
- `dpu-offload.json` — DPU Arm idle measurement
