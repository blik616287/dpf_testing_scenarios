# Fabric request — revert DPU `p0` uplinks to L2 (VLAN 497) for passthrough + ZT-accelerated testing

**To:** Network engineering (owner of `custeng.leaf1.1`)
**From:** DPF test team
**Leaf:** `custeng.leaf1.1` — Cisco Nexus N9K, NX-OS 9.3(11), AS 65001, router-id/lo `11.0.0.111`
**Scope:** two ports only — **Eth1/23** and **Eth1/25**. No change to Eth1/24 / Eth1/26.
**Risk:** low, local, fully reversible (rollback stanza included).

---

## TL;DR — the ask

Revert the two DPU **`p0`** uplinks from routed `/31` eBGP **back to L2 access VLAN 497**:

- **Eth1/23** (→ gpu1 `p0`): routed `172.16.97.240/31` → **`switchport access vlan 497`**
- **Eth1/25** (→ gpu2 `p0`): routed `172.16.97.244/31` → **`switchport access vlan 497`**
- MTU **9216** on both; **confirm the two ports are in one bridged broadcast domain** (see §5 — this
  is the part that has bitten us before).
- **Leave Eth1/24 and Eth1/26 (the `p1` uplinks) exactly as they are** — routed `/31` eBGP for HBN.

This restores the pre-2026-05-18 config that these two ports already ran for months. It's the same
change you actioned in reverse on **2026-05-20** (`FABRIC_REQUEST_L3_BGP_4UPLINKS.md`), just rolled back
on `p0` only.

---

## 1. Why — this unblocks two test modes that the all-L3 conversion broke

We run three DPF dataplane modes on the same two hosts, and they need different things from the `p0`
uplinks:

| Mode | What the `p0` uplink must be | Why |
|------|------------------------------|-----|
| **Passthrough** (`dpf-ovn-baseline`) | **L2, both `p0` in one broadcast domain** | The DPU is a transparent L2 bridge (`p0 ↔ pf0hpf`); the two hosts' PFs must be **L2-adjacent** on `172.16.97.0/24`. |
| **ZT-accelerated** (`dpf-ovn-accelerated`, VPC-OVN) | **L2, flat segment** | OVN **geneve** VTEPs ride a flat L2; each DPU's `ovnvtep` IP must be L2-reachable. |
| **HBN** (`dpf-ovn-hbn`) | routed `/31` eBGP | HBN wants an L3 ECMP underlay (this is why `p0` was converted on 2026-05-18). |

When all four uplinks were made routed `/31` on 2026-05-18, **passthrough and accelerated broke**:
frames egress gpu1's `p0` but never arrive at gpu2's `p0`, because the leaf no longer L2-bridges the
two ports (documented in `FABRIC_NETWORK_TEAM_REQUEST.md`). We now need to run the passthrough vs
accelerated comparison again, so `p0` has to go back to L2.

HBN and passthrough/accelerated are **mutually exclusive on the `p0` ports** — this request covers the
switch to L2; the exact **rollback to L3** is in §7 for when we return to an HBN campaign. (An optional
way to avoid flip-flopping and run all three at once is in §8.)

---

## 2. Current state → target

| Leaf port | DPU port | **Today** (HBN, all-L3) | **Target** (passthrough/accel) |
|-----------|----------|--------------------------|--------------------------------|
| **Eth1/23** | gpu1 `p0` | routed `/31` — leaf `172.16.97.240/31`, DPU `.241`, eBGP AS 65001↔65010 | **access VLAN 497** |
| Eth1/24 | gpu1 `p1` | routed `/31` — leaf `172.16.97.248/31`, DPU `.249` | **unchanged** (HBN) |
| **Eth1/25** | gpu2 `p0` | routed `/31` — leaf `172.16.97.244/31`, DPU `.245`, eBGP AS 65001↔65020 | **access VLAN 497** |
| Eth1/26 | gpu2 `p1` | routed `/31` — leaf `172.16.97.250/31`, DPU `.251` | **unchanged** (HBN) |

Only the two **bold** rows change. The two eBGP neighbors on `p0` (`.241`, `.245`) will drop — expected.

---

