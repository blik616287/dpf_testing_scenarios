# Pod-VF EVPN HBN Benchmark — v18 (NVIDIA-reference, baked profile)

**Date:** 2026-07-21
**Cluster:** dpf-hbn-ovn-v18 (`6a5f0b8c78c728f7e209ed28`), tenant `dpu-cplane-tenant1`
**Profile:** DPF ZT HBN v18 EVPN (`6a5f045378c7285c6704e57c`) — a fresh redeploy from the
fully-baked profile (not runtime `nv` surgery).

## Design (NVIDIA reference, adapted to this fabric)
The customer pod-VF offload done the NVIDIA way — **EVPN L2VNI** instead of per-VF `/29`s:
- Each host SR-IOV VF → representor `pf0vfN` → HBN swp `pf0vfN_if`, wired as a **VLAN-11
  bridge access port** (ServiceChain).
- VLAN 11 → **L2VNI 10010** (VXLAN), **stretched across both DPUs** so all pods share ONE
  flat `10.10.11.0/24` regardless of vfID or which DPU/host they land on.
- **Anycast SVI** `10.10.11.1/24` (same IP on both DPUs) = pod gateway.
- **DPU-to-DPU EVPN** (multihop `l2vpn-evpn`, loopback-to-loopback `11.0.0.1`↔`11.0.0.2`) —
  because this fabric's **leaf does not speak EVPN** (`l2vpn-evpn` = `NoNeg`); the leaf just
  IP-forwards the VXLAN. Underlay stays numbered `/31` eBGP to the leaf.

Everything above **rendered automatically from the profile** — no manual `nv` config. The
only manual steps in the redeploy were the standard infra gates (OVN-K zone-label + MTU,
DPU oob-up + join via console, hugepages/OVS/sfc restart).

## Results (iperf3, MTU 8900 for VXLAN overhead)
| Test | Throughput |
|------|-----------|
| TCP single-stream | 17.0 – 20.6 Gbit/s |
| TCP 4-stream | 31.1 Gbit/s |
| TCP 8-stream | 30.3 Gbit/s |

~30 Gbit/s aggregate = **hardware VXLAN offload** on the BF3 eSwitch (software VXLAN would be
single-digit). Traffic path: pod net1 (VF) → representor → VLAN-11 → VXLAN L2VNI (encap,
VTEP `11.0.0.1`) → p0/p1 uplinks → leaf (plain IP) → peer DPU VTEP → decap → VLAN-11 →
representor → peer pod net1. The two pods are on different hosts/DPUs in the same flat `/24`,
reachable only via the VXLAN tunnel, so it genuinely traverses EVPN.

vfID-independence proven: pods get an arbitrary VF (any of vf0–3, all VLAN-11 access ports)
and still land in the one flat subnet — the exact case the per-`/29` design couldn't automate.

## Fabric state (from the baked profile)
- Both HBN pods 2/2 Running; DPUDeployment + DPUServiceChain = Success.
- Underlay BGP → leaf Established (126 prefixes); DPU-to-DPU EVPN session Established.
- L2VNI 10010 / vxlan48 up, 1 remote VTEP; vlan11 anycast SVI up; 4 VF swps VLAN-11 access.
- Host: `bf3_p0_vfs`=4/worker; multus+sriov auto-attach (baked) gives pods net1 automatically.

## Profile bugs found during the fresh redeploy (fix for next time)
1. **OVN-K MTU** — my `mtu:1400` fix was in the *infra* profile, but the redeploy reused the
   old infra UID (`6a5ab330`, still `PodMTU=8940`); runtime-patched `ovn-config`. Rebuild+push
   the infra profile.
2. **Zone-label** — CP + both workers still needed `k8s.ovn.org/zone-name` applied by hand;
   the postKubeadm/addon labeler didn't beat ovnkube-node.
3. **DPU oob-fixup** — `dpf-oob-fixup.service` present but didn't bring oob up at boot; still
   needed manual console oob-up + `kubeadm-join.service` start. (Root cause: boot join/SF/
   hugepage/OVS services are gated on `network-online.target`, which never fires with oob down.)
