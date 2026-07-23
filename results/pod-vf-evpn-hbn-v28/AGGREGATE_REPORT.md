# Pod-VF EVPN Offload — Fabric Saturation & Multiport Aggregate (v28)

**Cluster:** dpf-hbn-ovn-v28 (`6a61750690e4083e3960c8d4`)
**Date:** 2026-07-22
**Profiles:** infra v14 (`6a615582`) + HBN v28 (`6a616821`) — the standalone, hands-off deploy set
**Config:** DPF v25.10.1 + DOCA HBN (EVPN L2VNI) on BlueField-3, pod-VF hardware offload

This report answers two questions the single-pair suite could not:
1. **Are we saturating the fabric?** (single pair tops ~32 G — a per-flow ceiling, not the fabric)
2. **Is uplink aggregation (multiport ECMP) actually working**, and did it come up from the profile?

---

## 1. Headline

| Metric | Result |
|--------|--------|
| **Balanced 4-pair aggregate** (bidirectional, both DPUs egress) | **77.72 Gbit/s** |
| Retransmits at saturation | **~0** (5–9 total per pair) |
| Direction symmetry | sm01→sm02 **39.63** / sm02→sm01 **38.08** Gbit/s |
| **Multiport ECMP split** (single-DPU egress, HW PHY counters) | **p0 47% / p1 53%** (35.11 / 39.79 GB) |
| Single-DPU egress rate (both uplinks) | **~50 Gbit/s** (> 40 G single-uplink cap → both in use) |
| `net1` MTU (all 8 pods, from profile) | **9000 (jumbo)**, zero manual steps |

77.72 Gbit/s ≈ **97% of the 2×40 G fabric** available to a DPU pair. The remaining gap is
host-side (iperf3 CPU + per-host TX/RX contention), not fabric.

---

## 2. Why single-pair ≠ fabric saturation (the topology fix)

A single pod-VF TCP flow tops ~32 Gbit/s: one VXLAN flow's entropy lands on one uplink and
one pod's TCP stack is the limit. To load the fabric you need **multiple flows across
multiple hosts**.

The first aggregate attempt put **all 4 clients on one node** (gpu-sm01) and all servers on
the other. That drives the whole load through **one host's egress path and one DPU**, leaving
the second worker's entire uplink capacity idle as pure RX. Result: 58–62 Gbit/s **with
80,000–136,000 retransmits per pair** — classic one-sided incast drops.

**Fix — balance across both workers.** 2 clients + 2 servers per node, cross-paired, so both
DPUs egress on both uplinks simultaneously:

| Pair | Client | Server | Direction |
|------|--------|--------|-----------|
| p0 | bc0 @ gpu-sm01 | bs0 @ gpu-sm02 | sm01→sm02 |
| p1 | bc1 @ gpu-sm01 | bs1 @ gpu-sm02 | sm01→sm02 |
| p2 | bc2 @ gpu-sm02 | bs2 @ gpu-sm01 | sm02→sm01 |
| p3 | bc3 @ gpu-sm02 | bs3 @ gpu-sm01 | sm02→sm01 |

| Topology | Aggregate | Retx |
|----------|-----------|------|
| All-clients-on-one-node (16 streams) | 58.83 | ~400 k total |
| All-clients-on-one-node (zerocopy) | 62.33 | ~400 k total |
| **Balanced both-nodes (16 streams)** | **77.72** | **~28 total** |

Balancing the load lifted throughput **+25%** and eliminated the drops.

---

## 3. Multiport ECMP — direct hardware proof

Multiport eSwitch (mlx5 `esw_multiport`) makes a DPU's single VTEP hash its self-originated
VXLAN across **both** 40 G uplinks. Without it, one uplink carries everything (~39 G ceiling).

**Measurement:** during a single-DPU (FN) egress-only burst, read the **hardware PHY tx
counters** of the two physical uplink ports p0/p1 (`/sys/class/net/pN/statistics/tx_bytes` on
the DPU host — these count HW-offloaded traffic; the software netdev/ethtool counters do not,
which is itself the offload signature).

```
p0 (0000:03:00.0)  PHY-TX delta:  35.11 GB   (47%)
p1 (0000:03:00.1)  PHY-TX delta:  39.79 GB   (53%)
total 74.9 GB in 12 s = ~49.9 Gbit/s from ONE DPU
```

~50 Gbit/s out of a single DPU is **physically impossible on one 40 G uplink** — and the split
is a near-even 47/53. **Multiport ECMP is active.**

**It came up from the profile.** On this fresh, hands-off v28 deploy the baked
`dpf-esw-multiport` boot service enabled `esw_multiport` before the HBN dataplane started —
no live patching. The DPU's p0/p1 PCIs are `0000:03:00.0` / `0000:03:00.1`, matching the
service. (The service has since been made **PCI-dynamic** — it now detects the uplink PFs by
`phys_port_name` p0/p1 with the known PCIs only as a fallback — so it is portable, not tied to
this slot.)

---

## 4. net1 jumbo — standalone

All 8 pods came up with `net1` at **MTU 9000** with no manual step. The fabric MTU has headroom
for VXLAN: `vlan11`/`vxlan48` are **9216**, so inner 9000 + 50 B VXLAN = 9050 fits with no
fragmentation. This is the `host-bf3-sriov-vfs` fix (raises PF0 + VFs to 9000 every loop) doing
its job from the profile.

---

## 5. Fabric ceiling analysis

- Each DPU: 2×40 G = 80 G to the leaf (full duplex).
- Balanced aggregate 77.72 G ≈ 97% of the 80 G a DPU pair can move one-way-equivalent.
- Per-host at saturation: ~40 G TX + ~38 G RX. The limit is now **host-side** (iperf3 CPU and
  each worker's PF0 sharing TX+RX), **not the HBN fabric** — the uplinks demonstrably have the
  headroom (multiport splits ~50 G from one DPU across both).

To push past 78 G you'd add workers/hosts or faster host PFs; the DPU fabric is not the bottleneck.

---

## 6. What this proves about the profile

Everything here ran on the **standalone v28 deploy** (infra v14 + HBN v28), brought up hands-off:
both DPUs joined, BGP + DPU-to-DPU EVPN Established, VFs allocatable, `net1` jumbo, **and
multiport ECMP active** — all from baked profile content, zero live patching. The only profile
change made as a result of this run is hardening the multiport service to detect PCI dynamically.

## 7. Artifacts

- `p0.json`–`p3.json` — the balanced 4-pair aggregate iperf3 JSON (16 streams, 15 s each)
