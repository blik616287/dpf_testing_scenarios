# Spectro Cloud Palette HBN Plan — v2 (Zero Trust primary + Host-Trusted A/B)

> **Status:** read-only design doc. No Palette resources have been created or modified.
>
> **Relationship to other docs:**
> - **Supersedes** the original `/tmp/hbn_plan.md` (a v1 draft that incorrectly assumed `deploymentMode: host-trusted`).
> - **Builds on** `HBN_PROFILE_PLAN.md` (the May 17 narrow deploy plan for the now-confirmed-broken `698dd2dd…` profile).
> - **Implements toward** `BENCHMARK_REPORT.md` §§ 7.0–7.9 (the measurement targets) and Appendix B.2 (the workaround catalog this profile encodes).
>
> **Measurement basis:** The §7 measurements (37 Gbps single-pair, 77 Gbps 4-uplink aggregate, 132.85 µs sockperf p99.9, sub-second BGP failover, ~4 % host CPU at line rate) were taken on the `dpf-ovn-baseline` family of profiles — **Zero Trust**, kamaji-hosted DPU tenant cluster, bench pods on the host cluster receiving DPU-offloaded VFs. The broken `698dd2dd…` HBN addon was authored as if it were a host-trusted overlay on a ZT base; that mismatch is part of why it never deployed.
>
> **Order of work:** Deliverable 1 (the ZT-mirroring profile family — ships first, reproduces §7 verbatim). Deliverable 2 (host-trusted variant + A/B benchmark plan to honestly compare modes).

---

# Deliverable 1 — Zero Trust HBN profile (primary, ships first)

## D1.1 Summary

This is the ZT-mirroring profile family that reproduces the §7 measurements verbatim. It preserves the two-cluster topology (host cluster + kamaji-managed `dpu-cplane-tenant1`), reuses the existing ZT infra packs (DPF v25.10.1 ZT operator + ZT CP-Configs) and adds an HBN payload addon authored fresh on `nvidia-dpf-deployment 25.10.1`. The host CNI is swapped from Cilium (which the existing ZT NetOp v2 ships) to **OVN-Kubernetes**, per constraint 2 — this is the only real divergence from the §7 reference stack at the infra layer. Host-trusted is **not** this deliverable; it's Deliverable 2 (a follow-on we benchmark before recommending to customers).

**What this delivers:**
- A new infra profile `dpf-ovnk-hbn-infra-zt` — forked from `69f25bfa957ca8a8c6eeb06a` (DPF ZT CP-Agent NetOp v2), Cilium swapped for OVN-K, kubeproxy disabled, all other ZT carry-over manifests preserved.
- A new payload profile `dpf-ovnk-hbn-payload-zt` — single pack `nvidia-dpf-deployment 25.10.1` with a fresh values block (not reused from the broken `698dd2dd…`) carrying DPUFlavor `hbn-ovnk` with `dpuMode: zero-trust`, DPUServiceTemplate `doca-hbn` (numbered /31 eBGP, ECMP), DPUServiceTemplate `ovn` (the DPU-side OVN-K node), and the SFC chain that wires p0/p1/pf2dpu2 through HBN.
- **Reuse** of the existing CP-Configs addon `69b7039ae8451ebc583d6a13` (Spectro-DPU-DPF-CP-Configs) for the DPUCluster + nic-cluster-policy + sriov-policy, with a values-only overlay to uncomment the `bf3-p1-vfs` block (needed for ECMP across both PFs).
- An optional opt-in egress-glue manifest pack (Profile D) gated by `enableEgressGlue=false` — for sites whose topology actually requires the `.240` VIP plumbing and host metric-fix workarounds.

## D1.2 Architecture pivot table — what changes from v1 (host-trusted)

| Aspect of v1 plan | v1 assumed (host-trusted) | Corrected (Zero Trust) |
|---|---|---|
| `nvidia-dpf-operator` values | `provisioningController.installInterface` commented out; values picked up the default (= host-trusted) | **Uncomment `installInterface.installViaRedfish.bfbRegistryAddress: "{{ .spectro.system.cluster.kubevip }}:8080"`** — verbatim from `/tmp/palette-pack-values/infra-nvidia-dpf-operator-25.10.1-values.yaml` lines 30–34 |
| `DPFOperatorConfig` inline manifest `deploymentMode:` | `host-trusted` (explicit) | **omit** the field (DPF operator default = ZT) — the existing `dpf-operator-config` manifest in the ZT NetOp v2 profile does this, preserve it |
| DPUFlavor `dpuMode` | `host-trusted` | **`zero-trust`** |
| Cluster topology | Single host cluster, DPU nodes are host-cluster workers | **Two clusters**: host cluster + kamaji-managed `dpu-cplane-tenant1` (DPUCluster CR present, DPU nodes are tenant-cluster workers) |
| CP-Configs addon | Custom-authored `dpf-ovnk-hbn-cpconfigs` manifest pack (v1 § 4.3 — 8 manifests) | **Reuse `69b7039ae8451ebc583d6a13`** (existing Spectro-DPU-DPF-CP-Configs) with a values-overlay block; only the SR-IOV policy bf3-p1-vfs uncomment + the OVN-K resource-injector helm + MTU configmap-patch job + zone-label job land as a *small* overlay pack (`dpf-ovnk-hbn-cpconfigs-overlay`) |
| ZT carry-over manifests | Dropped under "host-trusted obviates this" | **Reinstated**: `bootstrap-token-keeper`, `dpunode-discovery-daemonset`, `host-prep`, `dpuflavor-mode-rewrite`, `dpunode-alias-controller` are already in the ZT NetOp v2 `dpf-zt-cluster` inline pack — preserved as-is. **Add** `dpu-install-interface-fixer` (`profile-addons-accelerated/10-…`) and `dpunode-external-reboot-acker` (`11-…`) which the v2 doesn't carry but are load-bearing under ZT |
| Workaround coverage W3 (install-interface race) | Dropped — said "host-trusted has no hostAgent" | **Back open** — encoded via the `dpu-install-interface-fixer` CronJob (every 2 min, patches DPUNode.Status.dpuInstallInterface to `redfish`) |
| Workaround coverage W4 (kubeadm token 2 h expiry) | Dropped — said "host-trusted doesn't use kubeadm join" | **Back open** — encoded via the `bootstrap-token-keeper` CronJob (already in ZT NetOp v2 `dpf-zt-cluster.bootstrap-token-keeper`, every 15 min refreshes bootstrap-token-* secrets to +30 d in the kamaji tenant) |
| Workaround coverage W7 (both-node dpu-host / kamaji deadlock) | Documented-prereq (warned about kamaji-in-KVM as a topology constraint) | **Still open** — ZT *requires* kamaji, so this gap doesn't go away. The k8s machinePool must designate exactly one node as dpu-host (`useControlPlaneAsWorker: false`), keeping kamaji + local-path-etcd on the .90 control-plane node only |
| Workaround coverage W8 (.240 VIP plumbing) | Encoded opt-in via egress-glue | Same. ZT topology still routes through the kamaji tenant API VIP |
| W11 (DPU components hard-coded ClusterIP) | Documented-prereq | Same — but now `bootstrap-token-keeper` + `host-prep` (already in `dpf-zt-cluster`) walk around in practice |
| Single CNI swap (Cilium → OVN-K) on the infra | yes | **Same** — keep this. Constraint 2 stands |
| Profile count | Four (Infra, Payload, CP-Configs-custom, Egress-Glue) | **Three new + one reuse**: Infra (new fork), Payload (new), CP-Configs (existing `69b7039a…` reused with values overlay), Egress-Glue (new opt-in pack 4) |

