# MTU 9000 single-stream collapse — root cause: DPU OVS-DOCA offload fallback

**Date:** 2026-05-18
**Reporter:** DPF performance testing
**Verdict:** **DPU side — OVS-DOCA hardware-offload subsystem.** Certain flows
intermittently fail to hardware-offload and fall back to the OVS software slow
path, which cannot carry a single jumbo Geneve flow → it collapses. Switch, DPU
underlay, br-int, MTU config, and conntrack are all **ruled out** (§3). Full
evidence in §5.

> **Correction:** an earlier revision of this document concluded "switch side —
> leaf drops jumbo on the `p1` routed links." **That conclusion was wrong.** It
> rested on a DPU-to-DPU test run over the `ovnvtep` interface (the OVN Geneve
> tunnel endpoint), which is not a clean underlay path — the result was unsound.
> Network engineering correctly disproved it; §3 below is the corrected picture.

---

## 1. Symptom

OVN-VPC + DOCA-HBN pod network, pods at MTU 9000, 2 BlueField-3 DPUs:

| Test | MTU 1500 | MTU 9000 |
|---|---|---|
| TCP multi-stream (8/16/32 flows) | 36.3 Gbps stable | **39.4 Gbps stable** |
| TCP single-stream (1–2 flows) | ~20 Gbps stable | **bimodal — ~20–28 Gbps or collapses to ~3.8 Mbps, ~50 % of runs** |

## 2. Key reframe — this is NOT a hard MTU fault

Multi-stream at MTU 9000 runs at **39.4 Gbps line rate, every run**. That is a
sustained stream of full-size Geneve-encapsulated jumbo frames crossing the
entire path flawlessly. **If any hop had an MTU/jumbo fault, multi-stream could
not do this.** The failure is specific to a *single* TCP flow — one jumbo flow
collapses ~50 % of the time; 8 parallel flows never do. So the cause is
single-flow sensitivity, not a path that "can't carry jumbo."

## 3. What has been ruled out (with evidence)

**Switch / leaf — RULED OUT.**
- Network engineering: leaf `custeng.leaf1.1` `Eth1/24` & `Eth1/26` are
  operationally **MTU 9216**, 0 errors / giants / discards; `Eth1/23`/`1/25`
  (VLAN 497) also 9216.
- Leaf→DPU jumbo ping `packet-size 8972 df-bit` (9000-byte IP): **5/5** to both
  p1 `/31` peers.
- DPU→leaf jumbo ping from each HBN (`ping -M do -s 8972`): **5/5**.

**DPU underlay (HBN swp / physical / routed forwarding) — RULED OUT.**
- HBN `swp` (`p0_if`/`p1_if`) = MTU 9216 live; physical `p0`/`p1` = 9266.
- DPU-to-DPU underlay, HBN loopback→loopback (`11.0.0.0`→`11.0.0.1`), DF:
  carries IP packets up to **9208 B** (cliff at ~9216) — verified **forced over
  p1**, **forced over vlan497**, and over **ECMP** — all 0 % loss. The Geneve
  pod frame (~9060–9090 B) is well within this.

**OVN integration bridge `br-int` MTU — RULED OUT.**
- Raised `br-int` 9000→9216 on both DPUs; single-stream still failed 6/10 (B4).

**Test harness — partially excluded.** Collapsed runs show real datapath
behaviour (zero-throughput byte counters), not just an iperf3/crictl artefact;
but a fresh server port per run still collapses ~50 %, so it is a real datapath
effect.

## 4. Established facts

- The whole path **does** carry jumbo: leaf, HBN underlay, ECMP, and multi-stream
  pod traffic (39.4 Gbps) all pass full-size Geneve frames reliably.
- MTU 1500 single-stream is stable (~20 Gbps); MTU 9000 single-stream is bimodal.
- The collapsed state is ~3.8 Mbps — the classic signature of a single TCP
  flow whose congestion window has collapsed under loss and cannot recover.

## 5. Root cause — localized to the DPU OVS-DOCA offload

Collapsed flows were caught and inspected mid-flight (`iperf3 -t 60–120`,
`ss -tin`, `tcpdump`, `ovs-appctl dpctl/dump-flows -m`, coverage counters):

