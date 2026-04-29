#!/usr/bin/env python3
"""
DPF A/B Testing Cluster Deployment Script

Deploys 3 edge-native clusters sequentially via Palette API for DPF performance testing:
  1. dpf-ovn-baseline      - Passthrough mode (no acceleration)
  2. dpf-ovn-accelerated   - OVN offloaded to BlueField DPU
  3. dpf-ovn-hbn           - OVN + HBN (BGP/ECMP) on BlueField DPU

Required environment variables:
  PALETTE_API_KEY       - Palette API key
  PALETTE_PROJECT_UID   - Palette project UID

Usage:
  python3 dpf_deploy.py create <cluster_name>   # Create one of the 3 clusters
  python3 dpf_deploy.py status <cluster_uid>     # Check cluster status
  python3 dpf_deploy.py delete <cluster_uid>     # Delete a cluster
  python3 dpf_deploy.py list                     # List all clusters in project
  python3 dpf_deploy.py hosts                    # List available edge hosts
"""

import argparse
import json
import sys
import time
import os
import urllib.request
import urllib.error

API_BASE = "https://api.spectrocloud.com/v1"
API_KEY = os.environ.get("PALETTE_API_KEY", "")
PROJECT_UID = os.environ.get("PALETTE_PROJECT_UID", "")

if not API_KEY or not PROJECT_UID:
    print("Error: Set PALETTE_API_KEY and PALETTE_PROJECT_UID environment variables.", file=sys.stderr)
    print("  export PALETTE_API_KEY='your-api-key'", file=sys.stderr)
    print("  export PALETTE_PROJECT_UID='your-project-uid'", file=sys.stderr)
    sys.exit(1)

# Profile UIDs
INFRA_PROFILE_UID = "69836cfbe0eb284f406fee60"   # DPF Zero Trust Control Plane - Agent
ADDON_CP_CONFIGS_UID = "69b7039ae8451ebc583d6a13" # Spectro-DPU-DPF-CP-Configs
ADDON_PASSTHROUGH_UID = "69834c1973ed315efeaed916" # DPF Zero Trust Use Case - Passthrough
ADDON_HBN_UID = "698dd2dd4b0c719b6c763605"        # DPF Zero Trust Use Case - DOCA HBN

# Variable values per profile (Phase 0 discovered)
PROFILE_VARS = {
    INFRA_PROFILE_UID: {
        "K8sPodCIDR": "100.64.0.0/18",
        "K8sServiceCIDR": "100.64.64.0/18",
        "NfsServer": "172.16.30.90",
        "NfsPath": "/dpf",
        "NfsShareSize": "10Gi",
        "controlPlaneInterface": "enp129s0f0",
        "controlPlaneVIP": "172.16.30.244",
        "dpuOobPassword": "Welcome2spectr0!",
        "dpfDiscoveryStartIP": "172.16.30.33",
        "dpfDiscoveryEndIP": "172.16.30.36",
    },
    ADDON_CP_CONFIGS_UID: {
        "dpuClusterInterface": "enp129s0f0",
        "dpuClusterIP": "172.16.30.244",
        "DPU": "enp14s0",
        "DPUNumVFs": "46",
    },
}

CLUSTER_CONFIGS = {
    "dpf-ovn-baseline": {
        "description": "OVN baseline - Passthrough mode (no DPF acceleration)",
        "addon_profiles": [ADDON_CP_CONFIGS_UID, ADDON_PASSTHROUGH_UID],
    },
    "dpf-ovn-accelerated": {
        "description": "OVN accelerated - DPF offload to BlueField DPU",
        "addon_profiles": [ADDON_CP_CONFIGS_UID],
    },
    "dpf-ovn-hbn": {
        "description": "OVN + HBN - DPF offload + BGP/ECMP routing on BlueField DPU",
        "addon_profiles": [ADDON_CP_CONFIGS_UID, ADDON_HBN_UID],
    },
}


def api_request(method, path, body=None):
    """Make an authenticated API request to Palette."""
    url = f"{API_BASE}{path}"
    headers = {
        "ApiKey": API_KEY,
        "ProjectUid": PROJECT_UID,
        "Content-Type": "application/json",
    }
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        body_text = e.read().decode()
        print(f"HTTP {e.code}: {body_text}", file=sys.stderr)
        sys.exit(1)


def get_profile_detail(uid):
    """Fetch full cluster profile including packs."""
    return api_request("GET", f"/clusterprofiles/{uid}")


def build_profile_template(uid):
    """Build a minimal cluster profile reference: uid + variables only."""
    entry = {"uid": uid}
    if uid in PROFILE_VARS:
        entry["variables"] = [
            {"name": k, "value": v} for k, v in PROFILE_VARS[uid].items()
        ]
    return entry


def build_cluster_payload(name, edge_host_uids):
    """Build the full cluster creation payload."""
    config = CLUSTER_CONFIGS[name]

    profiles = [build_profile_template(INFRA_PROFILE_UID)]
    for addon_uid in config["addon_profiles"]:
        profiles.append(build_profile_template(addon_uid))

    machine_pools = [
        {
            "cloudConfig": {
                "edgeHosts": [{"hostUid": edge_host_uids[0]}] if edge_host_uids else [],
            },
            "poolConfig": {
                "name": "cp-pool",
                "size": 1,
                "labels": ["master"],
                "isControlPlane": True,
                "useControlPlaneAsWorker": True,
                "machinePoolProperties": {"archType": "amd64"},
            },
        },
        {
            "cloudConfig": {
                "edgeHosts": [{"hostUid": edge_host_uids[1]}] if len(edge_host_uids) > 1 else [],
            },
            "poolConfig": {
                "name": "worker-pool",
                "size": 1,
                "labels": ["worker"],
                "isControlPlane": False,
                "machinePoolProperties": {"archType": "amd64"},
            },
        },
    ]

    payload = {
        "metadata": {
            "name": name,
            "labels": {},
            "annotations": {
                "description": config["description"],
            },
        },
        "spec": {
            "cloudType": "edge-native",
            "cloudConfig": {
                "controlPlaneEndpoint": {
                    "host": "172.16.30.244",
                    "type": "VIP",
                },
            },
            "machinepoolconfig": machine_pools,
            "profiles": profiles,
        },
    }

    return payload


