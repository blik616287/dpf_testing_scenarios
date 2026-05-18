# Network request — convert 4 DPU uplinks to L3 routed eBGP (DPF HBN underlay)

**To:** Network engineering — `custeng.leaf1.1` (Cisco Nexus, NX-OS 9.3(11))
**From:** DPF / BlueField benchmarking
**Change type:** Convert 2 access ports to routed; bring up eBGP on all 4 uplinks
**Maintenance impact:** the 2 BlueField hosts (gpu1, gpu2) lose high-speed
connectivity during the change. No other workload is on these ports.

This request presents **two options** — decide **up front**, before the change
window (do not mix them across the 4 uplinks):
- **Route A — BGP unnumbered** — matches the NVIDIA reference architecture.
  Choose this **only if NX-OS unnumbered BGP is judged viable on this Nexus
  platform** — the §5 Phase A0 feature check is what makes that call.
- **Route B — numbered /31** — choose this if unnumbered is not viable.
  Functionally identical eBGP + ECMP; 2 of the 4 links already run it today.

---

## 1. Why — and the NVIDIA reference this is based on

We are rebuilding the cluster on the **NVIDIA DPF `hbn-ovnk` reference
deployment** (OVN-Kubernetes as primary CNI, offloaded to BlueField-3, with
DOCA HBN as the routing underlay). In that design **HBN runs BGP on the DPU and
every DPU high-speed port is an L3 routed uplink to the ToR** — not an L2 access
port.

Reference specs inspected to inform this request (full URLs in **§10 Sources**):

| Ref | What it specifies | NVIDIA source |
|---|---|---|
| [R1] | HBN `startupYAMLJ2`: eBGP per uplink, `peer-group hbn` / `remote-as external`, neighbors on `p0_if`/`p1_if`, ECMP via `path-selection multipath aspath-ignore on`, `multipath ebgp 16`, redistribute connected, AS 65101/65201 per worker | `doca-platform` repo — `hbn-ovnk` use-case guide |
| [R2] | ToR/leaf fabric config — routed uplinks, **BGP unnumbered**, `peer-group hbn remote-as external`, `path-selection multipath aspath-ignore on`, redistribute connected/static, leaf AS 65001, loopback 11.0.0.101/32 | RDG → **Fabric Configuration** page |
| [R3] | HBN BGP neighbor model (`type: unnumbered`), `multipath ebgp 16`, p0_if/p1_if uplinks/MTU; "ToR must support BGP and EVPN" | `doca-platform` repo — `hbn` use-case guide |
| [R4] | DPF system prerequisites — `host-trusted` mode, "DPU high-speed ports p0/p1 must be connected to the network", DPF v25.10.1 | `doca-platform` repo — host-trusted prerequisites |
| [R5] | Product context — "HBN enables routing on the server side using BlueField as a BGP router"; OVN-Kubernetes provides the geneve overlay | RDG Introduction / DPF v25.10.1 docs |
| [R6] | Cisco NX-OS "BGP Interface Peering via IPv6 Link-Local" (unnumbered) — config, prerequisites, TCAM carving, release support | Cisco Nexus 9000 NX-OS Unicast Routing Config Guide, 9.3(x) |

> **R2 is written for an NVIDIA Spectrum switch (Cumulus Linux / NVUE `nv set`).**
> `custeng.leaf1.1` is a Cisco Nexus — §5 translates the reference into NX-OS.
> **EVPN is *not* required** here: OVN-Kubernetes provides the overlay (geneve);
> HBN only needs a plain **L3 BGP unicast underlay with ECMP**.

---

## 2. Rationale — why this change, and why these design choices

### 2.1 Why move off the current setup at all

**Current state:** each DPU has `p0` = **L2 access port, VLAN 497** and `p1` =
**routed /31**. HBN BGP currently comes up by peering *numbered over the VLAN 497
SVI* for the p0 path and over the /31 for p1. It works — but it is the wrong
shape, for four concrete reasons:

