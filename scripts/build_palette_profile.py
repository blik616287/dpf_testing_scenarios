#!/usr/bin/env python3
"""Build a POST-ready Palette cluster-profile JSON from a directory.

Layout:
  <profile-dir>/
    profile.yaml          metadata + pack ordering
    values/<pack>.yaml    optional, one per pack
    manifests/*.yaml      optional, for inline-manifest packs (lex order)

profile.yaml shape (annotated):

  name: dpf-ovnk-hbn-infra-zt
  description: "..."
  type: cluster                       # or "add-on"
  cloudType: edge-native
  labels:
    tier: infra
    dpf-mode: zero-trust
  version: "1.0.0"
  packs:
    - name: edge-k8s
      type: oci                       # or "manifest"
      layer: k8s                      # os|k8s|cni|csi|addon
      registryUid: 64eaff453040297344bcad5d
      packUid: 696d0ee4ef11f75302dbdaff
      tag: "1.33.6"
      valuesFile: edge-k8s.yaml       # under values/  (omit -> empty values)
    - name: dpf-zt-cluster
      type: manifest
      layer: addon
      values: |                       # inline values block, multi-line string
        pack:
          spectrocloud.com/install-priority: "20"
      manifestsGlob: "manifests/*.yaml"  # everything under manifests/ in lex order

Outputs a single JSON to stdout suitable for `POST /v1/clusterprofiles`.
Substitutes nothing — Palette resolves `{{ .spectro.var.* }}` at cluster-create time.
"""

import argparse, glob, json, os, sys
import yaml


def load_yaml(path):
    with open(path) as f:
        return yaml.safe_load(f)


def load_text(path):
    with open(path) as f:
        return f.read()


def build_pack(profile_dir, pack):
    """Render one pack entry to the Palette pack shape."""
    out = {
        "name": pack["name"],
        "type": pack["type"],
        "layer": pack["layer"],
    }
    # OCI-only fields
    for k in ("registryUid", "packUid", "tag"):
        if k in pack:
            out[k] = pack[k]

    # values: inline `values` field beats `valuesFile`
    if "values" in pack:
        out["values"] = pack["values"]
    elif "valuesFile" in pack:
        out["values"] = load_text(os.path.join(profile_dir, "values", pack["valuesFile"]))
    else:
        out["values"] = ""

    # manifests
    if "manifestsGlob" in pack:
        pat = os.path.join(profile_dir, pack["manifestsGlob"])
        files = sorted(glob.glob(pat))
        if not files:
            print(f"warning: no manifests matched {pat!r}", file=sys.stderr)
        out["manifests"] = [
            {
                "name": os.path.splitext(os.path.basename(p))[0],
                "content": load_text(p),
            }
            for p in files
        ]
    elif "manifests" in pack:
        # explicit list of manifest filenames in declaration order
        out["manifests"] = [
            {
                "name": os.path.splitext(os.path.basename(m))[0],
                "content": load_text(os.path.join(profile_dir, "manifests", m)),
            }
            for m in pack["manifests"]
        ]

    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("profile_dir", help="directory containing profile.yaml")
    args = ap.parse_args()

    profile_dir = os.path.abspath(args.profile_dir)
    profile_path = os.path.join(profile_dir, "profile.yaml")
    if not os.path.exists(profile_path):
        sys.exit(f"error: {profile_path} not found")
    p = load_yaml(profile_path)

    payload = {
        "metadata": {
            "name": p["name"],
            "labels": p.get("labels", {}),
        },
        "spec": {
            "version": p.get("version", "1.0.0"),
            "template": {
                "type": p["type"],
                "cloudType": p.get("cloudType", "edge-native"),
                "packs": [build_pack(profile_dir, pk) for pk in p["packs"]],
            },
        },
    }
    if "description" in p:
        payload["metadata"]["annotations"] = {"description": p["description"]}

    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
