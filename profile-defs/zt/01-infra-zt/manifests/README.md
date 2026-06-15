# Profile A `dpf-zt-cluster` inline manifests — population checklist

10 manifests in lex order — the 8 verbatim NetOp-v2 carry-overs + 2 new ZT CronJobs for W3 / W5.

| File | Action | Source |
|---|---|---|
| `00-dpu-cluster.yaml` | verbatim copy | `/tmp/palette-pack-values/infra-zt-dpf-zt-cluster--dpu-cluster.yaml` |
| `01-dpu-bmc-password.yaml` | verbatim copy | `/tmp/palette-pack-values/infra-zt-dpf-zt-cluster--dpu-bmc-password.yaml` |
| `02-dpu-discovery.yaml` | verbatim copy | `/tmp/palette-pack-values/infra-zt-dpf-zt-cluster--dpu-discovery.yaml` |
| `03-host-prep.yaml` | verbatim copy | `/tmp/palette-pack-values/infra-zt-dpf-zt-cluster--host-prep.yaml` |
| `04-dpuflavor-mode-rewrite.yaml` | verbatim copy | `/tmp/palette-pack-values/infra-zt-dpf-zt-cluster--dpuflavor-mode-rewrite.yaml` |
| `05-bootstrap-token-keeper.yaml` | verbatim copy | `/tmp/palette-pack-values/infra-zt-dpf-zt-cluster--bootstrap-token-keeper.yaml` |
| `06-dpunode-alias-controller.yaml` | verbatim copy | `/tmp/palette-pack-values/infra-zt-dpf-zt-cluster--dpunode-alias-controller.yaml` |
| `07-dpunode-discovery-daemonset.yaml` | verbatim copy | `/tmp/palette-pack-values/infra-zt-dpf-zt-cluster--dpunode-discovery-daemonset.yaml` |
| **`08-dpu-install-interface-fixer.yaml`** | **verbatim copy (NEW for this profile)** | `profile-addons-accelerated/10-dpu-install-interface-fixer.yaml` (B.2 W3) |
| **`09-dpunode-external-reboot-acker.yaml`** | **verbatim copy (NEW for this profile)** | `profile-addons-accelerated/11-dpunode-external-reboot-acker.yaml` (B.2 W5) |