1. **It is an off-reference deviation.** The NVIDIA `hbn-ovnk` reference
   ([R1],[R2]) makes **every** DPU uplink an L3 routed BGP port straight into
   HBN. Peering a routing protocol over a shared VLAN SVI is not in the
   reference — and that deviation has been a direct source of fragility
   (SVI ARP failures, VLAN/SFC interaction, the p0 path repeatedly dropping).
2. **ECMP is asymmetric.** ECMP wants two *identical, equal-cost* paths. A
   switchport and a /31 are different constructs — the two uplinks per DPU are
   not interchangeable, so the ECMP the design depends on is built on uneven
   legs.
3. **A routing peer over a multi-access segment is fragile by design.** The
   VLAN 497 SVI is a shared broadcast domain; eBGP belongs on **point-to-point**
   links, where neighbor loss is detected directly from link state.
4. **It couples HBN to a VLAN it should not need.** HBN is a BGP router; its
   uplinks should be routed point-to-point with no L2/VLAN dependency.

**Target:** all **4 uplinks uniform, L3 routed, point-to-point eBGP.** Result —
matches the reference exactly, symmetric ECMP on equal legs, point-to-point
failure detection, and zero VLAN coupling. 2 of the 4 links (`p1`) already run
numbered eBGP today, so for Route B only the 2 `p0` ports change model.

### 2.2 Why unnumbered is preferred — *when the platform supports it* (Route A)

The NVIDIA reference architecture uses **BGP unnumbered** end to end — the ToR
([R2]) and HBN ([R1],[R3]). Policy for this deployment is to **match the NVIDIA
reference architecture**, so unnumbered is the target. Practically it also means
no /31 transit IPAM (8 addresses saved) and interface-name-based neighbors with
automatic discovery.

### 2.3 Why the engineer must *verify* unnumbered support before committing

Unnumbered BGP is the **native idiom on Cumulus** (the reference switch). On
Cisco NX-OS it is a **distinct feature** — *"BGP Interface Peering via IPv6
Link-Local"* + **RFC 5549** (carrying IPv4 prefixes over an IPv6 next-hop) [R6].
It **is** supported on NX-OS 9.3(x) — BFD support from 9.3(3), dynamic-AS for
interface peers from 9.3(6); `custeng.leaf1.1` runs **9.3(11)**, past that bar.

But it carries platform/config prerequisites that **must be confirmed on this
specific switch** before a production change — this is *why* §5 Route A starts
with a verification phase, not a blind apply:

- **TCAM re-carving.** BGP neighbors over link-local require the `ing-sup` TCAM
  region enlarged 512 → 768 — and a TCAM region change needs `copy run start`
  **+ a reload** [R6].
- **RFC 5549 dependency.** With no IPv4 address on the link you must enable
  `ip forward` on the interface for RFC 5549 to work [R6].
- **Hardware/ASIC support.** RFC 5549 hardware support is line-card/platform
  dependent (e.g. N9500 needs -R line cards, from 9.2(2)) — must be confirmed
  for this Nexus model [R6].
- **Parallel-link LLA collision.** Each DPU has *two* uplinks to the *same*
  leaf. NX-OS unnumbered BGP forbids the same link-local address on multiple
  interfaces, so `ipv6 link-local use-bia` is **mandatory** on every uplink
  (9.3(6)+) — see §5 Route A, Phase A2 [R6].

If verification (Route A, Phase A0/A-pilot) shows the platform does not cleanly
support it → **fall back to Route B (numbered /31)**, functionally identical
eBGP + ECMP. Matching the reference is the goal; a half-working unnumbered
config is worse than a clean numbered one.

---

## 3. Target topology

```
                         custeng.leaf1.1   (Cisco Nexus, AS 65001, lo 11.0.0.101/32)
        Eth1/23 ─┐   Eth1/24 ─┐      ┌─ Eth1/25      ┌─ Eth1/26
            │             │                │              │
        gpu1 p0       gpu1 p1          gpu2 p0        gpu2 p1
        └──── gpu1 HBN ────┘            └──── gpu2 HBN ────┘
           AS 65010, lo 11.0.0.1/32        AS 65020, lo 11.0.0.2/32

ECMP: leaf reaches each DPU over 2 equal-cost eBGP paths; each DPU reaches
the leaf (and the far DPU) over its own 2 uplinks. 4 eBGP sessions total.
```

