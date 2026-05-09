# Fabric request: HBN / ECMP setup for DPU acceleration testing

## TL;DR

The DPU performance test plan ([TEST_CASES.md](TEST_CASES.md) Test Cases 3 & 4) requires demonstrating **aggregate-bandwidth uplift** from BGP/ECMP across each DPU's two 40 Gb/s uplinks. Today only one uplink per DPU (`p0`, on Eth1/23 and Eth1/25 in VLAN 497) carries traffic; the second uplink (`p1`) is link-up at the PHY layer but isn't bridging anywhere we can reach. We need each DPU's `p1` switchport configured as a **routed `/31`** with its own BGP peering on the leaf so each DPU's routing table sees **two distinct L3 next-hops**. Without that, BGP installs only one path and ECMP scaling produces no bandwidth uplift.

**Concrete asks:**

0. **First**, send us `show running-config interface Ethernet1/24` and `Ethernet1/26` so we know the ports' actual current state (the cabling document suggests these are the p1 switchports, but `show vlan id 497` doesn't list them — please confirm).
1. Configure those two switchports as routed `/31` interfaces (NX-OS config below).
2. Enable BGP on `custeng.leaf1.1` with neighbor entries for the two DPU-side `/31` peer IPs, plus a small route to advertise so we can verify ECMP installs both next-hops.
3. Reply with the actual switchport names, leaf-side IPs, and leaf ASN you used so we can configure FRR on the DPUs.

Estimated leaf-side change: ~20 lines of NX-OS. **No change to existing Eth1/23 or Eth1/25** — VLAN 497 stays as-is, and our completed VPC-OVN benchmark dataset remains valid.