## D1.3 Resolved pack stack (ZT)

UIDs resolved by the prior agent run; values snapshots in `/tmp/palette-pack-values/`.

| Pack name | Pack UID | Tag | Registry UID | Layer | Role in this design |
|---|---|---|---|---|---|
| `edge-native-byoi` | `675f1171e0153f3d34d22d13` | `2.1.0` | `64eaff453040297344bcad5d` | os | Infra OS — verbatim from ZT NetOp v2 |
| `edge-k8s` | `696d0ee4ef11f75302dbdaff` | `1.33.6` | `64eaff453040297344bcad5d` | k8s | **KEEP edge-k8s 1.33.6 — match §7 reference** (the ZT NetOp v2 ships this; the v1 RKE2 switch is rejected — see § D1.4) |
| `cni-ovn-kubernetes` | `67fe80de85df4bd9d894c1cc` | (single rev) | `64cbb11ccd8804c7daa9543b` (tenant `packs-spectro.dreamworx.nl`) | cni | **Replaces cni-cilium-oss** per constraint 2 |
| `csi-longhorn` | `690e16355571ad04766ba35b` | `1.10.0` | `64eaff453040297344bcad5d` | csi | Match §7 ZT NetOp v2 (NOT the 1.10.1 v1 picked from host-trusted-v2 AICP) |
| `nvidia-dpf-prereqs` | `6981cbbae0eb268cb6bf71e9` | `25.10.1` | `671a7057c9a67791a2add6c0` | addon | Reuse the ZT values verbatim |
| `nvidia-dpf-operator` | `69808f9d35d497da0b235119` | `25.10.1` | `671a7057c9a67791a2add6c0` | addon | **CRITICAL diff vs v1**: `installViaRedfish` block uncommented per `infra-nvidia-dpf-operator-25.10.1-values.yaml` lines 29–34 |
| `network-operator` | `6951d8be0689c1e30fa160f2` | `25.10.0` | `671a7057c9a67791a2add6c0` | addon | **UID differs from v1** (`693811208c34d8a8dec7e34a` was the AICP host-trusted UID). ZT NetOp v2 uses this one — preserve |
| `dpf-zt-cluster` (inline manifest pack) | n/a (inline) | – | – | addon | The 8 bundled manifests stay inside the infra profile: `dpu-cluster`, `dpu-bmc-password`, `dpu-discovery`, `host-prep`, `dpuflavor-mode-rewrite`, `bootstrap-token-keeper`, `dpunode-alias-controller`, `dpunode-discovery-daemonset` |
| `nvidia-dpf-deployment` | `69808f9d35d497da06f2e564` | `25.10.1` | `671a7057c9a67791a2add6c0` | addon | Payload — values authored fresh (do **not** reuse `_broken-hbn-values.yaml`) |
| `dpf-control-plane` (CP-Configs manifest pack) | `69b7039ae8451ebc5382d527` | `1.0.0` | – | addon | Wrapped inside cluster profile `69b7039ae8451ebc583d6a13`. **Reuse directly**; values overlay adds the SR-IOV bf3-p1-vfs uncomment + resource-injector + MTU/zone jobs |

There is **no** OVN-K resource-injector pack and **no** DOCA HBN pack in this tenant — both ride as Helm references inside the `nvidia-dpf-deployment` values + as a `HelmChart` CR in the CP-Configs overlay.

## D1.4 RKE2 vs edge-k8s — decision reversal vs v1

v1 chose `edge-rke2 1.34.2` over `edge-k8s 1.33.6` because RKE2 natively supports `cni: none` + `disable: [rke2-kube-proxy]`. **Under ZT we keep `edge-k8s 1.33.6`** because:

1. The §7 measurements were on `edge-k8s 1.33.6` — `BENCHMARK_REPORT.md` § 2.2 line 92: "Kubernetes: host cluster v1.33.6". Changing the K8s pack changes a load-bearing variable.
2. The ZT NetOp v2 profile `69f25bfa…` ships `edge-k8s 1.33.6` — reusing the proven stack.
3. The `cni:none` + kubeproxy-disable can be done on edge-k8s via the kubeadm `initConfiguration.skipPhases: [addon/kube-proxy]` + `joinConfiguration.skipPhases: [addon/kube-proxy]` block in the values tree. v1 called this "fragile" — under ZT we accept the fragility because the alternative (RKE2 1.34.2) reintroduces an unmeasured-CRI-version risk and forks from the reference.

## D1.5 Profile definitions

### D1.5.1 Profile A — `dpf-ovnk-hbn-infra-zt` (cluster type, new fork of `69f25bfa…`)

POST shape (full `POST /v1/clusterprofiles` body — `<reuse>` cells mean "copy the value block from the listed snapshot verbatim"):