All 4 links: **point-to-point, MTU 9216, eBGP IPv4 unicast.** No EVPN, no LAG,
no VLAN. Leaf port numbers are from prior fabric notes — **confirm with
`show lldp neighbors`** (§9).

---

## 4. Addressing & AS plan  (confirm against fabric IPAM)

### 4.1 AS numbers & loopbacks — apply to BOTH routes
| Device | BGP AS | Loopback (router-id) |
|---|---|---|
| `custeng.leaf1.1` | **65001** | `11.0.0.101/32` |
| gpu1 (HBN) | **65010** | `11.0.0.1/32` |
| gpu2 (HBN) | **65020** | `11.0.0.2/32` |

gpu1/gpu2 **keep the existing fabric ASNs 65010 / 65020** — already live on the
leaf's `p1` BGP sessions, so the leaf needs **no ASN change**, only the new `p0`
sessions added. The leaf keeps its current ASN (`65001` shown below is
illustrative — substitute the real one). The NVIDIA reference's 65101/65201 are
illustrative too; any per-DPU distinct private ASN works, so there is no reason
to churn working ASNs. HBN is set to 65010/65020 in its DPUServiceConfiguration.

### 4.2 /31 transit links — **Route B (numbered) only**
Route A (unnumbered) needs **no /31s** — links use IPv6 link-local only.

| Link | Leaf int | Leaf IP /31 | Host port | Host IP /31 |
|---|---|---|---|---|
| gpu1-p0 | Eth1/23 | `172.16.97.240/31` | gpu1 p0 (`p0_if`) | `172.16.97.241/31` |
| gpu1-p1 | Eth1/24 | `172.16.97.242/31` | gpu1 p1 (`p1_if`) | `172.16.97.243/31` |
| gpu2-p0 | Eth1/25 | `172.16.97.244/31` | gpu2 p0 (`p0_if`) | `172.16.97.245/31` |
| gpu2-p1 | Eth1/26 | `172.16.97.246/31` | gpu2 p1 (`p1_if`) | `172.16.97.247/31` |

**Routes the leaf will learn from each DPU:** the DPU loopback `/32`
(`11.0.0.1`/`11.0.0.2`) and the OVN underlay subnets HBN redistributes — the
geneve VTEP pool (`10.0.120.0/22`, a `/29` per DPU) and the `pf2dpu2` subnet.
The leaf transits these between the two DPUs.

---

## 5. Leaf configuration — Cisco NX-OS

### ROUTE A — BGP unnumbered  *(matches NVIDIA reference [R2] — use ONLY if Phase A0 confirms the platform supports it)*

> Reference [R2] (Cumulus/NVUE):
> `nv set interface swp11-14` routed, no IP · `nv set vrf default router bgp
> neighbor swp11-14 type unnumbered` · `nv set vrf default router bgp peer-group
> hbn remote-as external` · `nv set vrf default router bgp path-selection
> multipath aspath-ignore on`.
> NX-OS equivalent — *"BGP Interface Peering via IPv6 Link-Local"* + RFC 5549 [R6].

#### Phase A0 — Feature verification (non-disruptive — run first)
```
show version                                          ! confirm NX-OS 9.3(11) + Nexus model
show hardware access-list tcam region | include ing-sup   ! current ing-sup size (need 768)
show running-config | include "feature bgp"
show ipv6 nd interface brief                           ! confirm ICMPv6 ND/RA available
```
Confirm against the Cisco 9.3(x) BGP guide [R6] that **this Nexus model**
supports RFC 5549 in hardware. NX-OS release (9.3(11) ✓) is already past the
9.3(6) interface-peer / dynamic-AS bar.

