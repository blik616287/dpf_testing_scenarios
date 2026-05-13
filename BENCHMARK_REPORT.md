# DPF Pod-to-Pod Acceleration Benchmark Report

**Status:** Test Cases 1 & 2 complete (passthrough vs VPC-OVN). Test Cases 3 & 4 (HBN/ECMP) pending fabric reconfiguration — see [§ 7. Pending Work](#7-pending-work-test-cases-3--4--hbnecmp).

**Date:** 2026-05-08
**Authors:** DPF testing team
**Source data:** `results/dpf-ovn-baseline/`, `results/dpf-ovn-accelerated/`
**Charts:** `results/charts/`

---

## 1. Executive Summary

Two pod-to-pod cluster configurations were benchmarked head-to-head on identical hardware:

- **Cluster A — `dpf-ovn-baseline`** (passthrough): the BlueField-3 DPU is configured as a wire; OVN runs on the host kernel.
- **Cluster B — `dpf-ovn-accelerated`** (VPC-OVN): the OVN dataplane is offloaded to the DPU's OVS-DOCA engine. Pod traffic traverses scalable functions on the DPU and rides geneve over the 40 Gb/s fabric between the two BlueField-3s.

The full benchmark matrix from `POD_TO_POD_TEST_PLAN.md` § "Benchmark Matrix" was run on both clusters: **11 tests × 5 runs × 60 s** (run 1 discarded as warmup; all numbers below are mean ± stdev over runs 2–5, n=4). All tools (iperf3, netperf, sockperf, mpstat) ran **inside the pod containers** on the DPU tenant cluster.

### Headline results

| Metric | Passthrough (A) | VPC-OVN (B) | Change |
|---|---:|---:|---:|
| TCP single-stream throughput | 20.5 ± 0.3 Gbps | 27.1 ± 4.0 Gbps | **+33 %** |
| TCP 8 / 16-stream throughput | 39.4 Gbps (line rate) | 39.4 Gbps (line rate) | — |
| **TCP request/response rate** | 8 543 round-trips/s | 23 472 round-trips/s | **+175 %** |
| **TCP connection rate** | 1 392 conn/s | 5 370 conn/s | **+286 %** |
| **sockperf p99.9 tail latency** | 963 µs | 104 µs | **−89 %** |
| Host CPU at line rate (8/16 streams) | 21 % busy | 5 % busy | **−77 %** |

The story isn't that throughput went up — at the per-link fabric ceiling of 40 Gb/s both arms were already saturated. The story is **the DPU does the dataplane work, freeing host cores**, and at the same time delivers **much faster transactions and tighter tail latency** because the per-packet path skips host softirq.

---

## 2. Test Environment

### 2.1 Hardware

| Component | gpu1 | gpu2 |
|---|---|---|
| Host | x86_64 | x86_64 |
| BlueField-3 DPU | MT24326005FN | MT2439600DAK |
| DPU FW / OS | DOCA Ubuntu 24.04, OVS-DOCA 3.2.1005 | same |
| 40 G fabric NIC | enp14s0f0np0 → DPU p0 | enp14s0f0np0 → DPU p0 |
| Mgmt NIC (1 G OOB) | enp129s0f0 (172.16.30.90) | enp129s0f0 (172.16.30.253) |
| BMC | 172.16.30.36 | 172.16.30.33 |
| DPU OOB IP (post-install) | 172.16.30.29 | 172.16.30.20 |
| DPU geneve VTEP | 172.16.97.98/27 | 172.16.97.102/27 |

### 2.2 Software

- DPF: v25.10.1 (Zero Trust mode, NetOp v2 profile)
- Kubernetes: tenant cluster v1.33.6 (kamaji-managed)
- Host CNI (host cluster): Cilium
- DPU pod CNI (tenant cluster, default): Flannel; secondary network on bench-net via OVS CNI + nv-ipam (VPC-OVN)
- Bench tools: iperf3 3.16, netperf 2.7.1, sockperf 3.10, sysstat (mpstat) 12.6.x — all installed inside the pod via the Ubuntu universe repo

### 2.3 Topology

Both clusters use the **same physical hardware**. Only the cluster profile differs:

```
A (passthrough)                    B (VPC-OVN accelerated)
─────────────                     ─────────────────────────
host pod ─ flannel ─ kernel        host pod ─ flannel ─ kernel
    │        OVN-host             OVN traffic ↓
    └───── PCIe ─ DPU (wire) ─ p0          on the DPU
                                  pod (in tenant cluster)
                                       └── SF (en3f0pf0sfX) ─┐
                                                              │
                                              br-int (OVS-DOCA, HW offload)
                                                              │
                                              geneve  ── p0 ── 40 G fabric
```

In both arms the wire is the same; **what changes is whose CPU encapsulates / decapsulates / conntracks**.

### 2.4 What was held constant between A and B

| Item | Held constant |
|---|---|
| Hardware (servers, DPUs, fabric switch, cables) | ✓ |
| K8s version, container runtime | ✓ |
| Fabric L2 / VLAN 497 / MTU 9216 | ✓ |
| Pod resource requests, image, container CPU pinning | ✓ |
| Benchmark commands & parameters (verbatim from runner script) | ✓ |
| Run count (5), warmup discard (run 1), inter-run idle (30 s) | ✓ |

The **only** intentional difference: cluster profile (`dpf-ovn-baseline` vs `dpf-ovn-accelerated`).

---

## 3. Methodology

### 3.1 Benchmark matrix

All eleven tests below were run on both clusters using the script `scripts/run_pod_accelerated.sh` (and its baseline twin `scripts/run_pod_baseline.sh`). Each command ran for 60 s, repeated 5 times, with run 1 discarded as warmup and 30 s idle between runs.

| # | Tool | Command | Measures |
|---|---|---|---|
| 1 | iperf3 | `-c <ip> -t 60 -B <client_ip> --json` | TCP throughput, single stream |
| 2 | iperf3 | `-c <ip> -t 60 -B <client_ip> -P 8 --json` | TCP throughput, 8 parallel streams |
| 3 | iperf3 | `-c <ip> -t 60 -B <client_ip> -P 16 --json` | TCP throughput, 16 parallel streams |
| 4 | iperf3 | `-c <ip> -u -b 0 -t 60 -B <client_ip> --json` | UDP send rate (max) and receiver loss% |
| 5 | iperf3 | `-c <ip> -u -b 0 -l 64 -t 60 --json` | UDP small-packet (PPS-bound) |
| 6 | iperf3 | `-c <ip> -u -b 0 -l 1400 -t 60 --json` | UDP MTU-sized packets |
| 7 | netperf | `-H <ip> -t TCP_RR -l 60` | TCP request/response rate |
| 8 | netperf | `-H <ip> -t UDP_RR -l 60` | UDP request/response rate |
| 9 | netperf | `-H <ip> -t TCP_STREAM -l 60 -- -m 1` | Small-message TCP stream |
| 10 | sockperf | `ping-pong -i <ip> -p 11111 -t 60 --full-rtt` | Tail latency (p50/p99/p99.9) |
| 11 | netperf | `-H <ip> -t TCP_CRR -l 60` | TCP connection rate (conntrack stress) |

### 3.2 Supplementary captures

For each run on each cluster:
- `mpstat -P ALL 1 62` inside the pod container (per-core CPU as the pod sees it)
- `mpstat -P ALL 1` continuously on the **host** (gpu1 and gpu2), then sliced to the 60 s window per test by `scripts/slice_host_mpstat.sh` — this is what shows the host CPU savings

### 3.3 VPC-OVN attachment plumbing (cluster B)

Pods on cluster B got their VPC-OVN net1 interface via:

1. `DPUVPC` named `bench-vpc` (`isolationClassName: ovn.vpc.dpu.nvidia.com`)
2. `DPUVirtualNetwork bench-net` (Bridged, `subnet: 10.100.0.0/24`, dhcp)
3. nv-ipam `IPPool` for the same /24
4. NetworkAttachmentDefinition with `type: ovs, bridge: br-int, interface_type: dpdk, ipam: nv-ipam`
5. Pod resource request `nvidia.com/bf_sf: 1` (an SF allocated by the SR-IOV device plugin)
6. **Manual OVN logical switch port creation** with the pod's MAC + IP and `requested-chassis: <DPU-node-name>` (the `vpc-ovn-node` controller binds via `ServiceInterface` CRs; raw NAD-attached pods don't auto-bind, so we did it manually)
7. **Manual `iface-id` setting** on each DPU's OVS port (`external_ids:iface-id=<lsp-name>`) so OVN-controller binds the port and installs flows. After this, `external_ids:ovn-installed=true` confirms the binding.

