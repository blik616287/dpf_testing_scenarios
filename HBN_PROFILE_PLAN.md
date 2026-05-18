# DPF Zero Trust — DOCA HBN Cluster Deployment Plan

**Purpose:** Plan the deployment of the third cluster (`dpf-ovn-hbn`) so we can execute TC3 (qualitative validation) and TC4 (HBN A/B benchmark + ECMP scaling sweep). Based on the actual HBN cluster profile pulled from Palette (UID `698dd2dd4b0c719b6c763605`) and lessons learned from the VPC-OVN deployment.

**Status:** **Plan only — not yet executing.** Triggers the destructive teardown of the live `dpf-ovn-accelerated` cluster.

---

## 1. Starting state

| Item | Current value |
|---|---|
| Live cluster | `dpf-ovn-accelerated` on gpu1/gpu2 — VPC-OVN, hw-offload=true |
| Bench pods | `bench-client-vpc`/`bench-server-vpc` on DPU tenant cluster (last left in working state for VPC-OVN) |
| Fabric state | **Both fabric asks complete and verified.** Eth1/23, Eth1/25 in VLAN 497; Eth1/24, Eth1/26 routed /31s; VLAN 497 SVI at 172.16.97.125/27 for second-path BGP |
| BGP on each DPU's `p1` | Established (AS 65010 gpu1 / AS 65020 gpu2 ↔ leaf AS 65001) — set up via FRR on the DPU host, NOT inside an HBN container |
| BGP on each DPU's `ovnvtep` (VLAN 497 SVI peering) | Established |
| ECMP routes | Installed in kernel routing table, L4 hash policy enabled |
| Hugepages on each DPU | 4 × 512 MB (= 2 GB) — manually allocated to fix OVS-DOCA init |
| DPUFlavor in use | `ovn-v25.10.1` (VPC-OVN flavor) — sets specific mlxconfig + kernel cmdline |
| Hardening manifests in use | The 6 in `profile-addons-accelerated/` |
| Benchmark data on disk | Test Set 1 + Test Set 2 — **safe** in `results/`, will not be erased by cluster teardown |

---

## 2. End state we're targeting

`dpf-ovn-hbn` cluster running on the same two hosts:

| Item | Target value |
|---|---|
| Cluster | `dpf-ovn-hbn` (CP-Configs + DOCA HBN addon profiles) |
| DPUFlavor | `hbn-v25.10.1` — different kernel cmdline, mlxconfig, OVS config |
| HBN container per DPU | Running, with FRR doing BGP + EVPN |
| BGP sessions per DPU | At least 2 (matching our existing fabric) — handled inside HBN container, **not** the FRR we set up on DPU host |
| OVS topology | br-int (OVN), br-ovn-ext, br-sfc (with **both p0 AND p1**), br-hbn (active, not empty) |
| Pod attachment | Same `DPUVPC` + `DPUVirtualNetwork` + NAD pattern as VPC-OVN, or HBN-specific equivalent |
| Bench pods | Re-deployed, attached to the post-HBN OVN network |
| All TC3 checks passing | BGP Established, ECMP routes installed, per-uplink traffic balance, controlled failover |
| TC4 11×5 matrix | run on `dpf-ovn-hbn`, comparable to existing datasets |
| TC4 ECMP scaling sweep | run (1, 2, 4, 8, 16, 32 parallel streams) |

---

## 3. Known divergences from current state — and patches needed

Pulled from `/tmp/hbn-profile.json` (Palette UID `698dd2dd4b0c719b6c763605`).

### 3.1 DPUFlavor changes (require DPU reboot via BFB re-push)