#### Phase A1 — TCAM re-carving  *(one-time, DISRUPTIVE — requires reload)*
Only if Phase A0 shows `ing-sup` < 768:
```
hardware access-list tcam region ing-sup 768
copy running-config startup-config
reload
```
After reload: `show hardware access-list tcam region | include ing-sup` → `768`.

#### Phase A2 — Routed interfaces, link-local only (×4)

> **Parallel-links requirement [R6].** This topology has two uplinks per DPU to
> the *same* leaf. NX-OS will not allow the same link-local address on multiple
> interfaces, so `ipv6 link-local use-bia` (derive a unique LLA from the
> burned-in MAC) is **mandatory** on every uplink — required for parallel-link
> deployments from NX-OS 9.3(6). Omitting it breaks unnumbered discovery here.

```
default interface Ethernet1/23
interface Ethernet1/23
  description L3-uplink-gpu1-p0-HBN
  no switchport
  mtu 9216
  no ip address
  ipv6 address use-link-local-only
  ipv6 link-local use-bia          ! MANDATORY here: unique LLA per interface (parallel links)
  ip forward                       ! RFC 5549: required when the link has no IPv4 address
  ipv6 nd ra-interval 4 min 3      ! speed up RA-based neighbor discovery / BGP convergence
  ipv6 nd ra-lifetime 10
  no shutdown
```
Repeat verbatim for `Ethernet1/24`, `Ethernet1/25`, `Ethernet1/26`
(`default interface` is only needed on 1/23 & 1/25 — the former access ports).

Not supported in interface-neighbor mode [R6] (none are needed here):
`update-source`, `ebgp-multihop`, `disable-connected-check`, `maximum-peers`,
BFD multihop.

#### Phase A3 — BGP
```
route-map ALLOW-ALL permit 10

router bgp 65001
  router-id 11.0.0.101
  bestpath as-path multipath-relax           ! mirrors reference 'aspath-ignore on'
  log-neighbor-changes
  address-family ipv4 unicast
    maximum-paths 4                          ! ECMP across the 4 uplinks
    redistribute direct route-map ALLOW-ALL  ! advertise loopback + connected
    network 11.0.0.101/32

  neighbor Ethernet1/23
    remote-as 65010
    description gpu1-p0
    address-family ipv4 unicast
  neighbor Ethernet1/24
    remote-as 65010
    description gpu1-p1
    address-family ipv4 unicast
  neighbor Ethernet1/25
    remote-as 65020
    description gpu2-p0
    address-family ipv4 unicast
  neighbor Ethernet1/26
    remote-as 65020
    description gpu2-p1
    address-family ipv4 unicast
```

#### Phase A-pilot — prove it on ONE link before rolling all 4
Bring up **Eth1/24** (already routed today) unnumbered first. Confirm the
session reaches `Established` and a DPU prefix is learned with an IPv6
link-local next-hop (§7.A). Only then apply the remaining 3. If the session
will not establish after ND/TCAM/`ip forward` are confirmed → **switch to
Route B.**

> Exact CLI may vary slightly by NX-OS maintenance release — confirm syntax
> against the Cisco 9.3(x) Unicast Routing Configuration Guide [R6].

---

### ROUTE B — Numbered /31  *(use if unnumbered is not viable — functionally identical eBGP)*

#### B1 — Routed interfaces (×4), using §4.2 addressing
```
default interface Ethernet1/23
interface Ethernet1/23
  description L3-uplink-gpu1-p0-HBN
  no switchport
  mtu 9216
  ip address 172.16.97.240/31
  no shutdown
```
Repeat for `Eth1/24` (`172.16.97.242/31`), `Eth1/25` (`172.16.97.244/31`,
`default interface` first), `Eth1/26` (`172.16.97.246/31`).

