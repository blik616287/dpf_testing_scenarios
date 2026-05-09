# DPF passthrough fabric — switch-port investigation request

## TL;DR

Two NVIDIA BlueField-3 DPUs (gpu1, gpu2) are deployed in DPF Zero Trust passthrough mode. Each DPU has a 200GbE port (`p0`) connected to the fabric switch on VLAN `dpf-dummy-fabric` (untagged, subnet `172.16.97.0/24`).

Configuration matches NVIDIA's canonical reference (DOCA Platform Framework v25.10.1 ZT passthrough use case), and on-DPU diagnostics confirm OVS/eswitch are forwarding correctly. **Frames egress one DPU's `p0` port but never arrive at the other DPU's `p0` port — even when the source MAC is the DPU's own MAC** (the one the switch learned at link-establishment time). The fabric switch is not bridging the two ports.

We need the switch-side L2 forwarding domain verified.

---

## What we definitively confirmed

### A. The DPUs are forwarding correctly

- DPF v25.10.1 with the canonical `passthrough` DPUFlavor + DPUServiceChain (`p0 ↔ pf0hpf`, `p1 ↔ pf1hpf`)
- sfc-controller installed all four canonical learning flows on `br-sfc` of each DPU
- Both `p0` ports show `Speed: 40000Mb/s, Link detected: yes`
- OVS interface MACs match kernel representor MACs (correct binding)
- No drops counted at OVS pipeline level; no eswitch errors

### B. Frames physically egress gpu1's `p0`, do not arrive at gpu2's `p0`

Test using the canonical reference (host PF MAC):
```
gpu1 host PF0 sends 5 ARPs for 172.16.97.11
→ gpu1 DPU pf0hpf rep:  RX +N        (host→DPU side OK)
→ gpu1 DPU p0 (egress): TX +1        ✓ frame on the wire
→ gpu2 DPU p0 (ingress): RX +0       ✗ frame did not arrive
→ tcpdump on gpu2 host PF0 in promisc with `ether src c4:70:bd:2b:f6:92 or arp`: 0 packets captured
```

### C. Even with src MAC rewritten to the DPU's own `p0` MAC, frames still don't cross