```json
{
  "metadata": {
    "name": "dpf-ovnk-hbn-infra-zt",
    "labels": {"tier": "infra", "dpf-version": "25.10.1", "dpf-mode": "zero-trust", "cni": "ovn-kubernetes"}
  },
  "spec": {
    "version": "1.0.0",
    "template": {
      "type": "cluster",
      "cloudType": "edge-native",
      "packs": [
        {"name":"edge-native-byoi","type":"oci","layer":"os",
         "registryUid":"64eaff453040297344bcad5d","packUid":"675f1171e0153f3d34d22d13","tag":"2.1.0",
         "values":"<reuse: infra-edge-native-byoi-2.1.0-values.yaml>"},

        {"name":"edge-k8s","type":"oci","layer":"k8s",
         "registryUid":"64eaff453040297344bcad5d","packUid":"696d0ee4ef11f75302dbdaff","tag":"1.33.6",
         "values":"<base: infra-edge-k8s-1.33.6-values.yaml + diff D1.5.1.a below>"},

        {"name":"cni-ovn-kubernetes","type":"oci","layer":"cni",
         "registryUid":"64cbb11ccd8804c7daa9543b","packUid":"67fe80de85df4bd9d894c1cc",
         "values":"<see D1.5.1.b — OVN-K override block>"},

        {"name":"csi-longhorn","type":"oci","layer":"csi",
         "registryUid":"64eaff453040297344bcad5d","packUid":"690e16355571ad04766ba35b","tag":"1.10.0",
         "values":"<reuse: infra-csi-longhorn-1.10.0-values.yaml>",
         "manifests":["setting-instance-mgr-cpu","setting-taint-toleration","longhorn-kubelet-root-dir-patch"]},

        {"name":"nvidia-dpf-prereqs","type":"oci","layer":"addon",
         "registryUid":"671a7057c9a67791a2add6c0","packUid":"6981cbbae0eb268cb6bf71e9","tag":"25.10.1",
         "values":"<reuse: infra-nvidia-dpf-prereqs-25.10.1-values.yaml>"},

        {"name":"nvidia-dpf-operator","type":"oci","layer":"addon",
         "registryUid":"671a7057c9a67791a2add6c0","packUid":"69808f9d35d497da0b235119","tag":"25.10.1",
         "values":"<reuse: infra-nvidia-dpf-operator-25.10.1-values.yaml VERBATIM — keep installViaRedfish uncommented per lines 30-34>",
         "manifests":["persistent-storage"]},

        {"name":"network-operator","type":"oci","layer":"addon",
         "registryUid":"671a7057c9a67791a2add6c0","packUid":"6951d8be0689c1e30fa160f2","tag":"25.10.0",
         "values":"<reuse: infra-network-operator-25.10.0-values.yaml>"},

        {"name":"dpf-zt-cluster","type":"manifest","layer":"addon",
         "values":"pack:\n  spectrocloud.com/install-priority: \"20\"\n",
         "manifests":[
           "dpu-cluster",
           "dpu-bmc-password",
           "dpu-discovery",
           "host-prep",
           "dpuflavor-mode-rewrite",
           "bootstrap-token-keeper",
           "dpunode-alias-controller",
           "dpunode-discovery-daemonset",
           "dpu-install-interface-fixer",
           "dpunode-external-reboot-acker"
         ]}
      ]
    }
  }
}
```

#### D1.5.1.a `edge-k8s 1.33.6` values delta — kubeproxy disable + cni:none

```yaml
pack:
  podCIDR: "{{ .spectro.var.K8sPodCIDR }}"
  serviceClusterIpRange: "{{ .spectro.var.K8sServiceCIDR }}"

charts:
  edge-k8s:
    cluster:
      config:
        clusterConfiguration:
          networking:
            podSubnet: "{{ .spectro.var.K8sPodCIDR }}"
            serviceSubnet: "{{ .spectro.var.K8sServiceCIDR }}"
        initConfiguration:
          skipPhases: ["addon/kube-proxy"]
          nodeRegistration:
            kubeletExtraArgs:
              read-only-port: "0"
              streaming-connection-idle-timeout: "5m"
            taints: []
        joinConfiguration:
          skipPhases: ["addon/kube-proxy"]
          nodeRegistration:
            kubeletExtraArgs:
              read-only-port: "0"
              streaming-connection-idle-timeout: "5m"
    cni:
      preInstalled: true
```

#### D1.5.1.b `cni-ovn-kubernetes` values block

Verbatim OVN-K override block — same shape as the v1 plan's § 4.1.2: `ovnkube-single-node-zone: true`, `ovnkube-control-plane: true`, `ovnkube-node-dpu: true`, `ovnkube-node-dpu-host: true`, `ovs-node: false`, `mtu: "{{ .spectro.var.PodMTU }}"`, gatewayMode shared, gatewayOpts `--gateway-interface=derive-from-mgmt-port`, transit subnet `100.88.0.0/16`, enableInterconnect/enableMultiNetwork true, image tag `v25.04`. Mode-independent (the chart doesn't know whether DPF underneath is ZT or HT).

### D1.5.2 Profile B — `dpf-ovnk-hbn-payload-zt` (addon)

Single pack: `nvidia-dpf-deployment 25.10.1` (UID `69808f9d35d497da06f2e564`). Authored fresh.

Load-bearing diffs vs v1 § 4.2:

| Field | v1 (host-trusted) | ZT corrected |
|---|---|---|
| `dpuFlavors[0].dpuMode` | `host-trusted` | **`zero-trust`** |
| `grub.kernelParameters` | `hugepages=3072` etc. | **Same** — preserved verbatim |
| `dpuServiceTemplates[doca-hbn]` Helm ref | `{{ .spectro.var.HBN_HELM_REPO }}` v1.0.5 | **Same** |
| `dpuServiceTemplates[ovn]` | gatewayOpts `--gateway-interface=br-dpu`, vtepCIDR 10.0.120.0/22 | **Same** |
| `dpuServiceConfigurations[doca-hbn].serviceDaemonSet.annotations.networks` | full 5-entry, fully namespaced (encodes W14) | **Same** |
| `perDPUValuesYAML` | per-DPU ASN + p0/p1 peer IPs as `{{ .spectro.var.DPU1_… }}`/`{{ .spectro.var.DPU2_… }}` | **Same** — numbered /31, AS 65010/65020 |
| `startupYAMLJ2` | numbered eBGP per § 7.1 with `multipaths.ebgp: 16` | **Same** |
| `dpuServiceIPAMs` pool1 + loopback | per § 7.1 | **Same** |
| `dpuServiceCredentialRequests` ovn-dpu duration `2160h` | per W4 mitigation | **Keep** — under ZT this is NOT redundant with `bootstrap-token-keeper`; it's a separate SA-token chain (OVN→tenant API auth) |
| Pack `manifests:` list (inline) | refs `dpucluster`, `nic-cluster-policy`, etc. | **Empty** — these belong in CP-Configs (Profile C), not duplicated here |

Full YAML for the payload values: identical to v1 § 4.2 with `dpuMode: host-trusted` → `dpuMode: zero-trust` (single-line find-replace).

### D1.5.3 Profile C — Reuse `69b7039ae8451ebc583d6a13` + values-only overlay (Profile C′)

The existing **Spectro-DPU-DPF-CP-Configs** (`69b7039ae8451ebc583d6a13`) ships three manifests:
- `dpf-trusted-mode-cp` — namespace `dpu-cplane-tenant1` + DPUCluster kamaji-mode with keepalived VIP
- `nic-cluster-policy` — NicClusterPolicy (Multus 3.9.3 + bridge + ipoib paths)
- `sriov-policy` — SriovNetworkNodePolicy for `bf3-p0-vfs`; `bf3-p1-vfs` is **commented out**

