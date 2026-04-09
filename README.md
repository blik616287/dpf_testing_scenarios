# DPF A/B Performance Testing

Automated deployment and testing pipeline for NVIDIA DPF (Data Processing Framework) A/B performance testing on BlueField DPUs, using [Spectro Cloud Palette](https://docs.spectrocloud.com/api/introduction/) for cluster lifecycle management.

## Process Overview

This project follows a **4-phase approach**. The same 2 physical nodes are reused throughout.

```
Phase 0: Discovery          Deploy a basic Ubuntu cluster, run privileged pods
    │                       to discover hardware, network, and DPU details.
    │                       Fill in CONFIG_REQUIREMENTS.md with real values.
    ▼                       Tear down discovery cluster.
Phase 1: Baseline Test      Deploy dpf-ovn-baseline (Passthrough mode).
    │                       Run full benchmark suite. Collect results.
    ▼                       Tear down.
Phase 2: OVN Accelerated    Deploy dpf-ovn-accelerated (DPF OVN offload).
    │                       Run full benchmark suite. Collect results.
    ▼                       Tear down.
Phase 3: OVN + HBN          Deploy dpf-ovn-hbn (DPF OVN + DOCA HBN/BGP/ECMP).
                             Run full benchmark suite. Collect results.
                             Tear down.
```

## Repository Structure

```
├── README.md                  ← You are here (full process guide)
├── CONFIG_REQUIREMENTS.md     ← All config parameters: what to discover, what to tune
├── TEST_CASES.md              ← Detailed test case definitions and metrics
├── manifests/
│   └── discovery-daemonset.yaml   ← Privileged DaemonSet for Phase 0 hardware discovery
└── scripts/
    ├── dpf_deploy.py              ← Palette API automation for DPF cluster lifecycle
    └── discover.sh                ← Discovery script (runs inside privileged pods)
```

## Prerequisites

- Python 3.6+ (no external dependencies)
- `kubectl` configured for the discovery cluster (Phase 0) and DPF clusters (Phase 1–3)
- 2 bare-metal nodes with NVIDIA BlueField DPUs, registered as Palette edge hosts
- A basic Ubuntu edge-native infrastructure profile in Palette (for Phase 0)
- Network infrastructure supporting BGP/ECMP (for Phase 3 HBN test)

## Setup

```bash
export PALETTE_API_KEY="your-api-key"
export PALETTE_PROJECT_UID="your-project-uid"
```

---

## Phase 0: Hardware Discovery

**Goal**: Deploy a minimal cluster on the target hardware to discover all environment-specific configuration values before attempting a DPF deployment.

### 0.1 — Deploy Discovery Cluster

Using Palette UI or API, deploy a **basic Ubuntu edge-native cluster** (no DPF) on the 2 target nodes:
- Use any general-purpose edge-native infrastructure profile (Ubuntu + K8s + Cilium/Calico)
- Node 1: control plane + worker
- Node 2: worker
- No addon profiles needed

Wait for the cluster to reach `Running` state and configure `kubectl` access.

### 0.2 — Deploy Discovery Pods

```bash
kubectl apply -f manifests/discovery-daemonset.yaml
kubectl -n dpf-discovery rollout status daemonset/dpf-discovery
```

This creates a privileged DaemonSet that runs on every node with full host access.

### 0.3 — Run Discovery Script

```bash
# Copy script to all pods and run
for pod in $(kubectl get pods -n dpf-discovery -o jsonpath='{.items[*].metadata.name}'); do
  echo ""
  echo "=========================================="
  echo "  Discovering: $pod"
  echo "=========================================="
  kubectl cp scripts/discover.sh dpf-discovery/$pod:/tmp/discover.sh
  kubectl exec -n dpf-discovery $pod -- bash /tmp/discover.sh
done
```

### 0.4 — What Gets Discovered

The script collects and reports:

| Section | Discovers | Maps To |
|---------|-----------|---------|
| Host identity | Hostname, OS, kernel | Baseline info |
| CPU / Memory / NUMA | Core count, memory, hugepage support | Tuning decisions |
| Network interfaces | All NICs, default route, IPs, MTU, driver | `controlPlaneInterface` |
| BlueField PCI devices | BF device names, PCI addresses, port names | `DPU` (PCI prefix) |
| SR-IOV capabilities | Max VFs per PF, current VF count | `DPUNumVFs` |
| DPU serial numbers | PCI serial, rshim devices | HBN `hostnamePattern` |
| BMC / OOB network | IPMI interfaces, ARP neighbors, tmfifo | `dpfDiscoveryStartIP/EndIP` |
| Disk / storage | Block devices, free space on /var | Longhorn readiness |
| MTU / jumbo frames | Current and max MTU per interface | MTU tuning |
| VRRP / keepalived | Existing instances, router IDs | `virtualRouterID` conflicts |
| Firmware versions | NIC driver, FW version | BFB compatibility |
| Free IP scan | Ping sweep of high subnet range | `controlPlaneVIP` candidates |

### 0.5 — Fill In Configuration

Using the discovery output, fill in `CONFIG_REQUIREMENTS.md` → [Palette Variables to Collect](#palette-spectro-variables-summary) and the [HBN Additional Variables](#hbn-specific-must-discover-for-dpf-ovn-hbn) section.

**What discovery cannot tell you** (requires human input):
- `dpuOobPassword` — DPU BMC credential, obtain from whoever set up the hardware
- `controlPlaneVIP` — discovery suggests candidates, but confirm with your network team it's outside DHCP
- ToR switch BGP config — must be coordinated with network team for HBN
- VLAN/VNI/VRF assignments — must match existing fabric configuration

### 0.6 — Tear Down Discovery Cluster

```bash
kubectl delete -f manifests/discovery-daemonset.yaml
```

Then delete the discovery cluster via Palette UI or API. The nodes are now free for DPF deployment.

---

## Phase 1: OVN Baseline (Passthrough)

**Goal**: Deploy a DPF cluster with passthrough mode (no acceleration) and collect baseline performance metrics.

**Cluster**: `dpf-ovn-baseline`
**Addons**: Spectro-DPU-DPF-CP-Configs + DPF Zero Trust Use Case - Passthrough

### 1.1 — Deploy

```bash
python3 scripts/dpf_deploy.py create dpf-ovn-baseline --hosts <HOST1>,<HOST2>
python3 scripts/dpf_deploy.py wait <cluster-uid>
```

### 1.2 — Validate

```bash
# Confirm both nodes are Ready
kubectl get nodes -o wide

# Confirm DPF operator is running
kubectl -n dpf-operator-system get pods

# Confirm DPUs are provisioned
kubectl -n dpf-operator-system get dpus

# Confirm passthrough service chain is active
kubectl -n dpf-operator-system get dpuservicechains
```

### 1.3 — Run Benchmarks

```bash
# Label nodes for pod placement
kubectl label node <node1> bench-role=client
kubectl label node <node2> bench-role=server

# Deploy benchmark pods (see TEST_CASES.md → Pod Placement Strategy)
# Run full benchmark suite: iperf3, netperf, sockperf
# Capture host CPU with mpstat
# Save results to results/dpf-ovn-baseline/
```

See [TEST_CASES.md](TEST_CASES.md) for the full benchmark matrix and detailed procedure.

### 1.4 — Tear Down

```bash
python3 scripts/dpf_deploy.py delete <cluster-uid>
# Wait for cluster to be fully removed before proceeding
```

---

## Phase 2: OVN Accelerated (DPF Offload)

**Goal**: Deploy a DPF cluster with OVN offloaded to the BlueField DPU and measure the acceleration uplift.

**Cluster**: `dpf-ovn-accelerated`
**Addons**: Spectro-DPU-DPF-CP-Configs (no passthrough — OVN offload is active)

### 2.1 — Deploy

```bash
python3 scripts/dpf_deploy.py create dpf-ovn-accelerated --hosts <HOST1>,<HOST2>
python3 scripts/dpf_deploy.py wait <cluster-uid>
```

### 2.2 — Validate

```bash
# Same node/pod checks as Phase 1, plus:

# Verify OVN offload is active on the DPU
# (SSH to node or exec into a privileged pod)
ovs-appctl dpctl/dump-flows type=offloaded | wc -l
# Should return > 0 once traffic flows

# Check OVS hardware offload is enabled
ovs-vsctl get Open_vSwitch . other_config:hw-offload
# Should return "true"
```

### 2.3 — Run Benchmarks

Same benchmark suite as Phase 1. Save results to `results/dpf-ovn-accelerated/`.

Additional data to capture:
- OVS offloaded flow count before and after each test
- Verify offload count increases during traffic (confirms hardware path)

### 2.4 — Tear Down

```bash
python3 scripts/dpf_deploy.py delete <cluster-uid>
```

---

## Phase 3: OVN + HBN (BGP/ECMP)

**Goal**: Deploy a DPF cluster with OVN offload plus DOCA HBN for BGP peering and ECMP multi-path routing.

**Cluster**: `dpf-ovn-hbn`
**Addons**: Spectro-DPU-DPF-CP-Configs + DPF Zero Trust Use Case - DOCA HBN

**Pre-requisite**: ToR switch must be configured for BGP/EVPN (see CONFIG_REQUIREMENTS.md #10).

### 3.1 — Deploy

```bash
python3 scripts/dpf_deploy.py create dpf-ovn-hbn --hosts <HOST1>,<HOST2>
python3 scripts/dpf_deploy.py wait <cluster-uid>
```

### 3.2 — Validate

```bash
# Same node/pod checks as Phase 1–2, plus:

# Verify BGP sessions are established (on DPU)
birdc show protocols
# All BGP sessions should be "Established"

# Verify ECMP routes
birdc show route
# Should show multiple next-hops for pod subnets

# Verify OVS offload + HBN bridge
ovs-vsctl show
# Should show br-sfc and br-hbn bridges
```

### 3.3 — Run Benchmarks

Same benchmark suite as Phase 1–2. Save results to `results/dpf-ovn-hbn/`.

Additional HBN-specific benchmarks:
- **ECMP scaling**: iperf3 with 1, 2, 4, 8, 16, 32 parallel streams
- **Per-uplink traffic distribution**: `ethtool -S` on p0 and p1 before/after
- **Failover test** (optional): disable one uplink, measure recovery time

### 3.4 — Tear Down

```bash
python3 scripts/dpf_deploy.py delete <cluster-uid>
```

---

## Results & Analysis

After all 3 phases, compare results across configurations:

```
results/
├── dpf-ovn-baseline/        ← Phase 1 results
├── dpf-ovn-accelerated/     ← Phase 2 results
├── dpf-ovn-hbn/             ← Phase 3 results
└── summary/
    ├── results.csv           ← Combined data
    └── charts/               ← Generated visualizations
```

### Key Comparisons

| Comparison | What It Shows |
|------------|--------------|
| Phase 1 vs Phase 2 | DPF OVN offload uplift (throughput, latency, CPU) |
| Phase 1 vs Phase 3 | Full DPF + HBN stack uplift |
| Phase 2 vs Phase 3 | Incremental HBN value (ECMP multi-path) |

See [TEST_CASES.md](TEST_CASES.md) for the full metric matrix and deliverable definitions.

---

## Cluster Configurations

All clusters use the **DPF Zero Trust Control Plane - Agent** edge-native infrastructure profile. The test variation comes from addon profiles:

| Profile | Type | Used By |
|---------|------|---------|
| DPF Zero Trust Control Plane - Agent | Infra (edge-native) | All DPF clusters |
| Spectro-DPU-DPF-CP-Configs | Addon | All DPF clusters |
| DPF Zero Trust Use Case - Passthrough | Addon | Phase 1 (`dpf-ovn-baseline`) |
| DPF Zero Trust Use Case - DOCA HBN | Addon | Phase 3 (`dpf-ovn-hbn`) |

## scripts/dpf_deploy.py Reference

```bash
python3 scripts/dpf_deploy.py hosts                          # List edge hosts
python3 scripts/dpf_deploy.py list                            # List clusters
python3 scripts/dpf_deploy.py create <name> --hosts H1,H2     # Create cluster
python3 scripts/dpf_deploy.py create <name> --hosts H1,H2 --dry-run  # Preview payload
python3 scripts/dpf_deploy.py status <uid>                    # Check status
python3 scripts/dpf_deploy.py wait <uid> [--timeout 3600]     # Wait for Running
python3 scripts/dpf_deploy.py delete <uid>                    # Tear down
```

Cluster names: `dpf-ovn-baseline`, `dpf-ovn-accelerated`, `dpf-ovn-hbn`

## API

- **Endpoint**: https://api.spectrocloud.com/v1
- **Auth**: `PALETTE_API_KEY` and `PALETTE_PROJECT_UID` environment variables