Repeat of the test with an OVS flow that rewrites source MAC on egress to be `c4:70:bd:2b:f6:a2` (gpu1 DPU `p0`'s own MAC — the one the switch learned at link-up):
```
gpu1 p0 TX:  18 → 19   (+1 frame egressed with src MAC = DPU's own p0 MAC)
gpu2 p0 RX:  86 → 86   (delta 0, no arrival)
```

This rules out:
- Port security / MAC limit / MAC sticky (would have allowed the DPU's own MAC)
- DHCP snooping / DAI (we sent ARP from the "expected" MAC)

The remaining explanations are at a more fundamental level than per-MAC filtering — the switch is just not bridging these two ports together.

### D. PHY-level counters confirm: frames never reach gpu2's NIC at all

Captured `ethtool -S p0` (PHY-level counters from the MAC controller, below all OVS/eswitch abstractions) before and after a 5-ping test:

```
gpu1 p0:  tx_packets_phy   199 → 206   (+7 frames physically on the wire)
          tx_broadcast_phy  43 → 49    (+6 broadcasts — the 5 ARPs)
          tx_discards_phy   0          (NIC did not drop anything)

gpu2 p0:  ALL COUNTERS UNCHANGED        (0 frames arrived at the NIC)
          rx_discards_phy   0          (NIC did not drop anything either)
```

Frames left gpu1's MAC layer cleanly. Zero of them reached gpu2's MAC layer. Not silent NIC drops on either end — the wire/switch path between them is the loss point.

### E. Neither DPU has *ever* received a broadcast on this VLAN

```
gpu1 p0 rx_broadcast_phy: 0   (in the entire lifetime of the link)
gpu2 p0 rx_broadcast_phy: 0
```

`rx_multicast_phy` on both is non-zero (~227+) — so they each receive routine multicast (LLDP from upstream switches, IPv6 link-local, etc.). But neither has ever seen a broadcast frame, in either direction. Real VLANs always have some broadcast traffic — ARP requests from other hosts, switch BPDUs, gratuitous ARPs. **Both DPU ports being entirely broadcast-isolated is the strongest evidence yet that the switch is not actually bridging these two ports together** despite the VLAN name being the same.

---

## Architecture context (so the cause is unambiguous)

In **DPF Zero Trust passthrough mode**, the BlueField-3 DPU is wired between the host and the fabric. Workload traffic from the host's PF interface enters the DPU over PCIe, traverses an OVS-DOCA chain (`pf0hpf ↔ p0`), and egresses on the DPU's `p0` 200GbE port. In the **default** passthrough config, the original host PF source MAC is preserved (no rewrite); in our test (B above) we additionally tried with src MAC rewritten to the DPU's own `p0` MAC. Both fail to cross the switch.

| Switch port | Connected to | DPU `p0` MAC (link-up time) | Host PF MAC (would appear in passthrough mode) |
|---|---|---|---|
| port-A (gpu1's 200G link) | DPU `p0` on gpu1 | `c4:70:bd:2b:f6:a2` | `c4:70:bd:2b:f6:92` |
| port-B (gpu2's 200G link) | DPU `p0` on gpu2 | `c4:70:bd:f0:65:d6` | `c4:70:bd:f0:65:c6` |

VLAN: `dpf-dummy-fabric` (untagged), subnet `172.16.97.0/24`, no DHCP.

---

## Most likely switch-side causes (in order of fit to evidence)

The disproof of port-security via test C means the issue is broader than per-MAC filtering. Likely candidates:

1. **The two ports are not actually in the same broadcast domain.** Possible reasons:
    - Trunk vs access mismatch — one or both ports might be trunked with PVID different from `dpf-dummy-fabric`, so untagged frames land in a different VLAN.
    - The two ports are members of different VLANs that happen to share the name `dpf-dummy-fabric` on different switches in a stack (some configs allow this but treat them as different VLANs at the stack level).
    - Port-VLAN-binding correctly configured but VLAN itself is not provisioned on a transit link / not in the spanning-tree forwarding state for both ports.
    - PVLAN (private VLAN) — both ports as isolated/community ports that can talk to a promiscuous port but not to each other.

2. **VRF / L3 segregation.** If the two ports' VLAN ends up on different VRFs and there's no inter-VRF L2 (which there usually isn't), unicast wouldn't cross.

3. **ACL / Layer 2 firewall** at the switch level blocking traffic between these two ports.

4. **Storm control / broadcast suppression** so aggressive that ARP broadcasts are dropped (would show as policer drops in switch counters).

5. **Spanning-tree state** — one or both ports in BLOCKING/LISTENING for the VLAN.

---

## Specific actions requested

For the two switch ports connected to gpu1 and gpu2's 200GbE DPU links:

### 1. Verify they're in the same broadcast domain
```
show vlan id <vlan-of-dpf-dummy-fabric>
show interfaces status | include <port-A>|<port-B>
show interfaces switchport <port-A>
show interfaces switchport <port-B>
show spanning-tree vlan <vlan-id> | include <port-A>|<port-B>
```
The two ports should both appear as **active members of the same VLAN ID** with **forwarding** STP state.

### 2. Check MAC table — does the switch see traffic from each port reach the other?
After we send pings:
```
show mac address-table | include <port-A>|<port-B>
show mac address-table address c470.bd2b.f6a2
show mac address-table address c470.bdf0.65d6
```
The DPU `p0` MAC for one side should appear *learned on the other side's port* if frames are crossing.

### 3. Inspect for L2 isolation features
```
show interfaces switchport <port-A> | include "private-vlan|protected"
show vlan private-vlan
show etherchannel summary
show ip access-lists | include <vlan-id>
```

### 4. Confirm jumbo MTU end-to-end
DPU `p0` ports are at MTU 9216. Switch ports must support ≥9216 (some platforms require global `system mtu jumbo 9216`).

### 5. Switch logs / counter check
```
show logging | include err|drop|<port-A>|<port-B>
show interfaces <port-A> counters errors
show interfaces <port-B> counters errors
```

---

## Testing helpers — minimal commands the network team can use to verify the fix

After whatever switch-side change is made, on the deployment hosts:

```bash
# gpu1 (172.16.30.90):
sudo ip link set dev enp14s0f0np0 up
sudo ip addr replace 172.16.97.10/24 dev enp14s0f0np0
sudo ip neigh flush all
ping -c 3 172.16.97.11

# gpu2 (172.16.30.253):
sudo ip link set dev enp14s0f0np0 up
sudo ip addr replace 172.16.97.11/24 dev enp14s0f0np0
```

Expected: 3/3 replies.

If still failing, on each side:
```bash
sudo tcpdump -i enp14s0f0np0 -ne -p arp or icmp
```
We should see at minimum the ARP request egressing one host *and arriving* on the other — that's the L2 reachability test, independent of any IP/ARP higher-layer behavior.

---

## Why this can't be worked around in DPF/OVS

In passthrough mode the DPU is intentionally a transparent L2 bridge between the host PF and the 200GbE fabric. There's no encap, no MAC rewriting, no L3 — that's the whole point. Any fix has to be at the switch.

(In contrast, the *accelerated* and *HBN* DPF modes encapsulate workload traffic with the DPU's own MAC as the outer source — those would be unaffected by per-MAC filtering, but as confirmed by test C above, this specific lab's fabric doesn't seem to be a per-MAC filter issue anyway. So fixing the switch is needed regardless of which DPF mode we benchmark.)

---

## Local diagnostic data we have, in case useful

- DPF version: v25.10.1 (canonical ZT passthrough use case)
- BFB: `bf-bundle-3.2.1-34_25.11_ubuntu-24.04_64k_prod.bfb` (DOCA 3.2.1)
- BlueField-3: B3220 P-Series FHHL DPU, PCIe Gen5 x16
- DPUFlavor: stock NVIDIA `passthrough` (LAG_RESOURCE_ALLOCATION=1, ENABLE_ESWITCH_MULTIPORT=yes, OVS-DOCA on br-sfc with `p0↔pf0hpf` and `p1↔pf1hpf` chains, all `Ready: True`)
- DPUs `Ready` in DPF, sfc-controller installed all 4 canonical learning flows on `br-sfc` of each DPU