def cmd_create(args):
    name = args.cluster_name
    if name not in CLUSTER_CONFIGS:
        print(f"Unknown cluster: {name}")
        print(f"Choose from: {', '.join(CLUSTER_CONFIGS.keys())}")
        sys.exit(1)

    edge_hosts = args.hosts.split(",") if args.hosts else []
    if len(edge_hosts) < 2:
        print("WARNING: Need 2 edge host UIDs (--hosts host1,host2)")
        print("Run 'python3 dpf_deploy.py hosts' to list available hosts")
        if not edge_hosts:
            print("Proceeding without host assignment (assign later in UI)...")

    payload = build_cluster_payload(name, edge_hosts)

    if args.dry_run:
        print(json.dumps(payload, indent=2))
        return

    print(f"\nCreating cluster '{name}'...")
    result = api_request("POST", "/spectroclusters/edge-native", payload)
    uid = result.get("uid", "unknown")
    print(f"Cluster created! UID: {uid}")
    print(f"\nMonitor status: python3 dpf_deploy.py status {uid}")
    print(f"Delete when done: python3 dpf_deploy.py delete {uid}")


def cmd_status(args):
    uid = args.cluster_uid
    data = api_request("GET", f"/spectroclusters/{uid}/status")
    state = data.get("state", "Unknown")
    conditions = data.get("conditions", []) or []
    print(f"Cluster {uid}: {state}")
    for c in conditions:
        print(f"  [{c.get('type')}] {c.get('status')} - {c.get('message', '')}")


def cmd_delete(args):
    uid = args.cluster_uid
    print(f"Deleting cluster {uid}...")
    api_request("DELETE", f"/spectroclusters/{uid}")
    print("Delete initiated. Cluster will be removed shortly.")


def cmd_list(_args):
    body = {"filter": {}, "sort": [], "limit": 50, "offset": 0}
    data = api_request("POST", "/dashboard/spectroclusters", body)
    items = data.get("items", [])
    print(f"{'Name':40s} {'UID':30s} {'State':15s} Cloud")
    print("-" * 100)
    for item in items:
        meta = item["metadata"]
        status = item.get("status", {})
        spec = item.get("specSummary", {})
        cloud = spec.get("cloudConfig", {}).get("cloudType", "?")
        print(f"{meta['name']:40s} {meta['uid']:30s} {status.get('state','?'):15s} {cloud}")


def cmd_hosts(_args):
    data = api_request("GET", "/edgehosts")
    items = data.get("items", [])
    print(f"{'Name':45s} {'UID':45s} {'State':10s} {'Health':10s} In-Use")
    print("-" * 120)
    for h in items:
        meta = h["metadata"]
        status = h.get("status", {})
        health = status.get("health", {}).get("state", "?")
        in_use = status.get("inUseClusters", {})
        state = status.get("state", "?")
        print(f"{meta['name']:45s} {meta['uid']:45s} {state:10s} {health:10s} {in_use}")


def cmd_wait(args):
    uid = args.cluster_uid
    timeout = args.timeout
    interval = 30
    elapsed = 0
    print(f"Waiting for cluster {uid} to reach Running state (timeout: {timeout}s)...")
    while elapsed < timeout:
        data = api_request("GET", f"/spectroclusters/{uid}/status")
        state = data.get("state", "Unknown")
        print(f"  [{elapsed}s] State: {state}")
        if state == "Running":
            print("Cluster is Running!")
            return
        if state in ("Error", "Failed"):
            print(f"Cluster entered {state} state.", file=sys.stderr)
            sys.exit(1)
        time.sleep(interval)
        elapsed += interval
    print(f"Timeout after {timeout}s. Last state: {state}", file=sys.stderr)
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="DPF A/B Testing Cluster Deployer")
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("create", help="Create a test cluster")
    p_create.add_argument("cluster_name", choices=list(CLUSTER_CONFIGS.keys()))
    p_create.add_argument("--hosts", help="Comma-separated edge host UIDs (2 required)")
    p_create.add_argument("--dry-run", action="store_true", help="Print payload without creating")
    p_create.set_defaults(func=cmd_create)

    p_status = sub.add_parser("status", help="Check cluster status")
    p_status.add_argument("cluster_uid")
    p_status.set_defaults(func=cmd_status)

    p_delete = sub.add_parser("delete", help="Delete a cluster")
    p_delete.add_argument("cluster_uid")
    p_delete.set_defaults(func=cmd_delete)

    p_list = sub.add_parser("list", help="List all clusters")
    p_list.set_defaults(func=cmd_list)

    p_hosts = sub.add_parser("hosts", help="List available edge hosts")
    p_hosts.set_defaults(func=cmd_hosts)

    p_wait = sub.add_parser("wait", help="Wait for cluster to reach Running state")
    p_wait.add_argument("cluster_uid")
    p_wait.add_argument("--timeout", type=int, default=1800, help="Timeout in seconds (default: 1800)")
    p_wait.set_defaults(func=cmd_wait)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