**Decision: do NOT fork.** Ship a thin overlay pack `dpf-ovnk-hbn-cpconfigs-overlay-zt` layered alongside:

```
Profile C′ — dpf-ovnk-hbn-cpconfigs-overlay-zt (manifest pack)
├── sriov-policy-p1.yaml          NEW SriovNetworkNodePolicy bf3-p1-vfs (uncommented), name=bf3-p1-vfs
│                                  resourceName=bf3-vfs-p1, pfNames `{{.spectro.var.DPU}}f1np1#2-45`
├── ovnk-resource-injector.yaml   NEW HelmChart CR (ovn-kubernetes-resource-injector chart, no Palette
│                                  pack exists), values: resourceInjector.enabled=true,
│                                  resourceName=nvidia.com/bf3-p0-vfs
├── mtu-configmap-patch.yaml      NEW Job — patches ovn-kubernetes-config.mtu to {{ .spectro.var.PodMTU }}
│                                  then kubectl rollout restart cluster-manager + node-dpu-host (W13)
└── ovn-zone-label-controller.yaml NEW Deployment (not Job) — long-running, watches DPU nodes
                                   appearing in kamaji tenant; applies k8s.ovn.org/dpu-host="",
                                   k8s.ovn.org/zone-name=<node>, annotation
                                   k8s.ovn.org/remote-zone-migrated=<node> (W10)
```

Pack-level: `spectrocloud.com/install-priority: "1"` so the overlay sequences after base CP-Configs (priority 0) but before the payload (priority 30).

**Why not fork `69b7039a…`?** (1) It's in production use by `dpf-ovn-accelerated` and the §7 reference cluster — forking risks drift. (2) The 8 manifests v1 tried to author from scratch in § 4.3 mostly already exist inside `69b7039a…` + `dpf-zt-cluster` — avoiding re-author reduces audit surface.

Net: v1's 8 manifests in a fork → 4 manifests in an overlay layered onto the existing CP-Configs.

### D1.5.4 Profile D — `dpf-ovnk-hbn-egress-glue-zt` (addon, opt-in)

Identical to v1 § 4.4 — the egress-glue DS that drops systemd units (`dpf-runtime-fixup.service`, `dpf-brdpu-shim.service`, `vip240-arp.service`, `vip240-proxy.service`, optional `tinyproxy.service`, `dpf-vf-rename.service`, `dpf-dpu-clock.service`). Opt-in via `enableEgressGlue=true`. DaemonSet pattern mirrors `infra-zt-dpf-zt-cluster--host-prep.yaml` (`nsenter -t 1 -m`).

The PHASE6_EGRESS_BLOCKER.md plumbing applies to ZT too — when the topology has the kamaji-in-KVM bridge (`.91` backend) the .240 VIP isn't kernel-routable, only ARP-announceable through OVS.

## D1.6 Customer variables

| Variable | Profile(s) | Default | ZT-only? | Notes |
|---|---|---|---|---|
| `K8sPodCIDR` | Infra | `10.233.64.0/18` | no | Must not overlap HBN pool/loopback |
| `K8sServiceCIDR` | Infra | `10.233.0.0/18` | no | |
| `PodMTU` | Infra, CP-Configs overlay, Payload | `8940` | no | Drops to 1400 fallback if FabricMTU < 9216 (~50 % throughput loss) |
| `FabricMTU` | Payload | `9216` | no | |
| `HbnSwpMTU` | Payload | `9000` | no | = FabricMTU − 216 |
| `controlPlaneInterface` | Infra + CP-Configs | `enp129s0f0` | **YES** | DPUCluster keepalived; HT no-op |
| `controlPlaneVIP` | Infra + CP-Configs | `172.16.30.244` | **YES** | DPUCluster keepalived VIP |
| `dpuOobPassword` | dpf-zt-cluster.dpu-bmc-password | – | **YES** | BMC OOB pwd; HT uses host rshim instead of Redfish |
| `dpfDiscoveryStartIP`/`EndIP` | dpf-zt-cluster.dpu-discovery | `172.16.30.33`/`.36` | **YES** | DPU OOB IP range for Redfish discovery |
| `DPU` | CP-Configs overlay | `enp14s0` | no | PF prefix |
| `DPUNumVFs` | Payload, CP-Configs | `46` | no | |
| `BFB_URL` | Payload | (DOCA 3.2.1-34 BFB URL) | no | |
| `HBN_HELM_REPO` | Payload | `https://helm.ngc.nvidia.com/nvidia/doca` | no | |
| `OVNK_HELM_REPO` / `OVNK_CHART_TAG` | Infra, Payload, CP-Configs | `oci://ghcr.io/mellanox/charts` / `v25.10.0` | no | |
| `DPU1_HOSTNAME_PATTERN` | Payload | `*mt24326005fn*` | no | **B.2 most-common HBN failure** |
| `DPU1_HOSTNAME` | Payload | `dpu-node-mt24326005fn-mt24326005fn` | no | |
| `DPU1_BGP_ASN` | Payload | `65010` | no | |
| `DPU1_P0_PEER_IP`/`LOCAL_IP` | Payload | `172.16.97.240` / `.241/31` | no | |
| `DPU1_P1_PEER_IP`/`LOCAL_IP` | Payload | `172.16.97.248` / `.249/31` | no | |
| `DPU1_POOL1_CIDR` | Payload | `172.16.97.8/29` | no | |
| `DPU2_*` (mirror) | Payload | (.244/.245/31, .250/.251/31, AS 65020, pool `.0/29`) | no | |
| `HbnPool1CIDR` | Payload | `172.16.97.0/24` | no | |
| `HbnLoopbackCIDR` | Payload | `11.0.0.0/24` | no | |
| `enableEgressGlue` | Egress-Glue | `false` | no | |
| `enableTinyproxy` | Egress-Glue | `false` | no | |
| `tenantApiVIP` | Egress-Glue | `172.16.30.240` | **YES (effectively)** | No tenant API under HT |
| `kamajiBackendIP` | Egress-Glue | `172.16.30.91` | **YES** | DNAT target |

Summary: **6 ZT-only vars** (`controlPlaneInterface`, `controlPlaneVIP`, `dpuOobPassword`, `dpfDiscoveryStartIP`/`EndIP`, `tenantApiVIP`, `kamajiBackendIP`).

## D1.7 Workaround coverage map (re-counted under ZT)