| Setting | Current (`ovn-v25.10.1`) | HBN target (`hbn-v25.10.1`) | Risk |
|---|---|---|---|
| Kernel cmdline | `iommu.passthrough=1 net.ifnames=0 biosdevname=0` | adds `cgroup_no_v1=net_prio,net_cls hugepagesz=2048kB hugepages=3072` | Low — DPF re-pushes BFB and reboots DPU |
| Hugepages | 4 × 512 MB (we set manually) | **3072 × 2 MB** = 6 GB | Required for HBN container's DPDK init |
| mlxconfig `ENABLE_ESWITCH_MULTIPORT` | not set | **yes** | Different eswitch mode; required for HBN's multi-uplink topology |
| mlxconfig `LAG_RESOURCE_ALLOCATION` | default | **1** | Required for ECMP at the eswitch level |
| OVS config | `br-sfc` has `p0` only | `br-sfc` has **both `p0` and `p1`** | DPU-side change applied by BFB cloud-init |
| OVS config | `br-hbn` exists but empty | `br-hbn` populated with HBN container's SF representors | Done by HBN container at startup |

**These are all baked in by the BFB install** triggered by the new DPUFlavor — we don't apply them manually.

### 3.2 BGP / EVPN config in the HBN profile vs what the network team configured

The HBN profile's default `startupYAMLJ2` for FRR inside the HBN container:

| Config | HBN profile default | What we have in the lab | Action |
|---|---|---|---|
| Underlay BGP type | **BGP unnumbered** (`type: unnumbered` on `p0_if`, `p1_if`) | **Numbered /31** (172.16.97.248/31 → gpu1; 172.16.97.250/31 → gpu2; VLAN-497 SVI 172.16.97.125/27 → both) | **Must override `startupYAMLJ2`** in helm values to use numbered peers |
| Per-DPU ASN (gpu1) | `bgp_autonomous_system: 65101` | We told the leaf to expect **65010** | **Must override** to 65010 |
| Per-DPU ASN (gpu2) | `bgp_autonomous_system: 65102` | Leaf expects **65020** | **Must override** to 65020 |
| EVPN address-family | enabled (`l2vpn-evpn`, L2VNI 10010, L3VNI 100001) | Leaf is **not** running EVPN — plain IPv4 unicast only | **Need to disable EVPN** in HBN config OR ask network team to add `l2vpn-evpn` to their existing BGP. The HBN doc says fabric doesn't need EVPN, but the HBN container's startup expects it on the local side. Probably acceptable to keep EVPN locally but the leaf will not advertise EVPN routes — need to verify HBN doesn't fail on this. |
| VRF setup | `RED` VRF with VLAN 11 / VNI 10010/100001 | Not relevant for our underlay-only test — but the profile expects pods on the RED VRF | Keep or simplify in helm overrides |

This is the **single biggest unknown**. The profile is built around BGP unnumbered + EVPN, and we have to overlay it onto a numbered/unicast fabric. Most likely-to-work approach: write a custom helm values override that replaces `startupYAMLJ2` with our numbered-peer FRR config.

### 3.3 Same v25.10.1 regressions we already hit (6 hardening manifests)

These almost certainly still apply to the HBN deploy:

| Manifest | Still needed? | Notes |
|---|---|---|
| `02-tenant-bootstrap-token-keeper.yaml` | **Yes** | Same kamaji tenant cluster, same 2 h token expiry issue |
| `05-longhorn-kubelet-root-dir-patch.yaml` | **Yes** | Same Palette/longhorn issue |
| `10-dpu-install-interface-fixer.yaml` | **Yes** | hostagent overwrites still happens in ZT mode |
| `11-dpunode-external-reboot-acker.yaml` | **Yes** | Same external-reboot annotation issue |
| `13-dpu-bmc-rshim-forcer.yaml` (v2) | **Yes — and CRITICAL** | If this runs during the BFB push at the wrong moment, the push aborts. We already learned this lesson and the v2 version guards on "active task" + idempotency. |
| `15-dpu-rebooted-condition-patcher.yaml` | **Yes** | Same host-rshim probe bug in DPF v25.10.1 |

Solution: keep the addon profile that bundles all six in the new cluster's profile list, just like the current VPC-OVN cluster.

### 3.4 New gotchas specific to HBN we should expect