#### B2 — BGP
```
route-map ALLOW-ALL permit 10

router bgp 65001
  router-id 11.0.0.101
  bestpath as-path multipath-relax
  log-neighbor-changes
  address-family ipv4 unicast
    maximum-paths 4
    redistribute direct route-map ALLOW-ALL
    network 11.0.0.101/32
  template peer HBN-DPU
    address-family ipv4 unicast
      send-community
      soft-reconfiguration inbound
  neighbor 172.16.97.241 remote-as 65010
    inherit peer HBN-DPU
    description gpu1-p0
  neighbor 172.16.97.243 remote-as 65010
    inherit peer HBN-DPU
    description gpu1-p1
  neighbor 172.16.97.245 remote-as 65020
    inherit peer HBN-DPU
    description gpu2-p0
  neighbor 172.16.97.247 remote-as 65020
    inherit peer HBN-DPU
    description gpu2-p1
```

---

### Both routes — loopback + optional BFD
```
interface loopback0
  description leaf-router-id
  ip address 11.0.0.101/32
```
**BFD** (recommended — sub-second failover; HBN supports it; BFD for unnumbered
is supported from NX-OS 9.3(3), single-hop only [R6]):
```
interface Ethernet1/23-26
  bfd interval 300 min_rx 300 multiplier 3
router bgp 65001
  neighbor <each>            ! add 'bfd' under each neighbor
    bfd
```

---

## 6. DPU / HBN side (for reference — applied by the DPF team)

HBN's `startupYAMLJ2` ([R1]/[R3]) is set to match the chosen route:

- **Route A (unnumbered)** — verbatim to the reference:
  ```yaml
  interface: { p0_if: {type: swp}, p1_if: {type: swp}, lo: {type: loopback, ip: {address: {11.0.0.1/32: {}}}} }
  router: { bgp: { autonomous-system: 65010, router-id: 11.0.0.1 } }
  vrf: { default: { router: { bgp: {
    neighbor: { p0_if: {peer-group: hbn, type: unnumbered}, p1_if: {peer-group: hbn, type: unnumbered} },
    peer-group: { hbn: {remote-as: external} },
    path-selection: { multipath: {aspath-ignore: on} } } } } }
  ```
- **Route B (numbered)** — `p0_if`/`p1_if` get the host-side /31s from §4.2;
  `neighbor` keys become the leaf /31 IPs; `peer-group hbn remote-as external`.

No action needed from network engineering on the DPU side — listed only so the
addressing and AS assignments can be cross-checked.

---

## 7. Validation — run on the leaf after applying

### 7.0 Interfaces & MTU (both routes)
```
show interface Ethernet1/23-26 brief         ! all 4: up, routed (not 'access')
show interface Ethernet1/23 | include MTU    ! MTU 9216 bytes  (repeat 24-26)
```

### 7.A Route A — unnumbered
```
show bgp ipv4 unicast summary                ! 4 neighbors by interface name, State = a PfxRcd count
show bgp ipv4 unicast neighbors Ethernet1/23 ! 'BGP state = Established'; fe80:: peer + 'interface peering'
show ip bgp neighbors Ethernet1/23           ! shows the interface used as a BGP peer
show ipv6 routers interface Ethernet1/23     ! remote router LLA learned via ICMPv6 RA — discovery proof
show ip route bgp                            ! DPU prefixes via IPv6 link-local next-hop (RFC 5549)
show ip route 11.0.0.1                       ! ECMP: TWO next-hops (Eth1/23 + Eth1/24)
show ip route 11.0.0.2                       ! ECMP: TWO next-hops (Eth1/25 + Eth1/26)
show forwarding ipv4 route 11.0.0.1          ! 2 next-hops in the hardware FIB
```
Jumbo proof (after BGP up — ping the learned DPU loopback, 9000-B, DF):
```
ping 11.0.0.1 packet-size 8972 df-bit count 5     ! expect 5/5, no fragmentation
ping 11.0.0.2 packet-size 8972 df-bit count 5
```

### 7.B Route B — numbered
```
ping 172.16.97.241 source 172.16.97.240 packet-size 8972 df-bit count 5   ! gpu1-p0, expect 5/5
                                                                          ! repeat .243/.245/.247
show ip bgp summary                          ! 4 neighbors, State/PfxRcd = a number (not Idle/Active)
show ip route 11.0.0.1                        ! ECMP: two next-hops via 172.16.97.241 + .243
show ip route 11.0.0.2                        ! ECMP: two next-hops via .245 + .247
show forwarding ipv4 route 11.0.0.1
```

