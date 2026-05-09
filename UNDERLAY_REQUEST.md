# 40G Underlay Configuration Request

**To:** Network Engineering
**From:** DPF Performance Test Team
**Re:** L3 underlay configuration on the BlueField-3 DPU 40G fabric for `dpf-ovn-baseline` / `dpf-ovn-accelerated` / `dpf-ovn-hbn` test clusters
**Status:** Blocked on switch-side configuration — host-side config ready to apply on confirmation
**Test cluster nodes:** `gpu1` (172.16.30.90), `gpu2` (172.16.30.253)
**Upstream switch:** `custeng.leaf1.1` (172.16.98.1, Cisco N9K-C9332PQ, NX-OS 9.3(11))

---

## TL;DR

The 40G DPU fabric is physically up on all four uplinks (gpu1 p0, gpu1 p1, gpu2 p0, gpu2 p1) and reaches the Cisco leaf, but **no IP layer is configured** on the host side of these links — DHCPv4 has no responder, RAs advertise no prefix and clear M/O flags, so SLAAC and DHCPv6 are both unusable. The hosts need static IPv4 transit /30s on the Cisco SVIs plus four `/32` route entries to the cluster loopbacks. With that in place, all DPF cluster pod traffic moves to the 40G path and we can begin the A/B benchmark suite.

**Concrete asks:**
1. Confirm the four Cisco switch ports / VLANs / SVIs that gpu1 p0, gpu1 p1, gpu2 p0, gpu2 p1 land on.
2. Assign IPv4 addressing per VLAN (we propose `10.99.10.0/30` … `10.99.13.0/30` — change if you have a reserved range).
3. Add four static routes to `10.99.0.1/32` (gpu1 loopback) and `10.99.0.2/32` (gpu2 loopback), each with two ECMP next-hops.
4. Optionally enable BGP from each DPU to the leaf (Tier 3 below) for the HBN test phase.

Estimated leaf-side change: ~12 lines of NX-OS config. No VLAN topology change.

---

## Background

This deployment runs NVIDIA DPF (DOCA Platform Framework) v25.10.1 on BlueField-3 DPUs in DPU mode (ECPF). Cluster pod-to-pod traffic is encapsulated by Cilium VXLAN and is meant to traverse the DPU's eswitch out the 40G uplinks (`p0` / `p1` on each DPU). The BlueField hardware offload only delivers a real performance uplift when traffic actually goes through the DPU data path. **Today, traffic is not going through the DPU.**

### Deployment model and division of responsibility

The deploy is two separate, sequential steps; the request below only concerns the second:

