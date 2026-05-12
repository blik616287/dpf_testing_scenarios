# Fabric request: HBN / ECMP setup for DPU acceleration testing

**Aligned with:** [NVIDIA DOCA HBN Service Guide 2.6.0](https://docs.nvidia.com/doca/archive/2-6-0/nvidia+doca+hbn+service+guide/index.html). Specific section citations appear inline next to each requirement so the network team can verify against the source.

---

## TL;DR

The DPU performance test plan ([TEST_CASES.md](TEST_CASES.md) Test Cases 3 & 4) requires demonstrating **aggregate-bandwidth uplift** from BGP/ECMP across each DPU's two 40 Gb/s uplinks. Today only one uplink per DPU (`p0`, on Eth1/23 and Eth1/25 in VLAN 497) carries traffic; the second uplink (`p1`) is link-up at the PHY layer but isn't in any forwarding domain we can reach. We need each DPU's `p1` switchport configured as a **routed L3 interface** with BGP peering on the leaf, so each DPU's routing table sees **two distinct L3 next-hops**. Without that, BGP installs only one path and ECMP scaling produces no bandwidth uplift.

**Concrete asks:**

0. **First**, send us `show running-config interface Ethernet1/24` and `Ethernet1/26` so we know the ports' actual current state. The cabling document suggests these are the p1 switchports; `show vlan id 497` doesn't list them, so they need to be confirmed and reconfigured anyway.
1. Configure those two switchports as **routed L3 interfaces** (`no switchport`). Two options below in [§ 4. Switchport config](#4-switchport-config). NVIDIA's published reference uses **BGP unnumbered** (option A); numbered /31 (option B) is also explicitly supported by the doc.
2. Enable eBGP on `custeng.leaf1.1` with one neighbor per uplink, distinct AS for each DPU.
3. Reply with the leaf-side ASN, the leaf-side IPs (if numbered) or interface names (if unnumbered), and confirmation that BGP listeners are up.

Estimated leaf-side change: ~20 lines of NX-OS. **No change to existing Eth1/23 or Eth1/25** — VLAN 497 stays as-is and our completed VPC-OVN benchmark dataset remains valid.

---

## 1. Confirmed port mapping

Per cabling documentation:

| Server | DPU port | Switch | Switchport | Current config |
|---|---|---|---|---|
| Server 1 (gpu1) | DPU Port 1 (`p0`) | `custeng.leaf1.1` | Eth1/23 | `switchport access vlan 497` ✓ — bridges to Eth1/25, VPC-OVN traffic rides this |
| Server 1 (gpu1) | DPU Port 2 (`p1`) | `custeng.leaf1.1` | **Eth1/24** | not in VLAN 497, no L3 config — needs reconfig |
| Server 2 (gpu2) | DPU Port 1 (`p0`) | `custeng.leaf1.1` | Eth1/25 | `switchport access vlan 497` ✓ — bridges to Eth1/23 |
| Server 2 (gpu2) | DPU Port 2 (`p1`) | `custeng.leaf1.1` | **Eth1/26** | not in VLAN 497, no L3 config — needs reconfig |

The DPU OS uses 0-indexed names (`p0`, `p1`); the switch description on Eth1/23 says "Port 0"; the cabling document uses "Port 1" / "Port 2". They're the same two ports, three naming conventions:

```
DPU "Port 1" in cabling doc  =  "Port 0" on switch description  =  p0 in DPU OS
DPU "Port 2" in cabling doc  =  "Port 1" on switch description  =  p1 in DPU OS
```

## 2. Empirical state we've already verified

- All four DPU uplinks (gpu1.p0, gpu1.p1, gpu2.p0, gpu2.p1) are physically up at 40 Gb/s — `ethtool` reports `Speed: 40000Mb/s, Link detected: yes` on each.
- Eth1/23 ↔ Eth1/25 bridge correctly: VPC-OVN geneve traffic between gpu1 and gpu2 sustains 23 Gbps single-stream / 39 Gbps multi-stream on this path. No fabric issue with the configured pair.
- Eth1/24 and Eth1/26 are link-up on our side. ARPs sent from gpu1.p1 (cabled into Eth1/24) increment that NIC's `tx_broadcast_phy` counter, but produce zero `rx_broadcast_phy` on either of gpu2's two ports. PHY-level evidence: frames leave gpu1.p1 cleanly; the switch is the loss point.
- `show vlan id 497` on `custeng.leaf1.1` lists `Po1, Eth1/23, Eth1/25, Eth1/31, Eth1/32, Eth1/1/1..Eth1/20/4` — Eth1/24 and Eth1/26 are not members.

## 3. Why HBN requires L3 (and why "same VLAN" won't work)

> **Cite:** DOCA HBN Service Guide 2.6.0, § *Ethernet Virtual Private Network - EVPN* — *"For the underlay, only IPv4 or BGP unnumbered configuration is supported."*

HBN runs FRR on each DPU and forms eBGP sessions with the leaf. **The underlay must be IP-routed**, not L2-bridged. Both numbered IPv4 and BGP unnumbered are explicitly supported per the cited line; both work.

The reason we cannot just put `p1` into VLAN 497 alongside `p0`:

- **Same VLAN → same broadcast domain → same leaf SVI → one BGP next-hop in the DPU routing table.** BGP would establish, but ECMP would install only one path.
- TC4's ECMP scaling sweep (1, 2, 4, 8, 16, 32 parallel flows) would show flat throughput — no bandwidth aggregation — which doesn't validate the HBN value proposition.

For ECMP to actually split traffic across both physical links the two paths must terminate on **two distinct L3 next-hops**, which on a single leaf means two routed interfaces / two BGP peerings.

## 4. Switchport config

NVIDIA's reference configuration (see § 5 example) uses **BGP unnumbered**. We can use either pattern; both are supported per the doc.

> **Cite:** DOCA HBN Service Guide 2.6.0, § *Sample Switch Configuration for EVPN* — Cumulus-style example uses `nv set vrf default router bgp neighbor swp1 peer-group fabric` and `nv set vrf default router bgp neighbor swp1 type unnumbered`. NX-OS equivalent below.

### Option A — BGP unnumbered (recommended, matches NVIDIA's reference)

```
interface Ethernet1/24
  description GPU svr 1 DPU 40Gb Port 1 (HBN unnumbered)
  no switchport
  mtu 9216
  speed 40000
  no negotiate auto
  no shutdown
!
interface Ethernet1/26
  description GPU svr 2 DPU 40Gb Port 1 (HBN unnumbered)
  no switchport
  mtu 9216
  speed 40000
  no negotiate auto
  no shutdown
```

No IP needed on these interfaces. The BGP transport will use IPv6 link-local. Confirm your NX-OS version supports interface-based BGP neighbors (`neighbor <interface>` syntax); if not, use Option B.

### Option B — Numbered /31 (also supported per the doc)

```
interface Ethernet1/24
  description GPU svr 1 DPU 40Gb Port 1 (HBN /31)
  no switchport
  mtu 9216
  speed 40000
  no negotiate auto
  ip address 10.99.10.0/31         ! .0 = leaf, .1 = DPU
  no shutdown
!
interface Ethernet1/26
  description GPU svr 2 DPU 40Gb Port 1 (HBN /31)
  no switchport
  mtu 9216
  speed 40000
  no negotiate auto
  ip address 10.99.11.0/31         ! .0 = leaf, .1 = DPU
  no shutdown
```

`10.99.10.0/31` and `10.99.11.0/31` are placeholders — please substitute whatever falls in your reserved transit range.

> **Cite (MTU):** DOCA HBN Service Guide 2.6.0, § *SF Interface MTU* — *"In the HBN container, all the interfaces MTU are set to 9216 by default."* The leaf-side MTU should match.

## 5. BGP on the leaf

### Option A — BGP unnumbered

```
router bgp 65001                                  ! leaf ASN — substitute your scheme
  router-id 10.99.0.1
  address-family ipv4 unicast
  !
  neighbor Ethernet1/24
    description gpu1 DPU (HBN)
    remote-as 65010                               ! gpu1 DPU ASN
    address-family ipv4 unicast
  !
  neighbor Ethernet1/26
    description gpu2 DPU (HBN)
    remote-as 65020                               ! gpu2 DPU ASN — distinct from gpu1
    address-family ipv4 unicast
```

### Option B — Numbered /31

```
router bgp 65001
  router-id 10.99.0.1
  address-family ipv4 unicast
  !
  neighbor 10.99.10.1
    description gpu1 DPU (HBN)
    remote-as 65010
    address-family ipv4 unicast
  !
  neighbor 10.99.11.1
    description gpu2 DPU (HBN)
    remote-as 65020
    address-family ipv4 unicast
```

eBGP between the leaf and each DPU. Per-DPU ASNs (rather than a shared one) avoid BGP loop-prevention edge cases when the two DPUs eventually see each other's routes via the leaf. NVIDIA's published example uses a single DPU AS (63642) against a fabric AS (63640), but per-DPU ASNs are also valid and operationally simpler. Private 4-byte ASNs are fine.

### (Optional but useful) Advertise a route the DPUs will route over

To validate ECMP we need the leaf to advertise *something* to both DPUs that they then resolve via ECMP next-hops. Easiest is the leaf's loopback or a synthetic /32 it injects:

```
interface loopback0
  ip address 10.99.0.1/32
!
router bgp 65001
  address-family ipv4 unicast
    network 10.99.0.1/32
```

Each DPU will then see `10.99.0.1/32` reachable via both peerings — two equal-cost paths. iperf3 between the two DPUs targeting routes installed via this BGP setup will exercise ECMP across both uplinks.

> **Cite (ECMP):** DOCA HBN Service Guide 2.6.0, § *ECMP Example* — *"HBN supports up to 16 paths for ECMP."* We only need 2 paths for this test.

## 6. Things the leaf does NOT need

> **Cite:** DOCA HBN Service Guide 2.6.0, § *Multihop eBGP Peering for EVPN* — *"Switches in the provider fabric provide IPv4 and IPv6 transport and do not have to support EVPN."*

The leaf does **not** need:
- EVPN address family
- VxLAN configuration
- L2VPN
- Any overlay protocol

The leaf only needs plain BGP IPv4 unicast + ECMP. This significantly limits the scope of what's being asked.

## 7. Operational note: do not admin-shut these ports

> **Cite:** DOCA HBN Service Guide 2.6.0, § *Disabling DPU Uplinks* — *"The uplink ports must be always kept administratively up for proper operation of HBN."*

Once Eth1/24 and Eth1/26 are configured, **do not** admin-shut them during testing or otherwise. NVIDIA documents that disabling an HBN uplink port also disables the corresponding DPU-side representor, which breaks data forwarding for HBN. For failover testing (TC3 phase 3), we'll trigger a controlled failover from the DPU side, not by shutting the leaf port.

## 8. What we need back from you

1. The actual switchport names you used (we expect Eth1/24 and Eth1/26 per the cabling doc — please confirm in the reply).
2. Which option you picked (A: unnumbered, or B: numbered /31).
3. **If A:** confirmation that BGP is configured with `neighbor Ethernet1/24` and `neighbor Ethernet1/26` style peers, plus the leaf ASN you used. **If B:** the actual /31s and IPs you assigned, plus the leaf ASN.
4. Confirmation that BGP listeners are up (`show ip bgp summary` with both neighbors in `Idle`/`Active` state — we'll bring them up from the DPU side once we have the IPs/interface names).
5. The loopback or test /32 you're advertising (so we know what to target for the ECMP-scaling iperf3 runs).

Once we have those, configuring FRR on each DPU takes about 10 minutes per DPU. We'll then deploy the `dpf-ovn-hbn` cluster, run the TC2 benchmark matrix on it (5 × 11 tests, ~80 minutes), and run the ECMP scaling sweep (parallel-flow count 1, 2, 4, 8, 16, 32). End-to-end: HBN data should be ready for the report ~2 hours after the leaf config lands.

## 9. Why this is no risk to existing benchmarks

- `Eth1/23` and `Eth1/25` are not modified — they stay in VLAN 497.
- The current VPC-OVN cluster keeps using its existing geneve-over-VLAN-497 underlay.
- The new `Eth1/24` / `Eth1/26` config is additive. If the HBN cluster never gets deployed or BGP never establishes, nothing else breaks.
- Rollback is two interface stanzas reverted to default (`switchport`, no IP) — VLAN 497 stays untouched throughout.

---

## References

| Topic | NVIDIA DOCA HBN 2.6.0 section |
|---|---|
| Underlay must be IPv4 or BGP unnumbered | *Ethernet Virtual Private Network - EVPN* |
| EVPN not required on the leaf | *Multihop eBGP Peering for EVPN* |
| Uplinks must stay admin-up | *Disabling DPU Uplinks* |
| HBN container MTU is 9216 | *SF Interface MTU* |
| ECMP supports up to 16 paths | *ECMP Example* |
| Sample switch BGP unnumbered config | *Sample Switch Configuration for EVPN* |

Doc URL: <https://docs.nvidia.com/doca/archive/2-6-0/nvidia+doca+hbn+service+guide/index.html>