A **single** next-hop on any DPU loopback = ECMP not working — check
`maximum-paths` and that both sessions to that DPU are up.

### 7.C DPU-side cross-check (DPF team, in each HBN container)
```
vtysh -c "show ip bgp summary"               ! 2 neighbors Established per DPU
vtysh -c "show ip route 11.0.0.2"            ! on gpu1: far DPU loopback, 2 ECMP next-hops
nv show vrf default router bgp
```

---

## 8. Rollback

```
! restore the two p0 ports to VLAN 497 access
default interface Ethernet1/23
interface Ethernet1/23
  switchport
  switchport mode access
  switchport access vlan 497
  mtu 9216
  no shutdown
! (repeat for Ethernet1/25)

! remove the BGP neighbors (interface- or IP-form, per route)
router bgp 65001
  no neighbor Ethernet1/23      ! Route A   — or:  no neighbor 172.16.97.241  (Route B)
  ...                          ! (all 4)
```
p1 (Eth1/24, Eth1/26) returns to its pre-change state. TCAM `ing-sup` carving
(Route A) can be left at 768 or reverted with another reload.

---

## 9. Confirmations needed from network engineering

1. **Route choice (decide first)** — run §5 Phase A0. If NX-OS unnumbered BGP is
   viable on this platform, use **Route A (unnumbered)** to match the NVIDIA
   reference; if not, use **Route B (numbered /31)**. Pick one before the change
   window — the two are not meant to be mixed across the 4 uplinks.
2. **Leaf port mapping** — confirm Eth1/23–26 ↔ gpu1-p0/p1, gpu2-p0/p1 via
   `show lldp neighbors`.
3. **VLAN 497** — confirm removing gpu1-p0 / gpu2-p0 from VLAN 497 breaks
   nothing else; whether the `Vlan497` SVI should be retained.
4. **TCAM reload (Route A)** — schedule the `ing-sup` re-carve + reload window.
5. **RFC 5549 hardware support (Route A)** — confirm for this Nexus model [R6].
6. **AS numbers** — leaf keeps its existing ASN; gpu1/gpu2 keep the existing
   fabric ASNs **65010 / 65020** (already live on the `p1` sessions). Confirm no
   collision.
7. **IP block (Route B only)** — `172.16.97.240/29` free for the four /31s.
8. **Jumbo MTU** — confirm `mtu 9216` applies on routed Eth1/23 & 1/25 (1/24 &
   1/26 already 9216), or apply the platform jumbo policy first.
9. **BFD** — apply or not (recommended).
10. **Default route** — should the leaf advertise a default to the DPUs
    (`default-information originate`) for host internet egress, or is that
    handled elsewhere?

---

## 10. Sources

All design values trace to the following references. DPF version pinned:
**v25.10.1**. Leaf: Cisco Nexus, **NX-OS 9.3(11)**. Retrieved 2026-05-18.

**[R1] DPF `hbn-ovnk` use-case guide — "OVN Kubernetes with Host Based Networking"**
NVIDIA `doca-platform` repository.
- `https://github.com/NVIDIA/doca-platform/tree/v25.10.1/docs/public/user-guides/host-trusted/use-cases/hbn-ovnk`
- Raw: `https://raw.githubusercontent.com/NVIDIA/doca-platform/public-main/docs/public/user-guides/host-trusted/use-cases/hbn-ovnk/README.md`
- Used for: HBN `startupYAMLJ2` BGP/ECMP stanza — `peer-group hbn` /
  `remote-as external`, unnumbered neighbors on `p0_if`/`p1_if`,
  `path-selection.multipath.aspath-ignore: on`, `redistribute connected`,
  per-worker AS (65101 / 65201), loopback router-id from the `11.0.0.0/24`
  pool; OVN-Kubernetes-provides-the-overlay design (no EVPN needed).