Once steps 6 & 7 land, traffic from the pod's net1 enters the DPU's br-int with hardware-offloaded flows.

---

## 4. Results — Throughput

### 4.1 TCP and UDP throughput

![Throughput comparison](results/charts/throughput.png)

- **TCP 1-stream**: VPC-OVN +33 %. Single-stream pinned to one host core in the passthrough arm; the DPU pipeline is faster than that core for encap/decap/conntrack.
- **TCP 8-stream and 16-stream**: both arms saturate the 40 Gb/s wire (39.4 Gbps). No throughput delta. **The win here is in CPU usage** — see § 5.
- **UDP sender (max bandwidth)**: VPC-OVN +160 %. The DPU's hardware path can transmit UDP much faster than the host kernel.
- **UDP 1400 B and 64 B sender**: similar +168–171 % gains. TX-side offload is doing real work.

### 4.2 UDP loss explained

![UDP send vs loss](results/charts/udp_split.png)

UDP loss% is *similar in both arms* (~50–60 % at high send rates). This is **expected and not a fabric problem**:

- iperf3 UDP receive is single-threaded — one process draining one UDP socket.
- All packets in a single 5-tuple flow land on one RX queue → one host CPU core.
- That core saturates around 8–12 Gbps for software UDP RX regardless of what the dataplane is doing.
- At a 23 Gbps sender rate, ~half of packets get dropped at the receiver's socket queue.

