# Profile A values — population checklist

Each YAML in this directory is the values block for the corresponding pack in `profile.yaml`. Most are **verbatim copies** of upstream pack-value snapshots; only `edge-k8s.yaml` and `cni-ovn-kubernetes.yaml` need authored overrides.

Source snapshots under `/tmp/palette-pack-values/` (captured by the Plan agent, read-only API).

| File | Action | Source |
|---|---|---|
| `edge-native-byoi.yaml` | verbatim copy | `infra-edge-native-byoi-2.1.0-values.yaml` |
| **`edge-k8s.yaml`** | **base + diff** | `infra-edge-k8s-1.33.6-values.yaml` + § D1.5.1.a overlay (`skipPhases: [addon/kube-proxy]` on init+join, `cni.preInstalled: true`, K8sPodCIDR/K8sServiceCIDR spectro vars) |
| **`cni-ovn-kubernetes.yaml`** | **authored** | OVN-K override block from § D1.5.1.b (tags ovnkube-single-node-zone, ovnkube-control-plane, ovnkube-node-dpu, ovnkube-node-dpu-host; mtu spectro var; gatewayMode shared; gatewayOpts derive-from-mgmt-port; etc.) |
| `csi-longhorn.yaml` | verbatim copy | `infra-csi-longhorn-1.10.0-values.yaml` |
| `nvidia-dpf-prereqs.yaml` | verbatim copy | `infra-nvidia-dpf-prereqs-25.10.1-values.yaml` |
| `nvidia-dpf-operator.yaml` | verbatim copy | `infra-nvidia-dpf-operator-25.10.1-values.yaml` — **CRITICAL**: keep `installInterface.installViaRedfish` block uncommented per lines 30–34 (this is the load-bearing diff vs v1's host-trusted snapshot) |
| `network-operator.yaml` | verbatim copy | `infra-network-operator-25.10.0-values.yaml` |

After populating these files, `python3 scripts/build_palette_profile.py profile-defs/zt/01-infra-zt > /tmp/infra.json` should produce a valid POST payload.