| # | B.2 item | ZT status | Encoded where |
|---|---|---|---|
| W1 | DPF v25.10.1 BFB-URL concat bug | **OPEN (medium)** | `bfbRegistryAddress: "{{ .spectro.system.cluster.kubevip }}:8080"` sidesteps the `?{bfb}?{bfcfg}` concat |
| W2 | rshim-forcer cronjob | encoded (omission) | We do NOT ship the rshim-forcer DS |
| W3 | DPU install-interface race | **encoded** | `dpu-install-interface-fixer` CronJob added to ZT `dpf-zt-cluster` inline pack |
| W4 | ZT kubeadm token 2 h expiry | **encoded** | `bootstrap-token-keeper` CronJob (already in `dpf-zt-cluster`) + DPUServiceCredentialRequest `ovn-dpu` duration `2160h` |
| W5 | DPUNode external-reboot annotation | **encoded** | `dpunode-external-reboot-acker` CronJob added to `dpf-zt-cluster` |
| W6 | Palette OVN-K NodePort gateway defect | encoded | DPUFlavor `ovs.rawConfigScript` sets `br-dpu external-ids:bridge-uplink=p0` + Egress-Glue `dpf-brdpu-shim` |
| W7 | Both-node dpu-host blocker (kamaji deadlock) | **OPEN (high)** | ZT *requires* kamaji; `useControlPlaneAsWorker: false` keeps `.90` CP-only |
| W8 | `.240` tenant-API VIP plumbing | encoded (opt-in) | Egress-Glue `vip240-arp.service` + `vip240-proxy.service` |
| W9 | DPU oob unicast dead | encoded (opt-in) | Egress-Glue `dpf-brdpu-shim.service` |
| W10 | OVN zone mismatch / ghost Node | encoded | CP-Configs overlay `ovn-zone-label-controller.yaml` (Deployment) |
| W11 | DPU components hard-coded ClusterIP | **OPEN (medium)** | Operator-side; can't patch from profile. `dpunode-discovery-daemonset` + `host-prep` partially mitigate |
| W12 | Host VF renames | encoded (opt-in) | Egress-Glue `dpf-vf-rename.service` |
| W13 | Pod MTU from host-cluster OVN ConfigMap | encoded | CP-Configs overlay `mtu-configmap-patch.yaml` Job |
| W14 | HBN pod malformed networks annotation | **OPEN (low)** | Payload serviceDaemonSet annotation ships fully-namespaced — avoids webhook re-injection steady state |
| W15 | DPU clock skew | encoded (opt-in) | Egress-Glue `dpf-dpu-clock.service` |
| W16 | Non-durable boot state | encoded | DPUFlavor `grub.kernelParameters` hugepages=3072 + Egress-Glue `dpf-runtime-fixup.service` |

**Open gaps under ZT: 4** (W1 medium, W7 high, W11 medium, W14 low). Same count as v1 but composition is different — W3 and W4 (v1 claimed obviated by HT) are now encoded via reinstated `dpf-zt-cluster` manifests rather than counted as open.

## D1.8 Verification

| # | Check | Command | Source file |
|---|---|---|---|
| V1 | 4× eBGP Established to leaf AS 65001 | tenant: `kubectl --kubeconfig=<tenant> -n dpf-operator-system exec ds/doca-hbn -- nv show vrf default router bgp neighbor` | `results/mtu9000-hbn/bgp-ecmp-state.txt` |
| V2 | ECMP multipath route | tenant `kubectl … exec ds/doca-hbn -- ip route show 11.0.0.0/24` — two next-hops per prefix | same |
| V3 | `hw-offload=true` active | tenant `ovs-vsctl get Open_vSwitch . other_config:hw-offload` → `true`; `tc filter show dev p0` shows `in_hw` | DPUFlavor `ovs.rawConfigScript` |
| V4 | Single-pair ≥ 36 Gbps (jumbo) | host-cluster `bash scripts/run_pod_accelerated.sh` | `results/mtu9000-hbn/matrix_v2/iperf3_1pair_*.txt` |
| V5 | 8-pair aggregate ≥ 75 Gbps, ~50/50 split | host-cluster `run_pod_accelerated.sh --pairs 8` | `agg-bandwidth-test.txt`, `per-uplink-distribution.txt` |
| V6 | Host CPU sys+soft < 7 % at line rate | `slice_host_mpstat.sh && make_charts.py` | `host_mpstat_*.csv` |
| V7 | DPU Arm CPU flat during bench | tenant `kubectl … exec ds/doca-hbn -- top -bn1` | `dpu_top.txt` |
| V8 | Sub-second BGP failover | tenant `kubectl … exec ds/doca-hbn -- nv action set interface p0_if link down` mid-flow | `failover-test.txt` |

Note: V1, V2, V3, V7, V8 need `--kubeconfig=<tenant>` under ZT because doca-hbn DS lives in the kamaji-hosted tenant. V4, V5, V6 unchanged — bench pods are on the host cluster.

## D1.9 `scripts/dpf_deploy.py` delta

