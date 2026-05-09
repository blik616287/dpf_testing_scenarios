# DPF Zero Trust profile addons (extracted from the working fix)

These two files capture the host-prep + kamaji-side fixes that made the cluster
deploy end-to-end without manual intervention. They're meant to be merged into
the existing Spectro Cloud cluster profile rather than applied directly.

## 01-edge-native-byoi-stages.yaml

A drop-in replacement for the **`edge-native-byoi`** pack values in the agent
profile (`DPF Zero Trust Control Plane - Agent` / `DPF ZT CP-Agent NetOp v2`).

What it adds vs. the stock pack values:

- `initramfs` stage:
  - Inserts `pci=realloc` into `GRUB_CMDLINE_LINUX_DEFAULT` and runs `update-grub`.
    Required so BIOS allocates enough PCIe BAR for `sriov_totalvfs=46` instead of 16.
    Touches `/var/run/grub-needs-reboot` so an operator (or a later stage) knows a
    reboot is needed once.
- `boot.before` stages:
  - Writes `/etc/netplan/99-br-dpu-interfaces-mtu.yaml` — the Linux bridge `br-dpu`
    with `enp129s0f0` as a member, getting the host mgmt IP via DHCP.
  - Writes `/etc/netplan/99-dpu-sriov.yaml` — `virtual-function-count: 46` on both
    DPU PFs. **`delay-virtual-functions-rebind: false`** — important: the default
    `true` leaves PF0 VFs unbound from `mlx5_core` after `netplan apply`, which
    breaks both representor enumeration and the host's br-dpu peering.
  - Calls `netplan generate && netplan apply`.
- `boot.after` stages:
  - Original Longhorn-storage CP node tagging (kept).
  - Idempotent rebind of any unbound PF VFs (catches edge cases where netplan
    leaves them dangling).
  - Adds `enp14s0f0v0` (PF0 VF 0) as a member of `br-dpu`. This is the DPU OS's
    PCIe path through the host. Without it the DPU OS oob_net0 has no route to
    the management network from the host side.

## 02-tenant-bootstrap-token-keeper.yaml

A manifest to add to the **`dpf-zt-cluster`** pack alongside `dpu-cluster`,
`dpu-bmc-password`, `dpu-discovery`. Solves the kubeadm-join discovery failure:

```
could not find a JWS signature in the cluster-info ConfigMap for token ID "<id>"
```

DPF generates `kubeadm join` bfcfg with a 24h-TTL bootstrap token. If the DPU
takes longer than 24h to provision (BFB install + cloud-init + reach kamaji),
the token expires; `tokencleaner` deletes the Secret; `bootstrap-signer` removes
its `jws-kubeconfig-<id>` entry from `kube-public/cluster-info`. The DPU's
already-running `kubeadm-join` then fails forever.

The CronJob runs every 15 minutes inside `dpf-operator-system`, pulls the kamaji
tenant admin kubeconfig from the existing
`dpu-cplane-tenant1/dpu-cplane-tenant1-admin-kubeconfig` Secret, and patches
every `bootstrap-token-*` Secret's `expiration` to "now + 30 days". This keeps
`bootstrap-signer` writing the JWS signatures so the join handshake works.

Manifests included:
- `ServiceAccount/dpf-bootstrap-token-keeper`
- `Role/RoleBinding` granting read access to the tenant kubeconfig Secret
- `CronJob/dpf-bootstrap-token-keeper` running `bitnami/kubectl:1.34`

## Things still missing from the profile that we worked around manually

- **`node-role.kubernetes.io/worker=""` label on workers**: the
  `SriovNetworkNodePolicy bf3-p0-vfs` requires it. The original profile assumes
  it's set by the Kubernetes pack but `edge-k8s` doesn't. Either:
  - patch `edge-k8s` postKubeadmCommands to label `$(hostname)` if the node is
    not control-plane, or
  - extend the `dpf-zt-cluster` pack with a Job that labels worker pool nodes.
- **Single-host SR-IOV variance**: gpu1 originally had `sriov_totalvfs=16`
  because the `pci=realloc` kernel arg wasn't set. With (1) above this becomes
  a one-time first-boot problem; the `grub-needs-reboot` flag could drive an
  automatic warm reboot, but for safety we leave the reboot decision to the
  operator (a flag file is left behind to make it explicit).
