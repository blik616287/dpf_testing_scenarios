# Fabric request (follow-up): second BGP peering per DPU for ECMP

**Status of prior ask:** [`FABRIC_HBN_ECMP_REQUEST.md`](FABRIC_HBN_ECMP_REQUEST.md) is **complete** on your side and verified from ours:

- `Eth1/24` ↔ `172.16.97.248/31` ↔ gpu1.p1 (AS 65010) — BGP **Established**, 123 prefixes received
- `Eth1/26` ↔ `172.16.97.250/31` ↔ gpu2.p1 (AS 65020) — BGP **Established**, 123 prefixes received
- Leaf loopback `11.0.0.111/32` is reachable from each DPU over the new path (~0.5 ms RTT)

That gave each DPU **one** BGP path to the leaf, which is enough to prove the underlay works. To run TC4's ECMP scaling benchmark we need each DPU to install **two equal-cost paths** in its routing table — otherwise BGP picks one and ECMP doesn't split flows.

This follow-up asks for the second path per DPU **without disturbing anything you already configured**.

---

## TL;DR

Add a second BGP neighbor entry on the leaf for each DPU, pointing at the DPU's existing `ovnvtep` IP on VLAN 497. The transport for this second peering rides the **existing** VLAN 497 SVI on the leaf — same VLAN, same L2 path that today carries our VPC-OVN traffic between `Eth1/23` ↔ `Eth1/25`. No new physical paths, no port reconfiguration, no change to the `/31` peerings from the prior ask.

**Concrete asks:**

0. Confirm the leaf SVI IP currently configured on VLAN 497. If it isn't already an IP in `172.16.97.96/27`, add a secondary IP in that range (suggestion: `172.16.97.125/27`).
1. Add two BGP neighbors on the leaf, both reaching us via the VLAN 497 SVI:
   - `172.16.97.98` (gpu1 DPU `ovnvtep`) — remote-as **65010** (same ASN as gpu1's existing /31 peering)
   - `172.16.97.102` (gpu2 DPU `ovnvtep`) — remote-as **65020**
2. Advertise the **same** loopback (`11.0.0.111/32`) over these new sessions, so each DPU sees two equal-cost next-hops to it.
3. Reply with the SVI IP we should peer to from the DPU side.

Estimated change: ~10 lines of NX-OS. No interface reconfiguration; only BGP neighbor stanzas.

---

## 1. Why a second path is needed

> **Cite:** [DOCA HBN Service Guide 2.6.0](https://docs.nvidia.com/doca/archive/2-6-0/nvidia+doca+hbn+service+guide/index.html), § *ECMP Example* — *"HBN supports up to 16 paths for ECMP."*

ECMP is "two or more equal-cost paths to the same destination." With a single BGP peering per DPU, BGP installs **one** best path. ECMP table for the TC4 benchmark (parallel flow counts 1, 2, 4, 8, 16, 32) shows no scaling, because all flows hash to that single path.

After this second peering each DPU will see, e.g.:

```
gpu1$ ip route get 11.0.0.111
11.0.0.111
  nexthop via 172.16.97.248 dev p1  weight 1     ← /31 path from prior ask
  nexthop via 172.16.97.125 dev ovnvtep  weight 1 ← new path via VLAN 497 SVI
```

Two equal-cost next-hops, two physical egresses, flows hash across them.

## 2. Why this is safe / additive

- The prior `/31` peerings on `Eth1/24` and `Eth1/26` stay exactly as configured.
- `Eth1/23` and `Eth1/25` (gpu1.p0, gpu2.p0) stay in VLAN 497 access mode — **no change**.
- The VLAN 497 fabric is already carrying production VPC-OVN traffic between `Eth1/23` ↔ `Eth1/25` (geneve underlay). Adding a BGP neighbor that talks across the same VLAN does not change frame forwarding behavior.
- Rollback is one BGP `no neighbor` block on the leaf. Nothing else.

## 3. DPU side context (so you can verify what you're peering with)

Each DPU has an OVS internal port `ovnvtep` with an IP in `172.16.97.96/27` — this is part of the VPC-OVN underlay we set up:

| DPU | ovnvtep IP | ASN (matches prior /31 peering) |
|---|---|---|
| gpu1 | `172.16.97.98/27` | 65010 |
| gpu2 | `172.16.97.102/27` | 65020 |

These IPs are L2-reachable on VLAN 497 today — `ping 172.16.97.98` from anywhere on VLAN 497 should already work. Adding the BGP listener doesn't change any of that; it just opens TCP/179 on the SVI.

## 4. Requested leaf config

### 4.1 VLAN 497 SVI

If your VLAN 497 SVI already has an IP in `172.16.97.96/27`, skip to 4.2. Otherwise add a secondary IP in that range:

```
interface Vlan497
  description dpf-dummy-fabric — secondary IP for HBN ECMP second-path BGP
  no shutdown
  ip address 172.16.97.125/27 secondary
```

(Or any free address in `172.16.97.96/27` — `.125` is just a suggestion.)

### 4.2 Two new BGP neighbors

```
router bgp 65001                              ! leaf ASN (unchanged from prior ask)
  address-family ipv4 unicast
  !
  neighbor 172.16.97.98
    description gpu1 DPU ovnvtep (HBN ECMP second path)
    remote-as 65010                           ! same ASN as gpu1 /31 peer
    update-source Vlan497                     ! source from the SVI
    address-family ipv4 unicast
  !
  neighbor 172.16.97.102
    description gpu2 DPU ovnvtep (HBN ECMP second path)
    remote-as 65020
    update-source Vlan497
    address-family ipv4 unicast
```

The DPU's `ovnvtep` interface is in `172.16.97.96/27` so the SVI IP at `172.16.97.125` is directly L2-reachable — no multihop required.

### 4.3 (Optional but needed for testing) advertise something

If the leaf is already advertising `11.0.0.111/32` via the existing /31 sessions, you don't need to do anything extra — the same loopback will be sent over the new sessions too. We just want each DPU to see TWO next-hops for it.

## 5. What we'll do on the DPU side once it's up

For each DPU we'll add a second BGP neighbor stanza to FRR (paraphrased):

```
router bgp 65010                              ! per-DPU ASN (unchanged)
  neighbor 172.16.97.125 remote-as 65001      ! the new SVI peer
  neighbor 172.16.97.125 update-source ovnvtep
  address-family ipv4 unicast
    neighbor 172.16.97.125 activate
    maximum-paths 2                           ! enable ECMP install
```

We'll verify via `show ip route bgp` that the leaf loopback resolves through both peerings, then run the TC4 ECMP scaling sweep.

## 6. What we need back

1. Confirmation the SVI IP you used (in `172.16.97.96/27`).
2. Confirmation `show ip bgp summary` shows the two new neighbors in `Idle` / `Active` (they'll move to `Established` once we add the DPU-side FRR config).
3. That's it — everything else is already in place from your prior config.

---

## References

| Topic | NVIDIA DOCA HBN 2.6.0 section |
|---|---|
| ECMP supports up to 16 paths | *ECMP Example* |
| Underlay only IPv4 or BGP unnumbered supported | *Ethernet Virtual Private Network - EVPN* |
| EVPN not required on the leaf | *Multihop eBGP Peering for EVPN* |

Doc URL: <https://docs.nvidia.com/doca/archive/2-6-0/nvidia+doca+hbn+service+guide/index.html>
