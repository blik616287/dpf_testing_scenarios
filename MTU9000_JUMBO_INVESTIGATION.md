# MTU 9000 Jumbo Failure — Root Cause: Switch Side (leaf `p1` routed links)

**Date:** 2026-05-18
**Reporter:** DPF performance testing
**Verdict:** **SWITCH SIDE** — the leaf drops jumbo frames on the `p1` routed
`/31` links. Software and DPU are exonerated by hard counter evidence.
**For:** network / fabric engineering — concrete fix in §5.

---

## 1. Symptom

OVN-VPC + DOCA-HBN pod network, pods at MTU 9000, on 2 BlueField-3 DPUs:

| Test | MTU 1500 | MTU 9000 |
|---|---|---|
| TCP multi-stream (8/16/32 flows) | 36.3 Gbps stable | 39.4 Gbps stable |
| TCP single-stream (1–2 flows) | ~20 Gbps stable | **collapses to ~3.8 Mbps on ~50–60 % of runs** |

## 2. Systematic isolation — software vs DPU vs switch

The HBN underlay has **two ECMP uplinks per DPU**: `p0` (VLAN 497 access,
leaf Eth1/23 & Eth1/25) and `p1` (routed `/31`, leaf Eth1/24 & Eth1/26). Each
flow's Geneve tunnel L4-hashes onto one uplink.

| # | Test | Result | Eliminates |
|---|---|---|---|
| B4 | Raise OVN `br-int` MTU 9000→9216, re-run single-stream | still 4/10 ok | **not** br-int / not a software MTU cap |
| — | MTU-1500 single-stream | stable | issue is jumbo-specific |
| B2/p0 | Single-stream forced over **p0** (VLAN 497) | **5/6 ok** (20–28 Gbps) | p0 path carries jumbo |
| B2/p1 | UDP jumbo forced over **p1**, with physical counters | **see §3 — ~100 % loss** | **isolates the fault to p1** |

**Arithmetic check:** p0 ≈ 83 % success, p1 ≈ 0 %. ECMP hashes single flows
~50/50 → predicted single-stream success ≈ 41 %. Observed (br-int test, n=10):
**40 %.** Multi-stream is immune because the p0-hashed streams alone saturate
the 40 G link, masking the p1 losses.

## 3. Proof — the fault is on the wire (switch), not the DPU

UDP, 8900-byte datagrams, DPU-to-DPU **forced over the `p1` routed path**, 15 s,
offered 3 Gbps. Physical-port packet counters captured on both DPUs:

```
iperf3 sender   : 631 989 datagrams sent
iperf3 receiver :     782 received,  629 523 lost   (~100 % loss)

gpu1  physical p1  tx_packets delta : 632 022     <-- DPU SENT the jumbo frames
gpu2  physical p1  rx_packets delta :     737     <-- DPU RECEIVED almost none
gpu1  p1  tx_discards_phy / tx_errors_phy : 0 / 0
gpu2  p1  rx_dropped / rx_errors          : 0 / 0
```

**~631 000 jumbo frames left gpu1's physical `p1` port and never arrived at
gpu2's physical `p1` port.** Both DPUs' NIC counters are completely clean — the
DPUs transmit and would receive fine. The frames are dropped **in flight,
between the two physical ports — i.e. inside the leaf switch.**

Control: the same DPU-to-DPU jumbo over **p0** (VLAN 497) and the full pod
multi-stream test run at 39.4 Gbps line rate — the leaf carries jumbo on the
VLAN 497 ports. Small packets (BGP, ping) cross `p1` fine — `p1` BGP is
Established with 126 prefixes. So `p1` passes small frames, drops large ones:
a classic **interface-MTU drop on the routed links**.

## 4. Conclusion — layer determination

- **Software — ruled out.** Raising OVN `br-int` to 9216 did not help (B4);
  MTU 1500 is stable; the failure is purely jumbo-size dependent.
- **DPU — ruled out.** gpu1 transmits 632 022 jumbo frames out `p1` with
  **0** `tx_discards_phy`/`tx_errors_phy`; gpu2 shows **0** `rx_dropped`/
  `rx_errors`. Both BlueField dataplanes are clean. The p0 path through the
  identical DPU stack carries jumbo fine.
- **Switch — CONFIRMED.** Jumbo frames are dropped between the two DPUs'
  physical `p1` ports — on leaf `custeng.leaf1.1`, the routed `/31` links
  **Eth1/24** (gpu1 `p1`) and **Eth1/26** (gpu2 `p1`).

## 5. Fix — for network engineering

On `custeng.leaf1.1` (Cisco Nexus, NX-OS 9.3(11)), the routed `/31` interfaces
carrying the `p1` HBN path are not passing jumbo. NX-OS L3/routed-interface MTU
is **per-interface and defaults to 1500** — it is not covered by
`system jumbomtu` (that applies to L2 switchports only, which is why the VLAN
497 ports Eth1/23/25 already carry jumbo).

```
interface Ethernet1/24      ! gpu1 p1  (172.16.97.248/31)
  mtu 9216
interface Ethernet1/26      ! gpu2 p1  (172.16.97.250/31)
  mtu 9216
```

Verify:
```
show interface Ethernet1/24 | include MTU       ! expect 9216
show interface Ethernet1/26 | include MTU
show interface Ethernet1/24 counters errors     ! giants / input errs should clear
show interface Ethernet1/26 counters errors
```
(For reference, Eth1/23 and Eth1/25 — the working VLAN 497 path — should already
read 9216 / system-jumbo; please report their MTU so the delta is confirmed.)