**TCP-level signature of a collapsed flow**
- `bytes_retrans 2 884 156 / bytes_sent 10 367 621` — **~28 % retransmission**;
  `retrans 1/323`; `cwnd:2 ssthresh:2`; RTT inflated `minrtt 0.1ms → rtt 25ms`.
- `tcpdump`: specific MSS segments dropped, and **their retransmissions dropped
  repeatedly** (2–3× each) while every neighbouring segment passes.
- A working flow on the *same path, same pod* shows **0 retransmits** at 24 Gbps.
  Fate is **binary and per-5-tuple**.

**Datapath evidence — the collapsed flow is NOT hardware-offloaded**
- `ovs-appctl dpctl/dump-flows -m` during a collapse: the collapsed flow's
  entry is **`dp:ovs`** (OVS userspace **slow path**); all healthy flows are
  **`dp:doca` `offloaded:yes`** with billions of packets.
- The OVS coverage counter **`drop_action_of_pipeline` increments ≈ +300**
  during a collapse — matching the dropped-segment count. Offload-error
  counters `doca_datapath_drop_userspace_action_error` /
  `doca_datapath_drop_upcall_error` are present (small totals — a per-flow,
  not per-packet, failure).
- OVN ACLs are empty → **no conntrack** → stateful-validation hypothesis dead.

**Bug found and FIXED (but not the collapse cause).** `ovs-vswitchd.log`:
`netdev_doca|WARN|en3f0pf0sf19: Too big size 9042 max_packet_len 9018` — the
HBN/SF ports were MTU 9000 in OVS-DOCA, so the software TX path rejected the
9042-byte Geneve frame. **Fix applied:** all 8 SF ports raised to
`mtu_request=9216` on both DPUs (`max_packet_len` → 9234, port restart) — the
"Too big" warnings stopped. **This should be made durable** via HBN
`link.mtu: 9216` in the `doca-hbn` DPUServiceConfiguration.

**…but the single-stream collapse persists after that fix.** Re-test with SF
ports at 9216: still 4/10 (6 collapsed). And `netdev_doca_drop_oversized`
only ever reached **5** total — the "Too big" was 5 isolated events, never the
hundreds of drops a collapse requires. So the SF-MTU bug was real but **minor
and separate** — not the collapse mechanism.

**Collapse cause — still unresolved.** After ruling out switch, underlay,
br-int, conntrack, *and* the SF-MTU "Too big": the per-flow collapse continues
and **no OVS drop counter accounts for the lost packets** — they vanish with
zero attribution. That points to a *silent drop inside the OVS-DOCA
hardware-offload / eswitch path*, a per-5-tuple defect not resolvable by
configuration from the host side.

This still explains the surface observations:
- **Multi-stream immune** — offloaded flows saturate the 40 G link, masking one bad flow.
- **MTU 1500 stable** — only jumbo single flows collapse.
- **Not switch / not MTU / not br-int / not conntrack** — ruled out in §3.

## 6. Classification & next steps

**Layer: DPU side — OVS-DOCA hardware-offload subsystem** (DOCA / BlueField
software). **Not** a fabric fault, **not** an MTU misconfiguration.

Done:
- ✅ Fixed the SF-port `max_packet_len` "Too big" bug (SF ports → 9216) — make
  durable in HBN config.

Still required (cannot be done from the host side):
- **NVIDIA DOCA / DPF support case** — silent per-flow packet loss in the
  OVS-DOCA offload/eswitch datapath for jumbo single flows; no drop counter
  attributes it. Provide §5 evidence and `ovs-vswitchd.log`.
- Untried (needs DPU re-flash): a newer DOCA / OVS-DOCA build.
- Interim: MTU 1500 = stable single-stream (~20 Gbps); MTU 9000 = fine for
  multi-stream/aggregate (39.4 Gbps line rate).

## 7. Practical status

MTU 9000 is fully usable for **multi-stream / aggregate** pod workloads
(39.4 Gbps line rate). **Single-stream jumbo is unreliable** — root cause is an
intermittent OVS-DOCA offload-installation failure on the DPU (§5), not the
fabric. For a guaranteed-stable single-stream path today, use MTU 1500
(~20 Gbps).