**Why "routed /31" and not "p1 added to VLAN 497"** is covered below in [§ Why we need ECMP, not "p1 added to VLAN 497"](#why-we-need-ecmp-not-p1-added-to-vlan-497). Short version: same VLAN = same SVI = one BGP next-hop = no bandwidth aggregation in TC4.

---

## Confirmed port mapping

Per cabling documentation:

| Server | DPU port | Switch | Switchport | Current config |
|---|---|---|---|---|
| Server 1 (gpu1) | DPU Port 1 (`p0`) | `custeng.leaf1.1` | Eth1/23 | `switchport access vlan 497` ✓ |
| Server 1 (gpu1) | DPU Port 2 (`p1`) | `custeng.leaf1.1` | **Eth1/24** | (not in VLAN 497 — needs config) |
| Server 2 (gpu2) | DPU Port 1 (`p0`) | `custeng.leaf1.1` | Eth1/25 | `switchport access vlan 497` ✓ |
| Server 2 (gpu2) | DPU Port 2 (`p1`) | `custeng.leaf1.1` | **Eth1/26** | (not in VLAN 497 — needs config) |

The DPU OS uses 0-indexed names (`p0`, `p1`); the switch description uses "Port 0" / "Port 1"; the cabling document uses "Port 1" / "Port 2". They're the same two ports, three naming conventions:

```
DPU Port 1 in the doc  =  "Port 0" on the switch description  =  p0 in the DPU OS
DPU Port 2 in the doc  =  "Port 1" on the switch description  =  p1 in the DPU OS
```

## What we already verified

- All four DPU uplinks are physically up at 40 Gb/s (`ethtool` link detected, advertised correctly).
- Eth1/23 and Eth1/25 bridge correctly: VPC-OVN geneve traffic between gpu1 and gpu2 sustains 23 Gbps single-stream / 39 Gbps multi-stream on this path. No fabric issue.
- Eth1/24 and Eth1/26 are link-up on our side. ARPs sent on gpu1.p1 (the cable into Eth1/24) increment the NIC's `tx_broadcast_phy` counter, but produce zero `rx_broadcast_phy` on either of gpu2's two ports. PHY-level test confirms frames leave gpu1.p1 cleanly; switch is the loss point. `show vlan id 497` does not list Eth1/24 or Eth1/26, which is consistent — those ports aren't in any forwarding domain we have visibility into.

## Why we need ECMP, not "p1 added to VLAN 497"

The intuitive fix — adding Eth1/24 and Eth1/26 to VLAN 497 alongside the p0 ports — gets us link-level redundancy but **zero bandwidth uplift**. With both DPU uplinks landing on the same broadcast domain / same SVI, the DPU's routing table sees one next-hop. BGP would establish, but ECMP would install only one path. TC4's ECMP scaling benchmark (1, 2, 4, 8, 16, 32 parallel flows) would show no scaling and the test would not validate the HBN value proposition.

For ECMP to actually split traffic across both physical links, **the two paths must terminate on two distinct L3 next-hops**. The cleanest way on a single leaf is two routed (`no switchport`) `/31` interfaces, each with its own BGP peering.

## Requested config

### 1. Switchports

Convert `Eth1/24` (gpu1.p1) and `Eth1/26` (gpu2.p1) from access-port to routed mode.

```
interface Ethernet1/24
  description GPU svr 1 DPU 40Gb Port 1 (HBN ECMP)
  no switchport
  mtu 9216
  speed 40000
  no negotiate auto
  ip address 10.99.10.0/31         ! .0 = leaf, .1 = DPU side
  no shutdown
!
interface Ethernet1/26
  description GPU svr 2 DPU 40Gb Port 1 (HBN ECMP)
  no switchport
  mtu 9216
  speed 40000
  no negotiate auto
  ip address 10.99.11.0/31         ! .0 = leaf, .1 = DPU side
  no shutdown
```

`10.99.10.0/31` and `10.99.11.0/31` are placeholders — please substitute whatever falls in your reserved transit range. The two `/31`s only need to be unique to each other and not collide with anything else.

### 2. BGP on the leaf

```
router bgp 65001                   ! leaf ASN — substitute your scheme
  router-id 10.99.0.1
  address-family ipv4 unicast
  !
  neighbor 10.99.10.1
    description gpu1 DPU (HBN)
    remote-as 65010                ! gpu1 DPU ASN
    address-family ipv4 unicast
  !
  neighbor 10.99.11.1
    description gpu2 DPU (HBN)
    remote-as 65020                ! gpu2 DPU ASN — distinct from gpu1
    address-family ipv4 unicast
```

eBGP between the leaf and each DPU. Per-DPU ASNs (rather than a shared one) avoid BGP loop-prevention edge cases when the two DPUs see each other's routes via the leaf. Private 4-byte ASNs are fine.

### 3. (Optional but useful) Advertise a route the DPUs will route over

To validate ECMP we need the leaf to advertise *something* to both DPUs that they then resolve via ECMP next-hops. Easiest is the leaf's loopback or a synthetic /32 it injects:

```
interface loopback0
  ip address 10.99.0.1/32
!
router bgp 65001
  address-family ipv4 unicast
    network 10.99.0.1/32
```

The DPUs will then see `10.99.0.1/32` reachable via `10.99.10.0` and `10.99.11.0` — two equal-cost paths. iperf3 between the two DPUs targeting routes installed via this BGP setup will exercise ECMP.

## What we need back from you

1. The actual switchport names you used (we expect `Eth1/24` and `Eth1/26` per the cabling doc — please confirm).
2. The leaf-side IPs you assigned to each `/31`.
3. The leaf BGP ASN you used.
4. Confirmation that BGP listeners are up (`show ip bgp summary` with both neighbors in `Idle`/`Active` state — we'll bring them up from the DPU side once we have the IPs).

Once we have those four items, configuring FRR on the DPUs takes about 10 minutes per DPU. We'll then deploy the `dpf-ovn-hbn` cluster, run the TC2 benchmark matrix on it (5 × 11 tests, ~80 minutes), and run the ECMP scaling sweep (parallel-flow count 1, 2, 4, 8, 16, 32). End-to-end: HBN data should be ready for the report ~2 hours after the leaf config lands.

## Why this is no risk to existing benchmarks

- `Eth1/23` and `Eth1/25` are not modified — they stay in VLAN 497.
- The current VPC-OVN cluster keeps using its existing geneve-over-VLAN-497 underlay.
- The new `Eth1/24` / `Eth1/26` config is additive. If the HBN cluster never gets deployed or BGP never establishes, nothing else breaks.
- We can roll the change back by reverting the two interface stanzas — VLAN 497 is untouched throughout.