```python
INFRA_OVNK_HBN_ZT_UID         = "<NEW_INFRA_ZT_UID>"
ADDON_OVNK_HBN_PAYLOAD_ZT_UID = "<NEW_PAYLOAD_ZT_UID>"
ADDON_OVNK_HBN_OVERLAY_ZT_UID = "<NEW_OVERLAY_ZT_UID>"
ADDON_OVNK_HBN_GLUE_ZT_UID    = "<NEW_GLUE_ZT_UID>"

PROFILE_VARS[INFRA_OVNK_HBN_ZT_UID] = {
    "K8sPodCIDR": "10.233.64.0/18", "K8sServiceCIDR": "10.233.0.0/18",
    "PodMTU": "8940", "FabricMTU": "9216", "HbnSwpMTU": "9000",
    "controlPlaneInterface": "enp129s0f0", "controlPlaneVIP": "172.16.30.244",
    "dpuOobPassword": "Welcome2spectr0!",
    "dpfDiscoveryStartIP": "172.16.30.33", "dpfDiscoveryEndIP": "172.16.30.36",
    "OVNK_HELM_REPO": "oci://ghcr.io/mellanox/charts", "OVNK_CHART_TAG": "v25.10.0",
}
PROFILE_VARS[ADDON_CP_CONFIGS_UID]["PodMTU"] = "8940"  # for mtu-configmap-patch carry-up

PROFILE_VARS[ADDON_OVNK_HBN_OVERLAY_ZT_UID] = {
    "DPU": "enp14s0", "DPUNumVFs": "46", "PodMTU": "8940",
    "OVNK_HELM_REPO": "oci://ghcr.io/mellanox/charts", "OVNK_CHART_TAG": "v25.10.0",
}
PROFILE_VARS[ADDON_OVNK_HBN_PAYLOAD_ZT_UID] = {
    "BFB_URL": "https://content.mellanox.com/BlueField/BFBs/Ubuntu24.04/bf-bundle-3.2.1-34_25.11_ubuntu-24.04_64k_prod.bfb",
    "DPUNumVFs": "46",
    "HBN_HELM_REPO": "https://helm.ngc.nvidia.com/nvidia/doca",
    "OVNK_HELM_REPO": "oci://ghcr.io/mellanox/charts", "OVNK_CHART_TAG": "v25.10.0",
    "FabricMTU": "9216", "HbnSwpMTU": "9000", "PodMTU": "8940",
    "HbnPool1CIDR": "172.16.97.0/24", "HbnLoopbackCIDR": "11.0.0.0/24",
    "DPU1_HOSTNAME_PATTERN": "*mt24326005fn*",
    "DPU1_HOSTNAME": "dpu-node-mt24326005fn-mt24326005fn",
    "DPU1_BGP_ASN": "65010",
    "DPU1_P0_PEER_IP": "172.16.97.240", "DPU1_P0_LOCAL_IP": "172.16.97.241/31",
    "DPU1_P1_PEER_IP": "172.16.97.248", "DPU1_P1_LOCAL_IP": "172.16.97.249/31",
    "DPU1_POOL1_CIDR": "172.16.97.8/29",
    "DPU2_HOSTNAME_PATTERN": "*mt2439600dak*",
    "DPU2_HOSTNAME": "dpu-node-mt2439600dak-mt2439600dak",
    "DPU2_BGP_ASN": "65020",
    "DPU2_P0_PEER_IP": "172.16.97.244", "DPU2_P0_LOCAL_IP": "172.16.97.245/31",
    "DPU2_P1_PEER_IP": "172.16.97.250", "DPU2_P1_LOCAL_IP": "172.16.97.251/31",
    "DPU2_POOL1_CIDR": "172.16.97.0/29",
}
PROFILE_VARS[ADDON_OVNK_HBN_GLUE_ZT_UID] = {
    "enableEgressGlue": "true", "enableTinyproxy": "false",
    "tenantApiVIP": "172.16.30.240", "kamajiBackendIP": "172.16.30.91",
}

CLUSTER_CONFIGS["dpf-ovnk-hbn-zt"] = {
    "description": "ZT-mirroring: OVN-K primary CNI + DOCA HBN (numbered /31 eBGP, ECMP) — §7 reproducer",
    "infra_profile":  INFRA_OVNK_HBN_ZT_UID,             # per-cluster override of INFRA_PROFILE_UID
    "addon_profiles": [
        ADDON_CP_CONFIGS_UID,                            # REUSE 69b7039ae8451ebc583d6a13
        ADDON_OVNK_HBN_OVERLAY_ZT_UID,                   # NEW 4-manifest overlay
        ADDON_OVNK_HBN_PAYLOAD_ZT_UID,                   # NEW payload
        ADDON_OVNK_HBN_GLUE_ZT_UID,                      # NEW opt-in glue
    ],
}
```

Structural changes to `dpf_deploy.py`:
1. `build_cluster_payload()` reads `config.get("infra_profile", INFRA_PROFILE_UID)` instead of the global
2. `controlPlaneEndpoint.host` reads from `PROFILE_VARS[infra]["controlPlaneVIP"]` instead of hard-coded
3. New subcommand `python3 scripts/dpf_deploy.py post-profiles --mode zt` that POSTs the 3 new profile JSONs from `profile-defs/zt/` and writes UIDs back

---

# Deliverable 2 — Host-Trusted variant + A/B benchmark plan

## D2.A The host-trusted profile

The original v1 plan was a host-trusted plan — the wrong baseline for §7 reproduction but a valid host-trusted plan in its own right. It becomes Deliverable 2 with these deltas:

### D2.A.1 Reusable as-is from v1

| v1 section | Status |
|---|---|
| § 1 Summary | Reuse — s/"reproduces what we measured"/"second variant for A/B"/ |
| § 2 Pack stack | Reuse verbatim (`edge-rke2 1.34.2`, `cni-ovn-kubernetes` 67fe…, `csi-longhorn 1.10.1`, `nvidia-dpf-prereqs/operator/network-operator` 25.10.1, network-op UID `693811208c34d8a8dec7e34a` AICP variant) |
| § 4.1 Profile A (RKE2 + OVN-K + host-trusted DPF) | Reuse, **keep** explicit `deploymentMode: host-trusted` in operator values |
| § 4.2 Profile B HBN Payload | Reuse, **keep** `dpuMode: host-trusted` |
| § 4.3 Profile C CP-Configs (8 manifests fork) | **Drop the profile entirely**. Under HT no kamaji-tenant cluster — DPUCluster CR isn't needed; nic-cluster-policy and sriov-policy ship inline with payload. CP-Configs `69b7039a…` is dropped. MTU + zone-label jobs stay as a **smaller** 3-manifest overlay |
| § 4.4 Egress-Glue | Reuse. Tinyproxy ON by default (PHASE6 confirms HT rebuild required it); `vip240-*` OFF by default (no kamaji backend) |
| § 5 Customer variables | Remove `controlPlaneInterface`/`controlPlaneVIP` from CP-Configs req (Infra-only under HT); remove `dpfDiscoveryStartIP`/`EndIP`/`dpuOobPassword` (no Redfish discovery) |
| § 6 Workaround coverage map | W3 and W4 genuinely don't apply under HT — count stays at 4 open gaps but W7 mitigation differs |
| § 7 Verification | Drop the `--kubeconfig=<tenant>` qualifier on V1/V2/V3/V7/V8 — doca-hbn DS runs in host cluster under HT |
| § 8 dpf_deploy.py delta | Reuse, rename UIDs to `_HT` suffix. CP-Configs UID dropped from `addon_profiles` |

### D2.A.2 W7 (kamaji deadlock) — host-trusted handling

v1 called W7 "high severity / cannot be encoded". Under **host-trusted** there's no kamaji — DPU nodes are direct host-cluster workers. So W7 in its ZT form goes away. **But:**

