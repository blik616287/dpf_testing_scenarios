# Accelerated Cluster Profile — DPF VPC-OVN

This document describes the **`dpf-ovn-accelerated`** Palette cluster profile: what it
contains, why each piece is there, and how it differs from the baseline profile.

It carries forward every hardening fix discovered during the baseline deployment, plus
a complete VPC-OVN DPUDeployment to actually offload the dataplane to the BlueField DPU.

---

## TL;DR

| | Baseline | Accelerated (this profile) |
|---|---|---|
| DPF use case | Passthrough (br-sfc, no offload) | **VPC-OVN** (DPU is the dataplane) |
| Pod data path | host kernel → host PF → fabric → host PF → host kernel | host pod → VF → DPU OVS pipeline → uplink → fabric |
| Dataplane CPU consumer | host CPU (cilium BPF + host conntrack) | **DPU silicon** (OVS-DOCA + ASAP² hw-offload) |
| Hardening manifests | 6 (numbered 02–09) | **9** (02–12, all baseline + 3 new) |
| VPC-OVN service stack | absent | 4 services + chain + IPAM (numbered 30–51) |

The accelerated arm is what the original A/B test was designed to measure. The
baseline numbers in `results/dpf-ovn-baseline/SUMMARY.md` are the comparison floor.

---

## Profile structure

The Palette profile **`DPF Zero Trust Use Case - VPC-OVN Accelerated`** layers on top
of the existing infra profile (`DPF ZT CP-Agent NetOp v2`, UID
`69f25bfa957ca8a8c6eeb06a`). It replaces the passthrough addon profile
(`DPF Zero Trust Use Case - Passthrough`, UID `69834c1973ed315efeaed916`) with this
VPC-OVN addon, while keeping `Spectro-DPU-DPF-CP-Configs` (UID `69b7039ae8451ebc583d6a13`).

The cluster recipe used by `scripts/dpf_deploy.py`:

```
infra:    69f25bfa957ca8a8c6eeb06a   (ZT CP-Agent NetOp v2)
addon:    69b7039ae8451ebc583d6a13   (Spectro-DPU-DPF-CP-Configs)
addon:    <new>                       (DPF VPC-OVN Use Case + hardening)   ← this profile
```

`scripts/dpf_deploy.py` already accepts `dpf-ovn-accelerated` as a valid cluster name —
the profile UID for the third slot just needs to be updated to point to the new profile.

---

## Manifests

All manifests live under `profile-addons-accelerated/` in this repo. The file numbers
indicate the order we want them rendered into the profile and the rough conceptual
grouping:

```
02-tenant-bootstrap-token-keeper.yaml         lessons-learned hardening (carried from baseline)
03-host-prep-daemonset.yaml                   lessons-learned hardening (carried from baseline)
05-longhorn-kubelet-root-dir-patch.yaml       lessons-learned hardening (carried from baseline)
06-dpunode-alias-controller.yaml              lessons-learned hardening (carried from baseline)
08-dpunode-discovery-daemonset.yaml           lessons-learned hardening (carried from baseline)
09-dpuflavor-mode-rewrite.yaml                lessons-learned hardening (carried from baseline)
10-dpu-install-interface-fixer.yaml           NEW — fixes hostagent install-interface race
11-dpunode-external-reboot-acker.yaml         NEW — auto-removes blocking reboot annotation
12-fabric-host-config.yaml                    NEW — netplan IP on 40G PF for fabric subnet
30-vpc-bfb.yaml                               VPC-OVN — pinned BFB v25.10.1
31-vpc-dpuflavor.yaml                         VPC-OVN — DPUFlavor (DPU mode = zero-trust, MPESW on, OVS-DOCA on)
40-vpc-dpudeployment.yaml                     VPC-OVN — orchestrates the 4 services + service chain
41-vpc-dpuserviceinterface.yaml               VPC-OVN — declares p0 + ovn-ext-patch interfaces
42-vpc-dpuserviceipam.yaml                    VPC-OVN — IP pool for OVN tenants
43-vpc-svc-tpl-ovn-central.yaml               VPC-OVN service template (NB/SB DB)
44-vpc-svc-tpl-ovn-controller.yaml            VPC-OVN service template (per-DPU controller)
45-vpc-svc-tpl-vpc-ovn-controller.yaml        VPC-OVN service template (vpc-ovn-controller)
46-vpc-svc-tpl-vpc-ovn-node.yaml              VPC-OVN service template (per-DPU node agent)
47-vpc-svc-cfg-ovn-central.yaml               VPC-OVN service configuration
48-vpc-svc-cfg-ovn-controller.yaml            VPC-OVN service configuration
49-vpc-svc-cfg-vpc-ovn-controller.yaml        VPC-OVN service configuration
50-vpc-svc-cfg-vpc-ovn-node.yaml              VPC-OVN service configuration
51-vpc-ovn-isolation-class.yaml               VPC-OVN — net-attach IsolationClass for tenant pods
```