## 3. Exact NX-OS config to apply

```
! ── gpu1 p0 ──────────────────────────────────────────────
interface Ethernet1/23
  no ip address
  no ip router ospf ... area ...        ! only if present; remove any L3 leftovers
  switchport
  switchport mode access
  switchport access vlan 497
  mtu 9216
  no shutdown

! ── gpu2 p0 ──────────────────────────────────────────────
interface Ethernet1/25
  no ip address
  switchport
  switchport mode access
  switchport access vlan 497
  mtu 9216
  no shutdown
```

Also remove the two now-dead eBGP neighbors from `router bgp 65001` if they were configured per-interface
(the `.241` and `.245` neighbors). The `p1` neighbors (`.249`, `.251`) stay.

---

## 4. The L2 fabric spec (unchanged from before — for reference)

| Property | Value |
|----------|-------|
| VLAN | **497** (`dpf-dummy-fabric`) |
| Mode | **untagged / access** |
| Subnet | `172.16.97.0/24` |
| MTU | **9216** (carries 9000-byte inner frames; geneve is ~9042 on the wire) |
| DHCP | none (static) |
| Ports that must bridge | **Eth1/23 ↔ Eth1/25** (plus whatever else is already in VLAN 497) |

**Who rides this L2 segment (informational — all endpoints are on the DPU/host side, nothing for you to configure):**

- **Passthrough:** host PFs `enp14s0f0np0` — gpu1 `172.16.97.10`, gpu2 `172.16.97.11`.
- **Accelerated:** OVN geneve VTEPs `ovnvtep` — gpu1 `172.16.97.98`, gpu2 `172.16.97.102` (pool `172.16.97.96/27`).
- Accelerated also declares a VPC egress-gateway pool `172.16.97.128/27`, but our testing is
  **east-west (pod-to-pod) only** — that pool is **declared but not routed**, so **no SVI, first-hop,
  or upstream routing is required** for it.

Out of scope: the **OOB/management** network `172.16.30.0/24` (OVN control-plane NB/SB at
`172.16.30.90:30641/30642`) is a separate 1 GbE path and is not affected by this request.

---

## 5. Validation — please confirm the two ports actually bridge

This is the one thing that has caught us before: on a prior attempt the two switchports shared a VLAN
**name** but were **not** in the same broadcast domain — zero broadcast/unicast crossed between them
(`FABRIC_NETWORK_TEAM_REQUEST.md`). Access-VLAN membership alone isn't proof. Please verify **actual L2
forwarding** between Eth1/23 and Eth1/25:

```
show vlan id 497                          ! Eth1/23 AND Eth1/25 both listed as members
show interface Ethernet1/23 switchport    ! mode access, access vlan 497, up
show interface Ethernet1/25 switchport
show spanning-tree vlan 497               ! neither port in BLK/blocking; same STP domain
show mac address-table vlan 497           ! after traffic: gpu2's host MAC learned on Eth1/23's side and vice-versa
```

Also please confirm none of these are silently isolating the ports:

- No **private-VLAN** isolation on VLAN 497 (`switchport mode private-vlan` / isolated).
- No **port isolation / protected** (`switchport protected`) on Eth1/23 or Eth1/25.
- No **storm-control** dropping broadcast/unknown-unicast at a low threshold.
- If this leaf is part of a **vPC/EVPN** fabric, that VLAN 497 is locally bridged between these two
  ports (not just extended over VXLAN to a peer).

**Success criterion:** a broadcast/ARP sourced on Eth1/23 is seen on Eth1/25 (and vice-versa), and each
side's MAC is learned on the other port.

---

## 6. How we'll verify end-to-end after the change (no action needed from you)

1. From each DPU, LLDP/CDP shows Eth1/23 (gpu1) and Eth1/25 (gpu2) as **access VLAN 497**.
2. Host-to-host on the fabric: from gpu1 `172.16.97.10`, `arping 172.16.97.11` crosses, and
   `ping -M do -s 9000 172.16.97.11` (jumbo, DF) succeeds — confirms L2 + 9216 MTU end-to-end.