1. **One-time OS install — MAAS** lays down vanilla Ubuntu on the bare metal. After install MAAS is no longer in the path; cluster operation does not depend on MAAS being reachable. The cloud-init / netplan that exists on the hosts today is just whatever MAAS produced during install (e.g. `dhcp4: true` on `enp14s0f0np0` is a vanilla default for a NIC MAAS had no explicit instructions for; it's not a configuration intent).

2. **Cluster lifecycle — Spectro Cloud Palette edge agent.** Each node has the Palette edge agent installed and registers as an edge appliance. From that point on, all cluster lifecycle (create / scale / upgrade / tear down) is driven through Palette in edge-native BYOI mode. The DPF operator and its DPUServices run inside that cluster and own the **DPU-side** data plane (DPU OS, OVS, passthrough/HBN service chains, BGP for HBN). Verified healthy today.

Neither MAAS nor Palette/DPF configures the **40G data fabric** (`enp14s0f0np0` / `enp14s0f1np1` → DPU `p0`/`p1`). That's a customer-managed data network owned by Network Engineering — the existing 1 G mgmt path on `enp129s0f0` (172.16.30.0/24) is unrelated and works fine.

**What we need from you is the underlay (L2/L3) config on the 40G data fabric:** SVI IPs, host IPs, and routes. Once that's in place we'll replace the default vanilla netplan with static config matching whatever scheme you confirm, and the cluster will work end-to-end.

---

## Findings

### 1. The 40G physical layer is fully UP on all four uplinks

| Port | Link | Speed | OVS state |
|---|---|---|---|
| gpu1 host `enp14s0f0np0` (→ DPU `p0`) | yes | 40 Gb/s | admin up, link up, MTU 9216 |
| gpu1 host `enp14s0f1np1` (→ DPU `p1`) | yes | 40 Gb/s | admin up, link up, MTU 9216 |
| gpu2 host `enp14s0f0np0` (→ DPU `p0`) | yes | 40 Gb/s | admin up, link up, MTU 9216 |
| gpu2 host `enp14s0f1np1` (→ DPU `p1`) | yes | 40 Gb/s | admin up, link up, MTU 9216 |

DPU OVS `br-sfc` is configured in passthrough (p0↔pf0hpf, p1↔pf1hpf) on both nodes; flow rules verified.

### 2. Cluster pod traffic is currently exiting via the **1 Gbps management** port

- `br-dpu` Linux bridge contains `enp129s0f0` (1 Gbps mgmt) **and** `enp14s0f0v0` (DPU VF representor).
- All remote-node MACs are learned in the bridge FDB on `enp129s0f0` (the 1 G port).
- `tcpdump` on each member during a benchmark run captured: 5 of 5 cilium-VXLAN frames (UDP/8472) **on `enp129s0f0`**, **0 frames** on the DPU VF rep.
- iperf3 single-stream TCP cap-to-cap = ~0.96 Gbps, exactly line-rate of the 1 G mgmt link.

### 3. Both DPU `p0` ports reach the Cisco leaf — different SVIs

Solicited Router Advertisements (`rdisc6`) on each node's `enp14s0f0np0`:

| Node | RA source IPv6 LL | Source MAC | M flag | O flag | Prefix Info | Advertised MTU |
|---|---|---|---|---|---|---|
| gpu1 | `fe80::2d7:8fff:fe3e:3730` | `00:D7:8F:3E:36:DD` | No | No | none | 9216 |
| gpu2 | `fe80::2d7:8fff:fe3e:3738` | `00:D7:8F:3E:36:DD` | No | No | none | 9216 |

Same chassis MAC → same Cisco device (`custeng.leaf1.1` per CDP on gpu2 Eth1/25), different SVIs / VLANs. ICMPv6 to the gpu1-side Cisco LL gateway returns 5.7 ms RTT, confirming working L3 reachability over the 40G fabric.

CDP from gpu2's PF identified its switch port as `Ethernet1/25`. We did not capture CDP on gpu1's PF in repeated 60 s windows — the gpu1 port assignment is unknown to us.

### 4. No DHCP, no SLAAC, no DHCPv6

- gpu1's `enp14s0f0np0` is netplan-configured `dhcp4: true`. With 4 successive `DHCPDISCOVER`s captured outbound, **0 OFFERs** were captured inbound.
- After enabling `dhcp4: true` on gpu2 via netplan and restarting `systemd-networkd`, gpu2 also sent 5 `DHCPDISCOVER`s and received **0 OFFERs**.
- RA flags on both VLANs: `M=0, O=0`, no Prefix Information option → SLAAC and DHCPv6 are both unavailable for these segments.

### 5. The two host-PF segments are not L2-bridged to each other

Confirmed by adding test IPs `10.99.99.1/24` (gpu1) and `10.99.99.2/24` (gpu2) to the host PFs and watching simultaneous tcpdumps:

- gpu1 sent 10 ARP requests for 10.99.99.2 → captured outbound on gpu1 PF.
- gpu2 capture during the same window: **zero** ARP requests received.
- Reverse direction: gpu2 → gpu1 likewise saw no ARP responses.

This is expected and correct for the HBN/ECMP topology described in `TEST_CASES.md` — the underlay should be L3 routed by the leaf, not bridged.

---

## Why this matters

Without IP layer configuration on the 40G fabric:

- All cluster pod traffic falls back to the 1 Gbps mgmt link, which is bridged into `br-dpu` for L2 reachability between the two nodes.
- Single-stream TCP is hard-capped at ~960 Mbps and 8/16-stream is *worse* (host CPU OVS contention) — meaningless as a baseline.
- Even `dpf-ovn-accelerated` and `dpf-ovn-hbn` would show no DPU offload uplift because no traffic touches the DPU eswitch beyond the existing passthrough wire.

Fixing this is a precondition for any of the test cases in `TEST_CASES.md` to produce meaningful data.

---

## Recommended Fix (Tier 2: ECMP-ready static)

This is the minimum config that lets us produce a valid baseline + accelerated A/B and demonstrate ECMP behaviour, without requiring a leaf BGP rollout. We can move to Tier 3 (full HBN/BGP) when we cycle to TC3.

### Addressing plan (proposed — please adjust to your reserved space)

**Loopbacks (per node, advertised across both PFs):**

| Node | Loopback `/32` |
|---|---|
| gpu1 | `10.99.0.1/32` |
| gpu2 | `10.99.0.2/32` |

**Transit /30s (one per host-PF ↔ Cisco-SVI link):**

| Link | Host IP | Cisco SVI IP |
|---|---|---|
| gpu1 `enp14s0f0np0` ↔ Cisco SVI A | `10.99.10.1/30` | `10.99.10.2/30` |
| gpu1 `enp14s0f1np1` ↔ Cisco SVI B | `10.99.11.1/30` | `10.99.11.2/30` |
| gpu2 `enp14s0f0np0` ↔ Cisco SVI C | `10.99.12.1/30` | `10.99.12.2/30` |
| gpu2 `enp14s0f1np1` ↔ Cisco SVI D | `10.99.13.1/30` | `10.99.13.2/30` |

**Reserved blocks if you'd like to give us our own subnet:**

We need 6 small subnets total (4 transit /30 + 2 loopback /32). A single `/24` reservation is more than enough; e.g. `10.99.0.0/24` carved as:
- `10.99.0.0/29` — node loopbacks (uses .0/.1/.2)
- `10.99.10.0/24` — transit links

### Cisco leaf-side config (NX-OS, ~12 lines)

```nxos
! one SVI per VLAN, IPs per the table above (replace VLAN IDs with actual)
interface Vlan<A>
  ip address 10.99.10.2/30
  no shutdown

interface Vlan<B>
  ip address 10.99.11.2/30
  no shutdown

interface Vlan<C>
  ip address 10.99.12.2/30
  no shutdown

interface Vlan<D>
  ip address 10.99.13.2/30
  no shutdown

! ECMP routes to each node's loopback via both of its PFs
ip route 10.99.0.1/32 10.99.10.1
ip route 10.99.0.1/32 10.99.11.1
ip route 10.99.0.2/32 10.99.12.1
ip route 10.99.0.2/32 10.99.13.1
```

NX-OS does ECMP automatically when multiple equal-cost statics share a destination, so no extra knobs needed.

### Host-side config (we'll handle this once you confirm)

We will:
1. Add a netplan addon (committed to the cluster profile) writing the static IPs above onto `enp14s0f0np0` / `enp14s0f1np1` and creating the loopback `/32`.
2. Add static routes on each host: peer's loopback via *both* local PFs (so the host also ECMPs outbound).
3. Move Cilium's tunnel endpoint to the loopback IP so VXLAN encap naturally lands on the 40G fabric.
4. Pull `enp129s0f0` out of `br-dpu` so 1G mgmt is reserved for OOB only (kubelet/Palette agent), and cluster pod traffic can no longer accidentally exit there.

---

## Tier 3 (HBN): defer, but plan for it

When we run `dpf-ovn-hbn` (TC3 / TC4), each DPU will run FRR/BIRD inside the DOCA HBN container and peer BGP with the leaf from each PF. The BGP config we'll need at that point:

| Peer | Local ASN | Remote ASN | Advertised |
|---|---|---|---|
| gpu1 DPU ↔ Cisco (SVI A) | 65001 | 65000 | `10.99.0.1/32`, `100.64.0.0/24` |
| gpu1 DPU ↔ Cisco (SVI B) | 65001 | 65000 | same |
| gpu2 DPU ↔ Cisco (SVI C) | 65002 | 65000 | `10.99.0.2/32`, `100.64.1.0/24` |
| gpu2 DPU ↔ Cisco (SVI D) | 65002 | 65000 | same |

ASNs above are placeholders — please assign from your reserved private-AS range. At Tier 3 the four static `ip route 10.99.0.x/32 ...` lines from Tier 2 should be removed.

---

## What we need from you

1. **Port mapping** — gpu1 PF0, gpu1 PF1, gpu2 PF0 (already known: `Eth1/25`), gpu2 PF1 → which leaf ports / which VLANs.
2. **Confirm or substitute IPv4 addressing** in the table above. If the existing `172.16.98.0/24` (the Cisco mgmt subnet) is the reserved underlay range, tell us how you'd like the four /30s carved.
3. **Apply the leaf-side static config** (the ~12 NX-OS lines above with VLAN IDs filled in).
4. **Confirm the leaf has ECMP enabled** for IPv4 (`maximum-paths` or NX-OS default). On NX-OS this is on by default but worth a quick check.
5. **For Tier 3**: assign two private ASNs for the DPUs (`65001`/`65002` proposed) and one for the leaf side, and either pre-configure BGP peers or schedule a window.

After you confirm (1)–(4) we'll apply the host-side change, validate end-to-end with iperf3 (target: ≥35 Gb/s per stream after offload, multi-stream ECMP saturation across both PFs), and report.

---

## Validation plan after fix

We will run, in order:

```
# 1. L3 reachability
ping -c 5 10.99.0.2 -I 10.99.0.1               # gpu1 → gpu2 loopback
ping -c 5 10.99.10.2 -I 10.99.10.1             # gpu1 → Cisco SVI A
ping -c 5 10.99.11.2 -I 10.99.11.1             # gpu1 → Cisco SVI B
# repeat from gpu2 with its addresses

# 2. ECMP path coverage (should show packets on both PFs)
ip -s link show enp14s0f0np0                   # before
ip -s link show enp14s0f1np1                   # before
iperf3 -c 10.99.0.2 -P 16 -t 30                # multi-flow
ip -s link show enp14s0f0np0                   # after — TX should have grown
ip -s link show enp14s0f1np1                   # after — TX should have grown too

# 3. DPU offload counters (DPU-side, via kubectl debug)
ovs-vsctl get Interface p0 statistics          # rx_packets, tx_packets should track iperf3 throughput

# 4. End-to-end pod-to-pod via Cilium tunnel
kubectl exec -n bench iperf3-client -- iperf3 -c <iperf3-server-pod-ip> -P 16 -t 60 --json
```

We expect single-stream ≈ 25–35 Gb/s, 16-stream ≈ saturating both 40 G uplinks (≈ 75 Gb/s aggregate via ECMP) for the `dpf-ovn-baseline` cluster, and significantly higher cap with lower CPU on `dpf-ovn-accelerated`.