| Gotcha | Likelihood | Mitigation |
|---|---|---|
| HBN container fails to start because BGP unnumbered isn't supported on the numbered /31 we have | **High** | Override `startupYAMLJ2` with numbered config before deploy |
| HBN BGP container can't reach `172.16.97.125` SVI (VLAN-497-only path) because HBN's `p0_if` is in a different VRF | Medium | Probably need to keep that peering on the DPU host's FRR (where we already have it) and let HBN run its own underlay on `p1_if` only |
| OVS chain conflict — HBN expects `br-sfc` to have both p0 and p1, but VPC-OVN config previously had br-sfc with only p0. The BFB install will reset this. | Low (BFB rewrites it) | Verify after BFB install that the new OVS topology is what HBN expects |
| HBN container requires `br-hbn` to be active and patch ports to br-sfc | Medium | HBN's cloud-init / DPUService should set this up, but if it doesn't we'll have to add the patch ports manually |
| Pods on the HBN cluster can't attach to br-int the same way (HBN doesn't use OVN-VPC) | **High — actually expected** | TC4 wants pod-to-pod traffic. If HBN doesn't provide a VPC layer, we need a different pod attachment story. Possibly stack the **VPC-OVN + HBN** combination (BFB has both OVS-DOCA layers — OVN VPC overlay riding on top of HBN BGP underlay). |
| Hugepages need to be 3072 × 2 MB after BFB install; ovs-vswitchd might still need a kick if `vm.nr_hugepages` doesn't get set automatically | Medium | Already learned this trick — set sysctl, restart vswitchd |

---

## 4. Risks and what to watch for

| Risk | Severity | Mitigation |
|---|---|---|
| Existing data loss | **Mitigated** — Test Set 1 and Test Set 2 data are saved to `results/` directories; nothing on disk is at risk |
| Cluster bring-up takes >2 h | Medium — likely (saw 90+ min for VPC-OVN; HBN likely similar plus debug time) | Plan for a 4-6 h block |
| HBN's helm chart values don't apply cleanly | High — needs custom override for numbered BGP + ASN | Write the override values file BEFORE running `dpf_deploy.py create` |
| BGP doesn't establish in HBN container | High — most likely failure point | Have a fallback: keep our existing FRR-on-host setup running in parallel and document it as "underlay validation works; HBN's own BGP didn't" |
| TC4 numbers come out worse than Test Set 2 | Medium | Possible if HBN adds overhead or if the test fabric doesn't actually support EVPN. Be honest in the report. |
| Network team needs more changes | Low-medium | We may need to ask them to enable EVPN or to support BGP unnumbered. Should we have a third ask drafted, just in case? |

---

## 5. Step-by-step execution plan

Each step has an estimated time and a checkpoint where we can stop if things go sideways.

### Phase A — Pre-deploy preparation (no destruction yet) — 30 min

1. **Pull the HBN profile spec from Palette** for diff against our current setup (done; saved to `/tmp/hbn-profile.json`).
2. **Draft a helm values override file** (`hbn-custom-values.yaml`) that:
   - Replaces the per-DPU `bgp_autonomous_system` from 65101/65102 → 65010/65020.
   - Replaces the FRR `startupYAMLJ2` to use numbered BGP peers matching what the network team configured (172.16.97.248, 172.16.97.250, 172.16.97.125).
   - Either disables EVPN or leaves it on but the leaf won't advertise EVPN routes (HBN container won't crash either way; verify locally).
3. **Decide whether to clone-and-patch the HBN cluster profile** in Palette (so the override is part of the profile) or apply the override at cluster create time. Clone-and-patch is more reliable — same approach as the v2 VPC-OVN profile.
4. **Snapshot the running VPC-OVN cluster** in case we need to roll back:
   - List cluster UID via `dpf_deploy.py list`
   - Save the cluster's spec via `kubectl get spectrocluster <uid> -o yaml > /tmp/vpc-ovn-cluster-snapshot.yaml`
   - Save current DPUDeployment, DPUService, DPUVPC, DPUVirtualNetwork manifests
   - This snapshot lets us recreate the VPC-OVN cluster faster if HBN deployment fails completely.