### 5a. Secondary item (DPU-side config, already worked around)

For a *permanent* MTU-9000 pod deployment there is also a DPU-side prerequisite:
HBN's `swp` interfaces (`p0_if`/`p1_if`/`pf0hpf_if`) are pinned to `link.mtu:
9000` in the `doca-hbn` `DPUServiceConfiguration`, but a 9000-MTU pod frame +
Geneve is ~9058 B. These were raised to 9216 transiently for this investigation;
to make it durable, change `link.mtu: 9000 → 9216` in
`hbn-deploy-tc4/manifests/01-hbn-bundle.yaml`. This is *not* the cause of the
single-stream collapse (the leaf is — §3/§4), but it must be fixed too or the
leaf fix alone will not give a clean MTU-9000 pod path.

## 6. Commands — verify the finding, make the fix, validate

Topology recap: leaf `Eth1/24` ↔ gpu1 `p1` (`172.16.97.248/31` ↔ `.249`);
leaf `Eth1/26` ↔ gpu2 `p1` (`172.16.97.250/31` ↔ `.251`); `Eth1/23`/`Eth1/25`
= VLAN 497 access ports (the working control path). DPU login:
`ssh ubuntu@172.16.30.29` (gpu1) / `172.16.30.30` (gpu2), pw `Welcome2spectr0!`.

### 6.1 Verify the finding

**Leaf-side** — on `custeng.leaf1.1` (NX-OS). Add `vrf <name>` to the pings if
the `/31`s are in a VRF.
```
show interface Ethernet1/23-26 | include "Ethernet1/|MTU"   ! compare 23/25 vs 24/26
! jumbo ping across each directly-connected /31 (DF set, 9000-byte packet):
ping 172.16.97.249 count 5 packet-size 9000 df-bit          ! gpu1 p1 -> EXPECT ~100% loss
ping 172.16.97.251 count 5 packet-size 9000 df-bit          ! gpu2 p1 -> EXPECT ~100% loss
ping 172.16.97.249 count 5 packet-size 500  df-bit          ! control -> succeeds
show interface Ethernet1/24 counters errors                 ! input errors / giants
show interface Ethernet1/26 counters errors
```

**DPU-side** — jumbo ping from each DPU to its directly-attached leaf `/31`
(one hop, no OVN/HBN routing involved). On gpu1 (peer `.248`), gpu2 uses `.250`:
```
HBN=$(sudo crictl ps -o json | python3 -c 'import json,sys;[print(c["id"]) for c in json.load(sys.stdin)["containers"] if c["metadata"]["name"]=="doca-hbn"]' | head -1)
sudo crictl exec $HBN ping -c3 -M do -s 1000 172.16.97.248     # control, small  -> 0% loss
sudo crictl exec $HBN ping -c5 -M do -s 8972 172.16.97.248     # 9000-B packet   -> EXPECT 100% loss
```

**DPU-side counter proof** (reproduces §3 — sustained jumbo, both physical
ports counted). On gpu1:
```
# force the underlay route over p1 only:
sudo crictl exec $HBN vtysh -c 'conf t' -c 'router bgp 65010' -c 'neighbor 172.16.97.125 shutdown'
# snapshot counters: gpu1 ->  cat /sys/class/net/p1/statistics/tx_packets
#                    gpu2 ->  cat /sys/class/net/p1/statistics/rx_packets  (and rx_dropped, rx_errors)
sudo iperf3 -c 10.0.120.10 -B 10.0.120.2 -u -b 3G -l 8900 -t 15   # jumbo UDP, gpu2 runs `iperf3 -s -B 10.0.120.10`
# re-snapshot; expect gpu1 tx delta ~600k, gpu2 rx delta ~0, both rx_dropped/tx_errors = 0
# restore:
sudo crictl exec $HBN vtysh -c 'conf t' -c 'router bgp 65010' -c 'no neighbor 172.16.97.125 shutdown'
```

### 6.2 Make the fix (leaf `custeng.leaf1.1`)
```
configure terminal
 interface Ethernet1/24
   mtu 9216
 interface Ethernet1/26
   mtu 9216
end
copy running-config startup-config
```

### 6.3 Validate the fix
```
# leaf — jumbo ping now succeeds, 0% loss:
ping 172.16.97.249 count 5 packet-size 9000 df-bit
ping 172.16.97.251 count 5 packet-size 9000 df-bit
show interface Ethernet1/24 | include MTU            ! 9216
# DPU — jumbo ping to leaf /31 succeeds:
sudo crictl exec $HBN ping -c5 -M do -s 8972 172.16.97.248
# DPU — re-run the §6.1 counter proof: gpu1 p1 tx delta  ==  gpu2 p1 rx delta, iperf3 ~0% loss
```
End-to-end: pod single-stream at MTU 9000 stops collapsing (no ~3.8 Mbps runs);
the TC4 matrix can then be re-run cleanly at jumbo.

---

**Bottom line:** not software, not the DPU — the leaf switch drops jumbo on the
`p1` routed `/31` links (Eth1/24, Eth1/26). Set those two interfaces to
`mtu 9216`. Evidence: 632 022 jumbo frames transmitted by the DPU, 737 received
by the peer DPU, zero NIC drops on either side.