### Why number `02–12` (not contiguous)

- 02–09 are the **baseline-proven** hardening manifests, kept at their original numbers
  so we can cross-reference them with the baseline profile in Palette without renumbering.
- 10–12 are **new** hardening manifests that codify lessons learned during the baseline
  deployment (see "Lessons learned" below).
- 30+ is the **VPC-OVN use case** payload, replacing the Passthrough use case payload
  (which was a single helm chart `nvidia-dpf-deployment` configured for passthrough).

---

## Lessons learned: the new manifests (10–12)

### `10-dpu-install-interface-fixer.yaml`

DPF v25.10.1 hostagent's nodemanager (`nodemanager.go:272`) **unconditionally** writes
`DPUNode.Status.DPUInstallInterface = "hostAgent"`, racing the main DPF controller which
honors the `--dpu-install-interface=redfish` flag. Because the DPU's own
`Status.DPUInstallInterface` latches at init time (one-shot, no rewrite), whichever wrote
first wins. In Zero-Trust mode the answer must be `redfish` because there is no host
rshim.

The fix is a CronJob (every 2 min) that:
1. Patches `DPUNode.Status.DPUInstallInterface` back to `redfish` if anything else.
2. Patches `DPU.Status.DPUInstallInterface` back to `redfish` only on DPUs still in
   pre-OS-Installing phases — once a DPU is past that point, switching the field is
   unsafe (provisioning is committed).

This is the single most expensive surprise of the baseline deployment.

### `11-dpunode-external-reboot-acker.yaml`

After BFB activation completes, DPF sets the
`provisioning.dpu.nvidia.com/dpunode-external-reboot-required` annotation on the
DPUNode and **blocks the state machine** until a human removes it. Real-world ZT
deployments assume an operator pushes a power button; in automated benchmarking we
have nobody. This CronJob (every 2 min) removes the annotation when the underlying
DPU is in a phase that confirms it has actually rebooted (`DPU Cluster Config`,
`Ready`, `Rebooting`, `OS Installing`) **or** the DPUNode reports `DPUNodeReady=True`.

### `12-fabric-host-config.yaml`

Configures the host's 40G PF (`enp14s0f0np0`) with a fabric IP via netplan, persistent
across reboots. Required for any host-PF or pod-routed-via-fabric traffic.

Lab-specific values (edit per environment):
- gpu1 (`edge-7bf6f0…`): 172.16.97.10/24
- gpu2 (`gpu-sm02`):     172.16.97.11/24
- VLAN 497 (untagged on access port), MTU 9216

Note: this is **mostly** redundant with VPC-OVN because the VPC-OVN dataplane terminates
on the DPU, not on the host PF. It's kept because:
1. The benchmarks still use the host PF as the comparison reference (host-PF runs).
2. If we ever need to debug VPC-OVN from the host side (e.g., reach the OVN northd
   service on the DPU from the host), having an IP on the fabric subnet is convenient.

### Carried from baseline (02–09)

These were proven during the passthrough deployment and we have no reason to remove them:
- `02-tenant-bootstrap-token-keeper.yaml` — extends bootstrap-token Secret expiry to
  +30 days every 15 min, preventing the 24h kamaji token expiry that orphans DPU joins.