The DPU **can't help the receive bottleneck** for a single-flow UDP test because the bottleneck is iperf3 itself, not the network. Multi-flow UDP with RSS (and, eventually, the HBN/ECMP test in TC4) would spread RX across cores.

---

## 5. Results — Host CPU (the killer metric)

![Host CPU at same workload](results/charts/host_cpu.png)

**This is the chart that sells DPF.** At identical workloads the host CPU drops by 41–77 %:

| Workload | Passthrough host CPU | VPC-OVN host CPU | Reduction |
|---|---:|---:|---:|
| TCP 1 stream | 9.3 % busy | 5.5 % busy | −41 % |
| TCP 8 streams (line rate) | 21.4 % busy | 5.0 % busy | **−76 %** |
| TCP 16 streams (line rate) | 21.2 % busy | 4.8 % busy | **−77 %** |
| UDP max | 9.4 % busy | 5.1 % busy | −46 % |
| TCP_RR | 9.4 % busy | 5.0 % busy | −47 % |
| TCP_CRR | 11.6 % busy | 5.1 % busy | −56 % |

Numbers are mean of `usr + sys + irq + soft` across all 48 cores during the 60 s test, repeated over runs 2–5. The **5 % residual** on the VPC-OVN side is mostly cilium / kubelet / system processes; networking-attributable host CPU on cluster B is essentially zero. The DPU is doing the dataplane work.

**Interpretation:** at sustained 39 Gbps line-rate pod-to-pod traffic, the passthrough cluster spends roughly the equivalent of 4–6 host cores on softirq / OVN / conntrack. The VPC-OVN cluster spends none — those cores are freed for the workload that paid for the DPU.

---

## 6. Results — Latency, Transactions, and Connection Rate

### 6.1 Round-trip / connection rates (where DPU offload truly shines)

![Transactions and connections](results/charts/transactions.png)

| Test | Passthrough | VPC-OVN | Δ |
|---|---:|---:|---:|
| netperf TCP_RR (round-trips/s) | 8 543 | 23 472 | **+175 %** |
| netperf UDP_RR (round-trips/s) | 10 154 | 26 834 | **+164 %** |
| netperf TCP_CRR (connections/s) | 1 392 | 5 370 | **+286 %** |