**Stop point**: if we cannot construct the helm override or if there's a fundamental incompatibility with the numbered BGP setup, **abort here** and don't tear down the existing cluster.

### Phase B — Teardown (destructive) — 15 min

5. `python3 scripts/dpf_deploy.py delete <vpc-ovn-cluster-uid>` — wait until both edge hosts return to "Available" state in Palette.
6. Watch for stuck DPUNodes, DPUDevices — clean up if needed.

**Stop point**: if teardown stalls, manually clean up state via Palette UI / kubectl.

### Phase C — HBN cluster create — 30 min to first DPU bring-up; up to 2 h for full readiness

7. `python3 scripts/dpf_deploy.py create dpf-ovn-hbn --hosts <H1,H2>`
8. Watch cluster status:
   - DPF operator deploys
   - DPF starts BFB push to each DPU (~10-15 min per DPU based on prior runs; can be longer)
   - **Critical**: the rshim-forcer cronjob may abort the BFB push. The v2 version with the active-task guard should be okay, but watch for it.
   - DPUs reboot into new BFB; cloud-init runs
   - Both DPUs join the new kamaji tenant cluster
9. Verify DPUFlavor `hbn-v25.10.1` is applied — check mlxconfig and kernel cmdline.

### Phase D — HBN DPUService bring-up — 30 min

10. Watch HBN DPUService deploy on each DPU.
11. Apply the helm values override (or verify it baked into the cluster profile).
12. Check HBN container running on each DPU, FRR running inside, BGP attempting to peer.
13. Verify BGP Established with our existing numbered peers.

**Likely manual interventions at this stage** (based on prior experience):
- Hugepage allocation if BFB doesn't set it (`echo 3072 > /sys/.../nr_hugepages` or sysctl).
- ovs-vswitchd restart if it failed to start.
- Custom OVS bridge wiring if HBN container's startup didn't fully wire br-hbn ↔ br-sfc.

### Phase E — TC3 qualitative validation — 30 min

14. **BGP Established** on each DPU's HBN container — `birdc show protocols` or `vtysh -c "show ip bgp summary"` inside the HBN container.
15. **ECMP routes installed** — `vtysh -c "show ip route bgp"` should show two next-hops for the leaf loopback `11.0.0.111`.
16. **Per-uplink traffic balance** — generate parallel flows from one DPU, watch `ethtool -S p0` and `ethtool -S p1` byte counts; both should increment.
17. **Failover test** — admin-shut one uplink on the leaf side, verify ECMP reconverges within BGP hold time (~3 × keepalive), iperf3 doesn't stall longer than that, no packet loss after convergence.

### Phase F — Pod attachment for benchmarks — 30 min

18. Determine what pod attachment model HBN supports — same `DPUVPC` + `DPUVirtualNetwork` as VPC-OVN? Different CRs? If HBN doesn't ship its own VPC layer, we may need to **stack VPC-OVN on top of HBN** (NVIDIA's "VPC-OVN + HBN" use case — different from either standalone).
19. Re-create `bench-client-vpc` and `bench-server-vpc` pods, manually bind LSPs if needed (same dance as before).
20. Verify ping between net1 IPs across the two DPUs.

### Phase G — TC4 11×5 matrix on HBN — 80 min

21. Adapt the existing runner (`scripts/run_pod_accelerated.sh`) to write output to `results/dpf-ovn-hbn/`.
22. Start host mpstat captures on both gpu1 and gpu2.
23. Launch the matrix in background.
24. Wait. Watch Round boundaries.

### Phase H — TC4 ECMP scaling sweep — 30 min

25. Write `scripts/run_ecmp_scaling.sh`: iterates over parallel-flow counts 1, 2, 4, 8, 16, 32, runs iperf3 -P N for each, captures per-uplink `ethtool -S` deltas to verify ECMP distribution.
26. Run 5 times per N for statistical comparison.

### Phase I — Report generation — 30 min