4. **PF name** — `host-bf3-sriov-vfs` DS + sriov-dp selector hardcode `eth0`, but the PF is
   `enp14s0f0np0` → 0 VFs advertised. Make the PF detection dynamic (phys_port_name `p0`).
5. **NAD IPAM collision** — `host-local` on the flat `/24` allocates per-node with no shared
   state → both pods got `10.10.11.10`. Switch to **whereabouts** (cluster-wide IPAM) so pods
   get distinct IPs automatically. (Manually assigned distinct IPs for this benchmark.)

## Aggregation — 4 pod-pairs concurrent (2026-07-21)
4 client pods (gpu-sm01) + 4 server pods (gpu-sm02), each auto-attached a VF (dynamic-PF
detection) with a distinct whereabouts IP in the flat 10.10.11.0/24, all running iperf3
concurrently (2 streams each, 12 s):

| Pair | Client→Server | Throughput |
|------|---------------|-----------|
| 0 | .10 → .11 | 11.4 Gbit/s |
| 1 | .12 → .14 |  5.6 Gbit/s |
| 2 | .13 → .17 | 11.1 Gbit/s |
| 3 | .15 → .16 | 11.1 Gbit/s |
| **Aggregate** | | **39.2 Gbit/s** |

This validates the fully-automated path at scale: 8 pods, each got a VF (any vfID) + a
**distinct** cluster-wide IP, all L2-adjacent in one flat /24 over the EVPN L2VNI.

### Initial EVPN result pinned to ONE uplink (~39 Gbit/s) — root-caused + FIXED
The first EVPN aggregation only hit ~39 Gbit/s. Root cause (measured via per-uplink PHY
counters): the originating VTEP sent **100% of its VXLAN out a single 40G uplink** (p0=34,
p1=0). The entropy was fine (the leaf spread the same packets 2:1 to the peer) — the problem
was the **mlx5 multipath LAG was disabled** on the originating DPU, so it bound its
self-originated VXLAN to one PCI function instead of hashing across the ECMP group.

**FIX (per DOCA docs): enable `esw_multiport` (multiport eSwitch) BEFORE HBN starts, then
power-cycle.** Requirements: `LAG_RESOURCE_ALLOCATION=1` in fw (already set), switchdev on
both PFs, `devlink dev param set pci/03:00.{0,1} name esw_multiport value true` applied at
BOOT (a systemd oneshot ordered before kubelet — NOT toggled live, which breaks BGP), then a
power-cycle so the eswitch inits in multiport mode. After the power-cycle the LAG comes up
`state=active type=multiport_eswitch port_sel_mode=mpesw`, BGP + EVPN establish normally, and
VXLAN ECMP-hashes across both uplinks.

### EVPN result WITH multiport eSwitch — both uplinks used
Per-uplink PHY counters during 4 concurrent pairs: **p0 = 36.9, p1 = 28.9 Gbit/s (≈65.7 total)**.

| Pair | Throughput |
|------|-----------|
| 0 | 18.0 Gbit/s |
| 1 | 18.4 Gbit/s |
| 2 |  9.6 Gbit/s |
| 3 | 18.2 Gbit/s |
| **Aggregate** | **64.1 Gbit/s** |

So EVPN pod-VF now hits **~64 Gbit/s** (up from ~39), matching the per-/29 L3 design — **both
40G uplinks fully used** — while keeping the EVPN automation (flat /24, any vfID, one NAD).
The earlier "EVPN inherently costs half the fabric" conclusion was WRONG; it was a missing
`esw_multiport` config, exactly as the docs specify.

Gotcha hit during recovery: repeated HBN pod restarts left **orphaned SFs** in br-hbn from
dead pods (identified by their OVS `external_ids` dpf-id referencing an old pod name); the
`ovs-watcher` sidecar crashes on any br-hbn SF lacking a matching `p<sf>brhbn` patch. Fix:
`ovs-vsctl del-port br-hbn <stale-sf>` for ports whose dpf-id isn't the current pod. Also, a
DPU power-cycle resets the host-facing PF, so host VFs + pod net1 must be recreated after.

## JSON artifacts
- `tcp-1stream.json`, `tcp-4stream.json`, `tcp-8stream.json` — single-pair.
- `agg-pair0..3.json` — 4-pair concurrent aggregation.