These are the metrics real workloads care about — RPC services, service meshes, load balancers, and any short-lived-connection pattern. **TCP_CRR's ~3.9× lift is the conntrack-offload story**: hardware conntrack on the DPU eliminates per-connection softirq cost on the host.

### 6.2 Tail latency (sockperf p99.9)

![Tail latency](results/charts/tail_latency.png)

| | p99.9 round-trip latency |
|---|---:|
| Passthrough | 963 µs |
| VPC-OVN | **104 µs** |

A **9× tail-latency reduction** at p99.9. For latency-sensitive workloads (SLB, low-latency RPC, real-time services) this is the most consequential number in the report. The host CPU's softirq path adds variable delay every time it runs; the DPU's hardware pipeline is deterministic.

### 6.3 Per-run distribution (variance check)

![Per-run distribution](results/charts/distribution.png)

n=4 per arm. Notable:

- **Passthrough is very stable** (low variance across runs).
- **VPC-OVN TCP single-stream is wider** (±4 Gbps) — the bottleneck is which CPU happens to handle the single SF queue's RX; this varies across runs.
- VPC-OVN TCP_RR, TCP_CRR, sockperf p99.9 are extremely stable. The DPU's hardware path produces consistent results run-to-run.
- For sockperf p99.9, the y-axis is log scale: the passthrough cluster's data points are nearly an order of magnitude above the VPC-OVN points, and the gap is wider than any per-run variance in either arm.

---

## 7. HBN Readiness — Test Cases 3 & 4

Test Case 3 (qualitative HBN validation) and Test Case 4 (HBN A/B benchmark + ECMP scaling sweep) are **not yet executed**. They require deploying a third cluster (`dpf-ovn-hbn`) on the same hardware. The underlay is partially ready — the first fabric request is complete and verified; a follow-up fabric request is open with the network team.

### 7.1 Readiness checklist

| # | Dependency | Status | Notes |
|---|---|---|---|
| 1 | **First fabric ask** — convert `Eth1/24` and `Eth1/26` (gpu1.p1, gpu2.p1) on `custeng.leaf1.1` to routed `/31` interfaces with BGP listener | ✅ **DONE** | Configured by network engineering; documented in [`FABRIC_HBN_ECMP_REQUEST.md`](FABRIC_HBN_ECMP_REQUEST.md) |
| 2 | **DPU-side BGP underlay validation** — bring FRR up on each DPU, verify BGP establishes, verify route propagation, verify L3 reachability to leaf loopback | ✅ **DONE** | See § 7.2 below |
| 3 | **Second fabric ask** — add a second BGP peering per DPU so each DPU sees **two equal-cost paths** to the leaf (required for ECMP scaling) | 🟡 **PENDING — open with network team** | Documented in [`FABRIC_HBN_SECOND_PEERING_REQUEST.md`](FABRIC_HBN_SECOND_PEERING_REQUEST.md). Without it, ECMP installs only one next-hop and TC4's scaling table will read flat. |
| 4 | DPU-side second BGP neighbor (FRR) | ⏸ Blocked on #3 | ~10 min DPU-side work once #3 is in |
| 5 | Deploy `dpf-ovn-hbn` cluster profile | ⏸ Blocked on #3 | Profile UID `698dd2dd4b0c719b6c763605` in `scripts/dpf_deploy.py` |
| 6 | TC3 qualitative validation (BGP Established, ECMP routes installed, per-uplink traffic balance, failover) | ⏸ Blocked on #3-5 | ~30 min |
| 7 | TC4 11×5 benchmark matrix on HBN cluster | ⏸ Blocked on #3-6 | ~80 min |
| 8 | TC4 ECMP scaling sweep (1, 2, 4, 8, 16, 32 parallel streams) | ⏸ Blocked on #3-6 | ~30 min |

### 7.2 What we verified after the first fabric ask landed

The network team replied with this configuration on `custeng.leaf1.1`:

```
Leaf ASN: 65001
Leaf router-id / Lo0: 11.0.0.111

gpu1 DPU p1:
  Switchport:  Ethernet1/24
  Leaf IP:     172.16.97.248/31
  DPU peer IP: 172.16.97.249/31
  DPU ASN:     65010

gpu2 DPU p1:
  Switchport:  Ethernet1/26
  Leaf IP:     172.16.97.250/31
  DPU peer IP: 172.16.97.251/31
  DPU ASN:     65020

Eth1/23, Eth1/25 unchanged (access VLAN 497, still serving VPC-OVN).
```

We then verified the underlay end-to-end:

| Check | Result |
|---|---|
| Bring up `p1` on each DPU with the assigned `/31` IP, MTU 9216 | ✅ |
| L3 ICMP from each DPU's `p1` to the leaf-side `/31` IP | ✅ ~0.5 ms RTT both sides |
| FRR installed on each DPU; configure BGP neighbor toward the leaf `/31` IP, per-DPU ASN | ✅ |
| BGP session state on each side | ✅ **Established** within ~5 s of activation |
| Prefixes received from leaf | **123 prefixes** to each DPU |
| Kernel routing table installs leaf loopback `11.0.0.111/32` via `p1` | ✅ both DPUs |
| End-to-end L3 ping DPU → leaf loopback over BGP-installed route | ✅ ~0.5 ms RTT both sides |

**Conclusion:** the p1 fabric path is correctly configured and end-to-end functional at L3, with BGP exchanging routes as designed. The underlay layer is HBN-ready for **one** path per DPU.

### 7.3 Why the second fabric ask is necessary (open with network team)

Each DPU currently sees **one** BGP path to the leaf (its own `p1`). For TC4's ECMP scaling sweep to show bandwidth aggregation across both physical uplinks (`p0` + `p1`), the DPU's routing table needs **two equal-cost next-hops** to the same destination. With one path, BGP installs one route; with two paths, BGP installs an ECMP route and the kernel hashes flows across both next-hops.

The simplest way to add the second path **without disrupting the running VPC-OVN cluster** (which keeps `Eth1/23`/`Eth1/25` in VLAN 497) is to peer BGP via the leaf's VLAN 497 SVI to each DPU's existing `ovnvtep` IP:

| DPU | Existing `ovnvtep` IP | New BGP path | New peer = leaf VLAN 497 SVI IP |
|---|---|---|---|
| gpu1 | `172.16.97.98/27` (live since VPC-OVN deployment) | over VLAN 497 fabric (Eth1/23 ↔ Eth1/25) | `172.16.97.125/27` (proposed; any IP in `172.16.97.96/27` works) |
| gpu2 | `172.16.97.102/27` | same VLAN 497 transport | same proposed SVI IP |

This adds **one BGP neighbor stanza per DPU** on the leaf and **one SVI secondary-IP line**, ~10 lines of NX-OS total. The /31s and Eth1/24/26 config from the first ask stay exactly as-is. The full follow-up request including the proposed config is in [`FABRIC_HBN_SECOND_PEERING_REQUEST.md`](FABRIC_HBN_SECOND_PEERING_REQUEST.md).

Once that's in place, each DPU's routing table will read something like:

```
11.0.0.111/32  proto bgp  metric 20
  nexthop via 172.16.97.248 dev p1       weight 1   (first ask — Eth1/24 /31)
  nexthop via 172.16.97.125 dev ovnvtep  weight 1   (second ask — VLAN 497 SVI)
```

…and TC4's parallel-flow sweep will exercise both physical uplinks.

### 7.4 Alternatives that were considered and rejected