27. Update `BENCHMARK_REPORT.md` § 7 with actual TC3/TC4 results.
28. Update Test Set 3 = HBN; tabulate all three datasets.
29. Regenerate charts as 4-way comparison (Cilium, VPC-OVN sw, VPC-OVN HW, HBN).
30. Add ECMP scaling chart (throughput vs parallel-flow count).

---

## 6. Time and decision points

| Phase | Best case | Likely | Worst case |
|---|---|---|---|
| A pre-deploy prep | 30 min | 1 h (drafting helm overrides + cluster profile clone) | 2 h if Palette API friction |
| B teardown | 15 min | 30 min | 1 h if stuck DPUNodes |
| C cluster create | 30 min | 1.5 h | 3 h if BFB push fails multiple times |
| D HBN DPUService | 30 min | 1 h | 2 h if BGP doesn't establish |
| E TC3 validation | 30 min | 1 h | 2 h if failover misbehaves |
| F pod attachment | 30 min | 1.5 h | 3 h if HBN doesn't provide a pod-attachment model |
| G TC4 matrix | 80 min | 90 min | 2 h |
| H ECMP sweep | 30 min | 1 h | 2 h |
| I report | 30 min | 1 h | 2 h |
| **Total wall clock** | **~5 h** | **~9 h** | **~18 h** |

The **6–10 h likely** range is what I was alluding to in chat. The single biggest variable is **whether the HBN profile works at all on our numbered/non-EVPN fabric**, which Phase D will reveal.

---

## 7. Rollback plan

If we get stuck mid-deploy and need to abandon:

1. **`dpf_deploy.py delete <hbn-cluster-uid>`** — tear down the broken HBN attempt.
2. **`dpf_deploy.py create dpf-ovn-accelerated --hosts <H1,H2>`** — recreate the VPC-OVN cluster.
3. Wait ~1.5–2 h for full bring-up.
4. Re-apply the manual LSP bindings for the bench pods (we have the runbook in `STACK_EXPLANATION.md` § 3.3).

We **won't lose any test data** in any rollback scenario — all the Test Set 1 and Test Set 2 results are already saved in `results/`.

---

## 8. What we should answer BEFORE executing

These are decisions to make before pulling the trigger on Phase B teardown:

1. **Helm override approach** — clone the HBN cluster profile in Palette and bake the override in (preferred, more reliable) vs apply override at cluster-create time (faster, less reliable). Recommendation: **clone-and-patch**, like we did with the v2 VPC-OVN profile.

2. **EVPN-or-not** on the HBN side — the network team's leaf doesn't run EVPN. The HBN profile expects EVPN. Three options:
   - (a) Keep EVPN on in HBN config; leaf won't advertise EVPN; expect the HBN container to ignore the lack of remote EVPN routes
   - (b) Strip EVPN from HBN's startupYAMLJ2; risk that other HBN components depend on EVPN being on locally
   - (c) Ask network team for a third change — enable `l2vpn-evpn` family on the existing BGP peers

   Recommendation: **try (a) first**. If the HBN container fails or the kernel routes don't install, fall back to (b). (c) is the last resort.

3. **Pod attachment model** — does the HBN profile alone provide a pod-attachment story, or do we need VPC-OVN layered on top? The NVIDIA doc references a "VPC-OVN + HBN" combination as the multi-tenancy use case, suggesting they're complementary. Need to check the HBN profile's DPUServiceConfigurations to confirm whether it includes pod attachment or not.

4. **Time window** — if Phases A-C alone could eat 4 h before we see whether HBN's BGP will Establish, we should book a 6-hour minimum block.

---

## 9. Recommended next action

**Spend 1-2 hours on Phase A only** — draft the helm override values file, decide on the EVPN question by inspecting the HBN container's helm chart, clone the cluster profile. Then **pause** and review before tearing anything down.

If Phase A reveals that the override is tractable and our fabric is going to work without further network-team changes, schedule a 6-hour window for Phases B-I. If Phase A reveals a hard incompatibility, fall back to leaving HBN on the backlog and shipping the existing report as-is (Test Set 1 + Test Set 2 are already the strong story).