- `03-host-prep-daemonset.yaml` — host netplan + grub (mlx5_core args, hugepages).
- `05-longhorn-kubelet-root-dir-patch.yaml` — patches Longhorn DaemonSet args to use
  `/var/lib/kubelet` (Spectro Palette's kubelet root dir).
- `06-dpunode-alias-controller.yaml` — creates host-named DPUNode aliases so users can
  reference DPUs by hostname instead of OUI-derived BMC name.
- `08-dpunode-discovery-daemonset.yaml` — BMC OUI-based DPUNode discovery.
- `09-dpuflavor-mode-rewrite.yaml` — awk-based YAML mutation that rewrites any
  DPUFlavor with `dpuMode: zero-trust` to `dpuMode: dpu` if needed for use cases that
  legacy-required `dpu`. (NOTE: kept defensively — the new VPC DPUFlavor explicitly
  uses `zero-trust` and may not need this; verify after deployment.)

---

## VPC-OVN use case (30–51)

Sourced from the upstream DPF docs:
`/tmp/doca-platform-source/docs/public/user-guides/zero-trust/use-cases/vpc/manifests/`,
with `$TAG` substituted to `v25.10.1`.

### Architecture

```
       Tenant pods (host worker nodes)
          │  k8s pod CIDR
          │
          ▼ VF (SR-IOV) attached via Multus + ovs-cni
   +─────────────────────────────────+
   │  BlueField-3 DPU                │
   │   +─────────────────────────+   │
   │   │  ovn-controller (per-DPU)│  │
   │   │  vpc-ovn-node    (per-DPU)│ │
   │   +─────────────────────────+   │
   │   br-sfc / OVS-DOCA hw-offload  │
   │              │                  │
   │              ▼ p0 uplink (40G)  │
   +──────────────│──────────────────+
                  ▼
              Fabric switch (VLAN 497)
```

Centralized control plane on one DPU (or HA pair):
- **ovn-central** (NB/SB DB)
- **vpc-ovn-controller** (translates vpc CRs → OVN logical flows)

Per-DPU dataplane:
- **ovn-controller** (programs OVS flows from SB DB)
- **vpc-ovn-node** (sets up local VFs, IPAM, multus)

### Critical DPUFlavor settings (`31-vpc-dpuflavor.yaml`)

- `dpuMode: zero-trust`
- `mlnx-bf.conf`: `ENABLE_ESWITCH_MULTIPORT="yes"` — MPESW must be on for VPC-OVN
- `mlnx-ovs.conf`: `OVS_DOCA="yes"`, `CREATE_OVS_BRIDGES="no"`
- nvconfig: `LAG_RESOURCE_ALLOCATION=1`, `NUM_OF_VFS=46`, `SRIOV_EN=1`
- ovs rawConfigScript: `doca-init=true`, `hw-offload=true`, p0 added to br-sfc as DPDK
  port with mtu_request=9216
- Hugepages: `hugepagesz=2048kB hugepages=3072` (≈6 GiB at 2M, for OVS-DOCA mempool)

### DPUDeployment (`40-vpc-dpudeployment.yaml`)

Selects all DPUs with `feature.node.kubernetes.io/dpu-enabled: "true"`, deploys all
4 services, and chains `p0` ↔ `ovn-ext-patch` (the OVN external patch port). This is
the topology that puts the DPU between the host pod and the uplink.

### Service chain (`41-vpc-dpuserviceinterface.yaml`)

Declares two DPUServiceInterfaces:
- `p0` — physical uplink (labels `ovn.vpc.dpu.nvidia.com/interface: p0`)
- `ovn-ext-patch` — patch port created by ovn-controller for external traffic

The chain in `40-vpc-dpudeployment.yaml` glues them together via OVS patch ports
managed by the SF-CNI-controller.

---

## Deployment plan

### Phase B — Create the Palette cluster profile

```bash
# 1. Get an admin Palette API token, project UID, and a workspace to upload to.
export PALETTE_API_KEY=...
export PALETTE_PROJECT_UID=...

# 2. Drive the API directly (not gomi/CLI) — Palette CLI doesn't expose
#    the customManifests array on packs in a useful way. The deploy script
#    already speaks the API; we'll add a helper subcommand `clone-profile`.

# Process:
# a. POST /v1/clusterProfiles with metadata.name = "DPF Zero Trust Use Case - VPC-OVN Accelerated"
# b. POST packs[]:
#       - name: nvidia-dpf-deployment   (helm chart, configured for VPC-OVN)
#       - name: dpf-vpc-ovn-manifests   (manifest pack — pure k8s YAML)
#         manifests:
#            - 30-vpc-bfb.yaml ... 51-vpc-ovn-isolation-class.yaml
#       - name: dpf-zt-hardening
#         manifests:
#            - 10-dpu-install-interface-fixer.yaml
#            - 11-dpunode-external-reboot-acker.yaml
#            - 12-fabric-host-config.yaml
# c. Verify by GET /v1/clusterProfiles/<uid>
```

We have an existing Palette pack inventory from API:
- profile `69f25bfa957ca8a8c6eeb06a` "DPF ZT CP-Agent NetOp v2" — 8 packs, custom
  manifests in csi-longhorn (3) and dpf-zt-cluster (8). 02, 03, 05, 06, 08, 09 from
  this list ALREADY live there; **we don't need to re-add them.** They are inherited
  through the infra profile.
- profile `69b7039ae8451ebc583d6a13` "Spectro-DPU-DPF-CP-Configs" — manifests for
  trusted-mode, nic-cluster-policy, sriov-policy. Inherited.
- New addon profile only needs: VPC-OVN manifests + the 3 new hardening manifests.

### Phase C — Deploy the cluster

```bash
# 1. Stop benchmarks, tear down baseline
python3 scripts/dpf_deploy.py delete <baseline-uid>

# 2. Wait for hosts to release back to "in-use=false" in Palette
python3 scripts/dpf_deploy.py hosts

# 3. Update dpf_deploy.py with the new accelerated profile UID
#    (DPF_VPC_ADDON_PROFILE_UID = "...")

# 4. Create accelerated cluster
python3 scripts/dpf_deploy.py create dpf-ovn-accelerated \
    --hosts <gpu1-uid>,<gpu2-uid>

# 5. Watch progress
python3 scripts/dpf_deploy.py wait <new-uid> --timeout 7200

# 6. Once Running, verify the accelerated stack:
kubectl get dpu,dpunode -n dpf-operator-system
kubectl get dpudeployment -n dpf-operator-system
kubectl get dpuservice -n dpf-operator-system
kubectl get pods -n dpf-operator-system | grep -E 'ovn-central|ovn-controller|vpc-ovn'

# 7. Re-deploy bench-client and bench-server pods (this time using vpc-ovn-attached
#    network instead of cilium pod CIDR) and re-run scripts/run_pod_baseline.sh
#    against the new pod IPs.
```

### Expected uplift over baseline

Recall baseline (`dpf-ovn-baseline` summary):

| Benchmark | Baseline | Expected accelerated direction |
|---|---:|---|
| TCP 1-stream | 20.48 Gbps | should approach fabric ceiling ~25 Gbps |
| TCP 8-stream | 39.40 Gbps | similar; already line-rate |
| UDP 64B PPS | 165 kpps | substantial uplift (DPU silicon vs host CPU) |
| TCP_RR latency | 117.1 µs | should drop noticeably |
| sockperf p99 RTT | 170.9 µs | should drop |
| Host CPU during 8-stream | several cores busy | near-idle (offloaded) |

If we don't see clear uplift in PPS and RR-latency benchmarks, it means hw-offload
isn't actually engaging — first thing to verify is `ovs-appctl dpctl/dump-flows -m`
on the DPU showing `actions:offloaded`.

---

## What is NOT in this profile

- **HBN** (DOCA Host-Based Networking): that's a separate cluster (`dpf-ovn-hbn`)
  with a different addon profile (BGP/ECMP routing on the DPU). HBN is the third arm
  of the test matrix, not this one.
- **Multi-tenant VPC isolation tests**: `51-vpc-ovn-isolation-class.yaml` is included
  but our benchmark uses a single tenant. Multi-tenant testing is outside the scope
  of the baseline-vs-accelerated A/B comparison.
- **Cilium VXLAN tunnel mode**: baseline uses cilium native routing on the 40G fabric.
  Accelerated bypasses cilium entirely for inter-pod data traffic (it goes via VF →
  DPU OVS → uplink), so cilium config doesn't materially affect the accelerated path.
  Cilium continues to be the host-side CNI for system pods.

---

## Open risks

1. **DPUFlavor `dpuMode: zero-trust` vs `dpu`** — the upstream VPC-OVN flavor uses
   `zero-trust`. Manifest `09-dpuflavor-mode-rewrite.yaml` rewrites
   `zero-trust → dpu`, which would corrupt the VPC-OVN flavor. Action item: either
   gate `09` to specific DPUFlavor names, or remove it from this profile if VPC-OVN
   only needs `zero-trust`.
2. **MPESW + LAG_RESOURCE_ALLOCATION conflict** — both are set; on some BFB versions
   one suppresses the other. Verify post-BFB-install with `mlxconfig -d <pci> q`.
3. **Pod attachment changes** — bench pods in baseline used the cilium default network.
   For VPC-OVN the bench pods need a `k8s.v1.cni.cncf.io/networks` annotation pointing
   at a NetworkAttachmentDefinition created by `vpc-ovn-node`. The benchmark scripts
   need to be re-pointed at the new pod IPs.
4. **Two-hour bootstrap token vs DPU BFB install duration** — empirically observed to
   be tight. The token-keeper handles the token expiry, but the bfcfg join command
   bakes in a token-id; if the DPU literally can't reach the apiserver within 2h, the
   token in the bfcfg has been deleted and join fails. The keeper extends, doesn't
   regenerate-then-rebake.