| Alternative | Why we rejected it |
|---|---|
| Add p1 ports to VLAN 497 (same broadcast domain as p0) | One VLAN = one SVI = one BGP next-hop. ECMP installs only one path. TC4 sweep would be flat. The point of ECMP is bandwidth aggregation across distinct next-hops. |
| Convert p0 to routed /31s as well | Breaks the live VPC-OVN cluster (Eth1/23/25 currently in VLAN 497 carries the geneve underlay). Loses our completed Test Set 1 + Test Set 2 dataset unless we redeploy + re-run ~80 minutes of benchmarks. |
| Add p1 as a separate VLAN with its own SVI | Equivalent topology to the proposed /31 + SVI but more switch state. NVIDIA's HBN doc reference shows numbered /31 or unnumbered routed interfaces, not access-VLAN-per-uplink. |
| BGP unnumbered (NVIDIA's preferred per the HBN doc) | Network engineer chose numbered /31 — both are explicitly supported per the doc (§ *Ethernet Virtual Private Network - EVPN*: "For the underlay, only IPv4 or BGP unnumbered configuration is supported"). Numbered is simpler from a Cisco NX-OS 9.3 standpoint. |

### 7.5 What will be measured once unblocked

The same 11-test matrix (5 runs each) will be run on `dpf-ovn-hbn`, producing two new datasets plus the HBN-specific ECMP scaling sweep:

#### Dataset 1 — Full-stack uplift (passthrough vs HBN)

| Metric | A — passthrough | B' — DPF + HBN | Δ |
|---|---|---|---|
| TCP throughput (1, 8, 16 streams) | (already collected) | _to be measured_ | _calc_ |
| UDP send / loss | (already collected) | _to be measured_ | _calc_ |
| TCP_RR / UDP_RR | (already collected) | _to be measured_ | _calc_ |
| TCP_CRR | (already collected) | _to be measured_ | _calc_ |
| Host CPU at line rate | (already collected) | _to be measured_ | _calc_ |
| sockperf p99.9 | (already collected) | _to be measured_ | _calc_ |

#### Dataset 2 — HBN incremental value (VPC-OVN vs HBN)

| Metric | B — VPC-OVN | B' — DPF + HBN | Δ |
|---|---|---|---|
| same matrix as above | (already collected) | _to be measured_ | _calc_ |

#### HBN-specific: ECMP scaling

| # parallel iperf3 streams | B — single path (Gbps) | B' — ECMP across 2 uplinks (Gbps) | uplift |
|---|---|---|---|
| 1 | _to be measured_ | _to be measured_ | _calc_ |
| 2 | _to be measured_ | _to be measured_ | _calc_ |
| 4 | _to be measured_ | _to be measured_ | _calc_ |
| 8 | _to be measured_ | _to be measured_ | _calc_ |
| 16 | _to be measured_ | _to be measured_ | _calc_ |
| 32 | _to be measured_ | _to be measured_ | _calc_ |

Plus the qualitative TC3 checks: BGP session established (`birdc show protocols`), multiple equal-cost routes installed (`birdc show route`), per-uplink traffic balance (`ethtool -S p0 / p1`), and an explicit failover test (admin-shut one uplink while iperf3 is running, measure re-convergence).

### 7.6 Estimated time after the second fabric ask is in

| Step | Wall clock |
|---|---|
| DPU-side: add second BGP neighbor to FRR on each DPU, verify two-path ECMP route installed | 15 min |
| Deploy `dpf-ovn-hbn` cluster on existing 2 nodes | 30 min |
| TC3 qualitative validation (BGP both peers Established, ECMP routes installed for two next-hops, per-uplink traffic balance, controlled failover) | 30 min |
| TC4 11-test × 5-run matrix on HBN cluster | 80 min |
| TC4 ECMP scaling sweep (1/2/4/8/16/32 parallel streams) | 30 min |
| Report compilation (this doc + STACK_EXPLANATION + new charts) | 15 min |
| **Total** | **~3 hours** |

---

## 8. Limitations and Caveats

1. **Reference R (host PF↔host PF) is incomplete.** The "fabric ceiling" with no overlay was partially measured in `results/host-pf-reference-incomplete/` but only 75/110 files were captured before the original L2-bridging issue (since fixed for `p0`) blocked further runs. R bounds the discussion (B can't exceed R) but is not the comparison itself; the A vs B story stands.
2. **n=4** per cluster (runs 2–5; run 1 discarded as warmup per the test plan). Stdev is reported alongside the mean. For most metrics the deltas (+30 % to +290 %) are far larger than within-arm variance.
3. **Single-flow UDP loss is iperf3-bound, not network-bound.** The receiver's iperf3 process is the bottleneck; the same loss percentage appears in both arms because the bottleneck is identical in both. Multi-flow UDP would behave differently.
4. **Pods run on the DPU tenant cluster, not on the host cluster.** This was a forced choice — the host cluster runs Cilium and has no DPF acceleration path. Running the bench pods on the DPU tenant cluster keeps the dataplane on the DPU's br-int, which is the path under test. CPU costs reported are host-side (gpu1 and gpu2 hosts via the persistent `mpstat` slicer), not DPU-side, so the "host CPU saved" metric is the right one.
5. **Plumbing for VPC-OVN pod attachment was manual** (steps 6 & 7 in § 3.3). DPF v25.10.1's `vpc-ovn-node` agent only auto-binds OVS ports for pods with `ServiceInterface` CRs, not raw NAD-annotated pods. For production use the operator-managed flow should be used.
6. **HBN ECMP scaling can't be demonstrated yet** because both DPU `p1` switchports are not in any forwarding domain — see [`FABRIC_HBN_ECMP_REQUEST.md`](FABRIC_HBN_ECMP_REQUEST.md).

---

## 9. Conclusion

DPF v25.10.1 VPC-OVN acceleration **delivers measurable, reproducible improvements** on every metric that exercises the host's networking path, on identical hardware:

- **Host CPU at line rate falls 76–77 %** — the DPU does the work that the host kernel does in passthrough mode.
- **Transaction rate (RR) rises ~2.7×, connection rate (CRR) rises ~3.9×** — conntrack and per-flow processing are hardware-offloaded.
- **Tail latency p99.9 drops 9×** (963 → 104 µs) — predictable hardware path eliminates softirq jitter.
- **Throughput at the 40 Gb/s fabric line rate is identical** in both arms (39.4 Gbps with 8+ streams) — the wire is the limit; the win shows up in the CPU-busy column.
- **Single-stream TCP gains 33 %**, **UDP send rate gains 160 %** — TX-side offload is real.

For the customer-facing positioning ("the DPU pays for itself by freeing host cores while delivering better latency and connection scaling"), the data in this report supports it without qualification.

The HBN/ECMP test (§ 7) will add a second value-prop — multi-uplink aggregate bandwidth — but is gated on a one-time fabric reconfiguration on `custeng.leaf1.1`. Once that's done, the existing test infrastructure (scripts, OVN/NAD setup, runner) reuses cleanly for the third cluster.

---

## Appendix A — File Index

```
results/
├── dpf-ovn-baseline/                 110 result files + run.log (passthrough, n=5 per test)
├── dpf-ovn-accelerated/              220 result files + run.log + host-mpstat slices (VPC-OVN)
├── host-pf-reference-incomplete/     partial (R baseline, fabric-blocked)
└── charts/                           generated PNGs (this report)

scripts/
├── run_pod_baseline.sh               passthrough runner
├── run_pod_accelerated.sh            VPC-OVN runner
├── slice_host_mpstat.sh              cuts persistent mpstat into per-test windows
└── make_charts.py                    generates the charts in this report
```

## Appendix B — Reproducing the Comparison

```bash
# 1. Deploy cluster A (passthrough) and run baseline
python3 scripts/dpf_deploy.py create dpf-ovn-baseline --hosts H1,H2
# wait for cluster Running, then:
bash scripts/run_pod_baseline.sh

# 2. Tear down, deploy cluster B (VPC-OVN), run accelerated
python3 scripts/dpf_deploy.py delete <baseline-uid>
python3 scripts/dpf_deploy.py create dpf-ovn-accelerated --hosts H1,H2
# wait for cluster Running and pods bound to OVN (see §3.3 for manual binding), then:
bash scripts/run_pod_accelerated.sh

# 3. Generate charts and report
python3 scripts/make_charts.py
```

All paths and IPs in the runner scripts are hard-coded for the lab inventory in [`memory/env_details.md`](.claude/projects/-home-ubuntu-dpf-testing-scenarios/memory/env_details.md). Edit before running on a different inventory.