1. `nvidia-dpf-operator` values: `kamajiClusterManager.disable: true` — turn the kamaji-tenant subchart off (v1 didn't set this; preserved kamaji default-on). **Add this** to D2.A's operator values.
2. PHASE6_EGRESS_BLOCKER kamaji-in-KVM bridge **does not apply** under pure HT — it was needed in PHASE6 because that was a mixed setup (HT operator but still trying to host kamaji on `.90`). Pure HT turns kamaji off entirely.
3. Document in `CONFIG_REQUIREMENTS.md` as a deployment-time decision: ZT (kamaji on, 2-cluster) or HT (kamaji off, 1-cluster). Mixed is unsupported.

> v1's prescription of `kamajiPlacement: external-vm` is **revised** to `kamajiClusterManager.disable: true`. There's no `kamajiPlacement` field in the operator schema; v1 was speculating.

### D2.A.3 Host-trusted profile structure (final)

```
Deliverable 2.A — Host-Trusted Profile family (3 profiles, not 4)
├── Infra:         dpf-ovnk-hbn-infra-ht  (NEW: fork of AICP-edge-infra-nvidia-stack-host-trusted-v2)
│                  Same as v1 § 4.1, with:
│                  + nvidia-dpf-operator.kamajiClusterManager.disable: true
│                  + dpf-operator-config inline manifest: spec.deploymentMode: host-trusted
├── Payload:       dpf-ovnk-hbn-payload-ht  (NEW)
│                  Same as v1 § 4.2, dpuMode: host-trusted preserved
│                  + inline manifests: nic-cluster-policy, sriov-network-node-policy (PF0+PF1 both),
│                    ghcr-pull-secret, ghcr-argocd-repo
├── Overlay:       dpf-ovnk-hbn-cpconfigs-overlay-ht  (NEW, only 3 manifests)
│                  resource-injector + mtu-configmap-patch + ovn-zone-label-controller
└── Egress-Glue:   dpf-ovnk-hbn-egress-glue-ht  (NEW, opt-in)
                   tinyproxy ON by default; vip240-* OFF by default
```

## D2.B A/B benchmark plan

### D2.B.1 Test matrix

| Metric | Source script | Mode-A (ZT) target | Mode-B (HT) target |
|---|---|---|---|
| TCP 1/8/16-stream | `run_pod_accelerated.sh` | 36.6 / 37.0 / 36.8 Gbps ± 0.4–0.7 | ±1 Gbps |
| ECMP 1→32 flows single pair | `--flow-sweep` | 34.2→37.1 Gbps | ±1 Gbps |
| Aggregation 1/2/4/6/8 pairs | `--pairs 1,2,4,6,8` | 36.3/70.1/76.3/69.7/78.0 Gbps | ±2 Gbps at plateau |
| Per-uplink ECMP balance | aggregate parser | gpu1 51/49, gpu2 50/50 at 8-pair | ±5 pts |
| Sub-second BGP failover | `--failover` | 36.3 Gbps on p1 alone, hold-time 9 s | recovery ±2 s |
| Host CPU sys+soft at line rate | `slice_host_mpstat.sh` | `.90` 5.94/3.97 % at 8-stream | ±0.5 pts |
| DPU Arm CPU under load | new `slice_dpu_mpstat.sh` | `.29` 7.82/0.78 % at 8-stream | ±1 pt |
| sockperf p99/p99.9/p99.99 | sockperf 4×60s | 88.7/132.9/277.5 µs | **most-likely-to-differ** (see D2.B.4) |
| sockperf size sweep | offload-fraction reproducer | 0.06→5.0 Gbps as txn grows 256B→64KB | ±10 % per size |

n=4 runs × 60 s each, run 1 warmup, 30 s idle between.

### D2.B.2 Test methodology

Reuse existing `scripts/run_pod_accelerated.sh`, `scripts/slice_host_mpstat.sh`, `scripts/make_charts.py`. New/modified:
1. `run_pod_accelerated.sh` — add `--label` flag for `results/ab/<mode>/<metric>/` tagging
2. `slice_host_mpstat.sh` — add `--mode` for output filename
3. `make_charts.py` — `--ab-pair zt,ht` for 2-bar grouped charts + delta overlay
4. **New** `scripts/slice_dpu_mpstat.sh` — DPU Arm mpstat slicer (one-time investment, benefits future runs regardless)

### D2.B.3 Switch-over procedure

Per mode flow: teardown → DPU state-clean → BFB reflash → cluster-create-target-mode → wait-Running → V1–V8 verify → matrix execute → artifact capture.

**Wall-clock per mode (end-to-end clean rebuild → bench complete):**

| Step | ZT | HT |
|---|---|---|
| Teardown + Palette cleanup | 0.5 h | 0.5 h |
| DPU state-clean + BFB flash (2× DPUs) | 1.0 h | 1.0 h |
| Cluster create + reach Running | 1.0 h | 0.7 h |
| W3/W4 cron-jobs settle (ZT only) | 0.25 h | 0 |
| V1–V8 verification | 0.25 h | 0.25 h |
| Test matrix execution | 1.5 h | 1.5 h |
| Artifact capture + sanity diff | 0.5 h | 0.5 h |
| **Per-mode subtotal** | **5.0 h** | **4.5 h** |
| **Full A/B (both)** | **9.5 h** | |

Reference: Appendix B.4 budgets 40–80 engineer-hours for a clean rebuild without the workaround catalog. 9.5 h assumes we **have** the catalog (encoded as profile manifests per D1/D2.A) — 4–5× faster than cold rebuild. Reserve 3× buffer (~30 hr total wall-clock) for first-pass debugging; converge to 9.5 h on repeats.

### D2.B.4 Expected outcomes

**Hypothesis: ZT and HT are equivalent on bulk dataplane metrics.** Dataplane is identical — OVS-DOCA eswitch, hw-offload, geneve, HBN BGP/ECMP, same DPUFlavor nvconfig.

**Where I expect them to differ:**

1. **Host CPU under bench load (most likely).** ZT has more cross-plane control-plane chatter: bootstrap-token-keeper / install-interface-fixer / external-reboot-acker CronJobs, kamaji etcd heartbeats, OVN-K ghost-Node label-watcher. Expected: **ZT +1 pt total busy at idle, +0.5 pt at line rate**.
2. **Sockperf p99.9 tail latency (second-most likely).** Kamaji etcd fsync calls hit local-path on `.90`; can preempt host softirq. Expected: **ZT +5–15 µs at p99.9 vs HT**.
3. **First-pod scheduling time** (one-shot). ZT kamaji tenant must reach Ready first. +1–3 min bring-up.

**Statistically indistinguishable:** TCP throughput, 4-uplink aggregation, per-uplink balance, BGP failover, DPU Arm CPU, sockperf p50/p99.

### D2.B.5 Decision criteria — when to recommend HT as customer default

Ship **HT as default** if **all** of:
1. Host CPU at line rate: `(ZT − HT) busy% ≤ 0.5 pts` AND `(ZT − HT) sys+soft ≤ 0.3 pts` at 8/16-stream, both hosts
2. Sockperf p99.9: `(ZT − HT) ≤ 10 µs` (95 % CI overlap)
3. Sockperf p99.99: `(ZT − HT) ≤ 30 µs`
4. Throughput parity: 4-uplink aggregate at 8 pairs `|ZT − HT| ≤ 2 Gbps`
5. BGP failover: surviving-uplink throughput `|ZT − HT| ≤ 1 Gbps`; hold-time `±2 s`
6. No single-metric regression > 10 % vs ZT

If any fails: ship ZT as default. The §7 measurements stand. If all six pass: HT becomes the recommended default; ZT remains for customers needing kamaji-tenant isolation.

### D2.B.6 Risk register

| Risk | Likelihood | Mitigation |
|---|---|---|
| DPU clock skew across teardowns | medium | `dpf-dpu-clock.service` every 30 min; record offset at start of each run |
| BFB flash wears DPU eMMC (2 flashes/cycle, 8+ for confidence) | low-medium | BMC multipart upload (different controller path than rshim); limit re-runs to 2 cycles unless inconsistent |
| Kamaji `.240` VIP SPOF during ZT — keepalived election storm | medium | Pin `virtualRouterID: 126`, priority 100 on `.90`; disable IPMI watchdog during bench |
| OVS hw-offload bit silently flips between modes | low | V3 must pass before *every* matrix run, not just per bring-up |
| HBN hostnamePattern fails after BFB reflash (MAC-derived hostname change) | low-medium | Capture `kubectl get nodes` before bench; assert wildcard match; auto-update PROFILE_VARS if mismatched |
| ZT host-pod created before DPU node joins tenant → schedules to no-DPU host | medium | Add `kubectl wait --for=condition=Ready dpu/$DPU` on tenant before bench |
| RKE2 1.34.2 CRI socket change (HT only) | medium | Smoke-test `nsenter -t 1 -m -p -n` in host-prep DS before A/B; fall back to edge-k8s 1.33.6 + kubeadm skipPhases if it fails |
| OVN-K resource-injector chart drift between modes | low | Pin both to identical `v25.10.0` by image digest, not tag |

### D2.B.7 A/B deliverables

| Artifact | Form | Location |
|---|---|---|
| `BENCHMARK_REPORT.md` § 7.10 "Mode comparison: ZT vs HT" | New subsection after § 7.9; 5-column table; n=4 per arm | existing file |
| `results/ab/zt/` and `results/ab/ht/` raw trees | Mirror of `results/mtu9000-hbn/matrix_v2/` layout | new dirs |
| `results/ab/mode-comparison.csv` | Long-form: `metric, mode, run_idx, value, unit, stdev_within_arm` | new file |
| `results/charts/mode_comparison_*.png` | 2-bar grouped charts per metric | existing dir |
| `CUSTOMER_ONEPAGER.md` v2 | One paragraph: "Both modes deliver equivalent dataplane performance; we recommend [ZT|HT] as default for…" | existing file |
| `CONFIG_REQUIREMENTS.md` § "Mode selection" | New decision tree section near the top | existing file |

### D2.B.8 Pass/fail report structure

For each metric: ZT mean ± σ, HT mean ± σ, ΔAB ± propagated σ, Welch's t-test p-value, decision-rule outcome. **Topline verdict line**: one of "HT meets all 6 criteria — recommend as customer default" / "HT fails criterion N — recommend ZT as default". **Customer-facing caveat**: ZT-only vars list (D1.6) vs smaller HT list.

---

# Cross-deliverable open questions

1. **OVN-K resource-injector chart version.** Both modes pin `OVNK_CHART_TAG: v25.10.0`. The `cni-ovn-kubernetes` Palette pack is upstream OSS (no resource-injector subchart) — lands as `HelmChart` CR in CP-Configs overlay both modes. **Open:** verify `oci://ghcr.io/mellanox/charts` is pullable from the bench fabric; if not, mirror to `harbor.dreamworx.nl` and pin digest.
2. **Network Operator UID confusion.** ZT uses `6951d8be0689c1e30fa160f2` (`network-operator`); HT uses `693811208c34d8a8dec7e34a` (`nvidia-network-operator`). Same tag 25.10.0. **Open:** same chart published twice with different pack names, or genuinely different builds? File Palette pack-publish question. Until resolved, pin each mode to its own UID.
3. **`packs-spectro.dreamworx.nl` registry status.** HTTP 500 on `/v1/registries/oci/{uid}`. Doesn't block POSTing the profile but blocks long-term confidence.
4. **kamaji etcd local-path on `.90` — is the fsync latency really a CPU/p99.9 nondeterminism source?** Load-bearing testable claim in D2.B.4. If A/B disproves it, ZT-vs-HT is indistinguishable and D2.B.5 criterion 1 collapses. Honest framing: A/B may produce "no difference" — that's a valid customer outcome ("pick mode by security posture; perf is the same").
5. **Tenant kubeconfig exfil for V1/V2/V3/V7/V8 under ZT.** Add helper `scripts/get_tenant_kubeconfig.sh`: `kubectl -n dpu-cplane-tenant1 get secret dpu-cplane-tenant1-admin-kubeconfig -o jsonpath='{.data.admin\.conf}' | base64 -d > /tmp/tenant.kubeconfig`. Document the assumed cluster-name `dpu-cplane-tenant1`.
6. **W7 under ZT in production:** §7 lab had 2 nodes (`.90` CP-only + `.253` worker). For customers with 3+ nodes the topology is more flexible (kamaji on dedicated CP, dpu-hosts elsewhere). Don't over-constrain `useControlPlaneAsWorker: false`; convert to per-cluster var with sane defaults.

---

### Critical Files for Implementation

- `scripts/dpf_deploy.py` — adds `dpf-ovnk-hbn-zt` and `dpf-ovnk-hbn-ht` to `CLUSTER_CONFIGS`; per-cluster `infra_profile` override; new `post-profiles` subcommand; new `PROFILE_VARS` blocks for ZT and HT.
- `/tmp/palette-pack-values/infra-nvidia-dpf-operator-25.10.1-values.yaml` — ZT operator values block (lines 30–34: `installViaRedfish` uncommented) is the load-bearing diff vs v1. Source of truth for Deliverable 1's Profile A operator pack.
- `/tmp/palette-pack-values/ht2-nvidia-dpf-deployment.yaml` + `_broken-hbn-values.yaml` — structural reference for both deliverables' payload values.
- `profile-addons-accelerated/10-dpu-install-interface-fixer.yaml` and `11-dpunode-external-reboot-acker.yaml` — verbatim inline manifests added to the ZT `dpf-zt-cluster` pack (Deliverable 1, encodes W3 and W5).
- `BENCHMARK_REPORT.md` §§ 7.0–7.9 (A/B target metric definitions), § B.2 (workaround catalog the profile encodes), § 7.10 (new subsection Deliverable 2.B.7 lands).
