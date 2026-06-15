# `profile-defs/zt/` — Zero Trust HBN cluster profile sources

Source-of-truth for the four Palette cluster profiles that reproduce the § 7 HBN benchmarks under **Zero Trust**. See [`HBN_PROFILE_PLAN_V2.md`](../../HBN_PROFILE_PLAN_V2.md) for the full design rationale (this directory implements Deliverable 1, § D1.5).

## Layout

```
profile-defs/zt/
├── README.md                      this file
├── 01-infra-zt/                   Profile A: dpf-ovnk-hbn-infra-zt (cluster type, fork of 69f25bfa…)
│   ├── profile.yaml               metadata + pack ordering + per-pack value/manifest refs
│   ├── values/                    one YAML per pack values block; assembled by build script
│   └── manifests/                 inline manifests for the dpf-zt-cluster manifest pack
├── 02-payload-zt/                 Profile B: dpf-ovnk-hbn-payload-zt (addon, NEW values)
│   ├── profile.yaml
│   └── values/
├── 03-cpconfigs-overlay-zt/       Profile C′: 4-manifest overlay layered onto 69b7039a…
│   ├── profile.yaml
│   ├── values/
│   └── manifests/
└── 04-egress-glue-zt/             Profile D: opt-in egress glue (vip240, runtime-fixup, …)
    ├── profile.yaml
    ├── values/
    └── manifests/
```

Each `profile.yaml` is a thin manifest that the build script (`scripts/build_palette_profile.py`) walks to produce a single POST-ready JSON. See **Building & POSTing** below.

## Building & POSTing

```bash
# 1. Render each profile to /tmp/<name>.json:
python3 scripts/build_palette_profile.py profile-defs/zt/01-infra-zt > /tmp/dpf-ovnk-hbn-infra-zt.json
python3 scripts/build_palette_profile.py profile-defs/zt/02-payload-zt > /tmp/dpf-ovnk-hbn-payload-zt.json
python3 scripts/build_palette_profile.py profile-defs/zt/03-cpconfigs-overlay-zt > /tmp/dpf-ovnk-hbn-cpconfigs-overlay-zt.json
python3 scripts/build_palette_profile.py profile-defs/zt/04-egress-glue-zt > /tmp/dpf-ovnk-hbn-egress-glue-zt.json

# 2. POST each to Palette:
for f in /tmp/dpf-ovnk-hbn-*-zt.json; do
  curl -s -X POST -H "ApiKey: $PALETTE_API_KEY" -H "ProjectUid: $PALETTE_PROJECT_UID" \
    -H "Content-Type: application/json" --data @"$f" \
    https://api.spectrocloud.com/v1/clusterprofiles
done
# returns {uid: <new_profile_uid>} per POST; capture and stash for scripts/dpf_deploy.py
```

The build script:
- Reads `profile.yaml` for metadata + pack list.
- For each pack, embeds the matching `values/<pack-name>.yaml` as the `values` field (string).
- For each manifest pack, walks `manifests/*.yaml` (lex sort) and embeds each as `{name, content}`.
- Substitutes `{{ .spectro.var.* }}` placeholders verbatim (Palette resolves them at cluster-create time).
- Emits a single POST-ready JSON to stdout.

## Status

| Profile | Status | Notes |
|---|---|---|
| 01-infra-zt | **skeleton** | profile.yaml shell + value snapshots cited; needs full assembly |
| 02-payload-zt | **skeleton** | the meat — DPUFlavor + DPUDeployment + DPUServiceConfig + numbered /31 BGP startup YAML. Largest single values block |
| 03-cpconfigs-overlay-zt | **complete** | 4 manifests authored |
| 04-egress-glue-zt | **complete** | single DaemonSet manifest authored |

See [`HBN_PROFILE_PLAN_V2.md`](../../HBN_PROFILE_PLAN_V2.md) § D1.5 for the per-profile spec details and § D1.7 for the workaround-coverage map each profile implements.

## Source snapshots

All upstream pack-value templates were captured by the planning agent (read-only API enumeration) to `/tmp/palette-pack-values/`. The 6 most load-bearing ones referenced in this directory:

- `infra-edge-native-byoi-2.1.0-values.yaml` — Profile A OS pack
- `infra-edge-k8s-1.33.6-values.yaml` — Profile A K8s pack (then add the skipPhases + cni:none diff)
- `cni-ovn-kubernetes-values.yaml` — Profile A CNI pack
- `infra-nvidia-dpf-operator-25.10.1-values.yaml` — Profile A DPF operator pack (**keep `installViaRedfish` uncommented**)
- `infra-zt-dpf-zt-cluster--*.yaml` — the 8 carry-over inline manifests for the `dpf-zt-cluster` pack
- `ht2-nvidia-dpf-deployment.yaml` — structural reference for Profile B (strip AICP, set numbered BGP, flip `dpuMode: zero-trust`)

DO NOT copy `_broken-hbn-values.yaml` (the broken `698dd2dd…` addon values block) into any profile here. Cited only as a "what NOT to do" reference.