3. Passthrough deploy (`dpf-ovn-baseline`) → `scripts/run_baseline.sh`; expect ~39 Gbit/s at 8 streams
   (matches the prior baseline in `results/dpf-ovn-baseline/SUMMARY.md`).
4. Accelerated deploy (`dpf-ovn-accelerated`) → confirm `ovnvtep` `.98 ↔ .102` L2-reachable and geneve
   tunnels up, then pod-to-pod benchmark.

---

## 7. Rollback — restore HBN (routed /31) on these two ports

When we return to an HBN campaign, flip Eth1/23 & Eth1/25 back to their current L3 config:

```
interface Ethernet1/23
  no switchport
  mtu 9216
  ip address 172.16.97.240/31
  no shutdown

interface Ethernet1/25
  no switchport
  mtu 9216
  ip address 172.16.97.244/31
  no shutdown
```

…and re-add the two eBGP neighbors under `router bgp 65001` (`.241` remote-as 65010 on Eth1/23,
`.245` remote-as 65020 on Eth1/25) — i.e. the exact state from `FABRIC_REQUEST_L3_BGP_4UPLINKS.md`.

---

## 8. Nice-to-have (optional) — run all three modes without flip-flopping the fabric

The mode-switch in §3/§7 means we ask you to reconfigure Eth1/23 & Eth1/25 each time we change test
campaigns. If it's easy on your side, an alternative keeps **all three modes working simultaneously**
and removes that back-and-forth — this is exactly the state the fabric was in **before 2026-05-18**:

- Keep Eth1/23 & Eth1/25 as **L2 access VLAN 497** (for passthrough + accelerated), **and**
- Add a **VLAN 497 SVI** on the leaf with a **BGP session per DPU** so HBN keeps a `p0` path over the
  SVI (instead of the routed `/31`). Peer the DPU `ovnvtep` addresses (gpu1 `172.16.97.98`, gpu2
  `172.16.97.102`) from an SVI secondary such as `172.16.97.125/27`, remote-as 65010 / 65020.

This is the setup we asked for in `FABRIC_HBN_SECOND_PEERING_REQUEST.md` (2026-05-13) and it worked;
it just adds one SVI + two SVI-based BGP neighbors. **Purely optional** — the mode-switch in §3 is the
minimum needed to unblock passthrough/accelerated. If you'd rather not carry the extra SVI/BGP, §3 + §7
(flip on demand) is completely fine.

---

## 9. Open items / please confirm

1. **VLAN 497 SVI** — does it still exist on the leaf, or was it removed during the all-L3 conversion?
   (Not needed for §3; relevant only for the §8 nice-to-have.)
2. Re-adding Eth1/23 & Eth1/25 to VLAN 497 is the **only** membership change (the /31 conversion just
   removed them) — confirm nothing else about VLAN 497 changed.
3. **MTU 9216** is still clean end-to-end on VLAN 497 (no lower MTU on any transit link/SVI).
4. Confirm **no DHCP** on VLAN 497 (endpoints are statically addressed).

---

## 10. Sources / prior requests (same format, same fabric)

- `FABRIC_REQUEST_L3_BGP_4UPLINKS.md` — the 2026-05-20 request that converted `p0` to routed /31
  (this doc is the reverse of its §8 rollback).
- `FABRIC_HBN_ECMP_REQUEST.md` — original per-port map; documents `p0` = VLAN 497 access baseline.
- `FABRIC_HBN_SECOND_PEERING_REQUEST.md` — the SVI + BGP-over-VLAN-497 setup referenced in §8.
- `FABRIC_NETWORK_TEAM_REQUEST.md` — the passthrough L2 / broadcast-domain investigation (the §5 failure mode).
- `STACK_EXPLANATION.md`, `memory/env_fabric_switchports.md` — mode↔fabric mapping and current port state.

---

*Summary: two-port, reversible L2 change (Eth1/23 & Eth1/25 → access VLAN 497, MTU 9216) to re-enable
passthrough and ZT-accelerated testing; `p1` (Eth1/24/26) untouched. The only thing we really need
double-checked is that the two `p0` ports genuinely bridge (§5). Optional SVI+BGP in §8 avoids future
flip-flopping.*