**[R2] RDG — "RDG for DPF with OVN-Kubernetes and HBN Services" → Fabric Configuration**
NVIDIA Docs (Solutions).
- `https://docs.nvidia.com/networking/display/public/sol/rdg_for_dpf_with_ovn-kubernetes_and_hbn_services/fabric+configuration`
- Parent: `https://docs.nvidia.com/networking/display/public/sol/rdg+for+dpf+with+ovn-kubernetes+and+hbn+services`
- Host-Trusted variant: `https://docs.nvidia.com/networking/display/public/SOL/RDG-for-DPF-Host-Trusted-with-OVN-Kubernetes-and-HBN-Services`
- Used for: the ToR/leaf reference — routed uplinks, BGP **unnumbered**
  (`neighbor swpXX type unnumbered`), `peer-group hbn remote-as external`,
  `path-selection multipath aspath-ignore on`, redistribute connected/static,
  leaf AS `65001`, loopback `11.0.0.101/32`. (Written for NVIDIA Spectrum /
  Cumulus Linux — translated to Cisco NX-OS in §5.)

**[R3] DPF HBN use-case guide — "Host Based Networking (HBN)"**
NVIDIA `doca-platform` repository.
- `https://github.com/NVIDIA/doca-platform/tree/public-main/docs/public/user-guides/host-trusted/use-cases/hbn`
- Used for: HBN BGP neighbor model `type: unnumbered`, `multipath { ebgp: 16 }`,
  `aspath-ignore: on`, p0_if/p1_if uplink/MTU, "ToR must support BGP and EVPN."

**[R4] DPF System Prerequisites — Host Trusted**
NVIDIA `doca-platform` repository.
- `https://github.com/NVIDIA/doca-platform/blob/public-main/docs/public/user-guides/host-trusted/prerequisites/system.md`
- Used for: `host-trusted` mode, "DPU high-speed ports p0/p1 must be connected
  to the network", Kubernetes 1.33–1.35, BlueField-3 / DOCA ≥2.5.

**[R5] DOCA Platform Framework v25.10.1 — product documentation**
NVIDIA Docs.
- `https://docs.nvidia.com/networking/display/dpf25101`
- RDG Introduction: `https://docs.nvidia.com/networking/display/public/SOL/RDG-for-DPF-with-OVN-Kubernetes-and-HBN-Services/Introduction`
- Used for: "HBN enables routing on the server side using BlueField as a BGP
  router"; OVN-Kubernetes with OVS-DOCA hardware offload.

**[R6] Cisco Nexus 9000 Series NX-OS Unicast Routing Configuration Guide, Release 9.3(x) — Configuring Advanced BGP**
Cisco.
- `https://www.cisco.com/c/en/us/td/docs/switches/datacenter/nexus9000/sw/93x/unicast/configuration/guide/b-cisco-nexus-9000-series-nx-os-unicast-routing-configuration-guide-93x/b-cisco-nexus-9000-series-nx-os-unicast-routing-configuration-guide-93x_chapter_011110.html`
- Used for: "BGP Interface Peering via IPv6 Link-Local for IPv4 and IPv6
  Address Families" (unnumbered) — `neighbor <interface> remote-as` config
  procedure, RFC 5549 (IPv4 prefix over IPv6 next-hop), the `ing-sup` TCAM
  carve 512→768, the `ip forward` requirement when the link has no IPv4
  address, ICMPv6 ND/RA-based discovery + the `ipv6 nd ra-interval/ra-lifetime`
  tuning, the **`ipv6 link-local use-bia` parallel-link requirement (9.3(6)+)**,
  interface-neighbor unsupported commands, the `show bgp/ip bgp/ipv6 routers`
  verification commands, release support (BFD for unnumbered from 9.3(3);
  dynamic-AS / VLAN interface peers from 9.3(6)).
- Page content verified by direct fetch 2026-05-18 (Wayback mirror:
  `web.archive.org/web/20250329234806/<the URL above>`).

**Companion document:** `OVNK_HBN_DOCUMENTED_PATH.md` (same repo) — the full
DPF deployment path that consumes this fabric change; cites the same [R1]–[R5].
