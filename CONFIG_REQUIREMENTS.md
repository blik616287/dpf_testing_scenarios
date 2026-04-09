# Configuration Requirements — Discovery & Tuning

This document identifies every configuration parameter across the 4 Palette cluster profiles that requires **discovery** (values that must be gathered from your specific environment) or **tuning** (defaults that may need adjustment for your hardware/network).

**Phase 0 of the [deployment process](README.md#phase-0-hardware-discovery) automates discovery of most values** using a privileged DaemonSet on a basic Ubuntu cluster. The discovery script (`scripts/discover.sh`) maps directly to the variables below — each section header notes which discovery script section provides the data.

## Table of Contents

- [Critical: Must Discover Before Deployment](#critical-must-discover-before-deployment)
- [HBN-Specific: Must Discover for dpf-ovn-hbn](#hbn-specific-must-discover-for-dpf-ovn-hbn)
- [Tuning: May Need Adjustment](#tuning-may-need-adjustment)
- [Palette Spectro Variables Summary](#palette-spectro-variables-summary)
- [Pre-Deployment Checklist](#pre-deployment-checklist)

---

## Critical: Must Discover Before Deployment

These values are **required for all 3 cluster configurations**. Deployment will fail or produce a non-functional cluster without them.

### 1. DPU Cluster Keepalived Interface
> Discovery script: **Section 3 — NETWORK INTERFACES**

| | |
|-|-|
| **Variable** | `spectro.var.controlPlaneInterface` (infra) / `spectro.var.dpuClusterInterface` (CP-Configs) |
| **Where** | `dpf-zt-cluster` → `dpu-cluster` manifest, `dpf-control-plane` → `dpf-trusted-mode-cp` manifest |
| **What it is** | The host network interface on which keepalived will listen to provide the DPU cluster VIP. This should be the out-of-band (OOB) / management network interface on the control plane node. |
| **How to discover** | SSH to the host and identify the management interface: `ip addr show` — look for the interface with the management IP (not the high-speed data interfaces). Common names: `eno1`, `bond0`, `ens1f0`. |
| **Example** | `eno1` |

### 2. DPU Cluster Virtual IP
> Discovery script: **Section 12 — FREE IP SCAN**

| | |
|-|-|
| **Variable** | `spectro.var.controlPlaneVIP` (infra) / `spectro.var.dpuClusterIP` (CP-Configs) |
| **Where** | `dpf-zt-cluster` → `dpu-cluster` manifest, `dpf-control-plane` → `dpf-trusted-mode-cp` manifest |
| **What it is** | A virtual IP address for the DPU cluster Kubernetes API endpoint. Keepalived will manage this VIP on the host. |
| **Requirements** | Must be on the same subnet as the management interface. Must NOT be in the DHCP allocation range. Must be currently unused. |
| **How to discover** | Check your network team's IPAM / DHCP config. Reserve a static IP on the management subnet. Verify with: `arping -D -I <interface> <candidate-ip>` — no response means it's free. |
| **Example** | `172.16.0.250` |

### 3. DPU BMC / OOB Password
> Discovery script: **Not discoverable** — requires human input

| | |
|-|-|
| **Variable** | `spectro.var.dpuOobPassword` |
| **Where** | `dpf-zt-cluster` → `dpu-bmc-password` manifest (creates a Kubernetes Secret) |
| **What it is** | The password for the BlueField DPU's BMC (Baseboard Management Controller) used for Redfish-based provisioning. DPF uses Redfish to push the BFB (BlueField Bundle) to the DPU during initial setup. |
| **How to discover** | Check the DPU's BMC configuration. Default BF3 BMC password is typically set during manufacturing or first boot. May need to be obtained from whoever configured the hardware. |
| **Caution** | This is a sensitive credential. Will be stored as a Kubernetes Secret. |

### 4. DPU Discovery IP Range
> Discovery script: **Section 7 — DPU BMC / OOB NETWORK**

| | |
|-|-|
| **Variables** | `spectro.var.dpfDiscoveryStartIP`, `spectro.var.dpfDiscoveryEndIP` |
| **Where** | `dpf-zt-cluster` → `dpu-discovery` manifest |
| **What it is** | The IP address range that DPF will scan to discover BlueField DPUs on the OOB/BMC network. The DPF provisioning controller uses Redfish to these IPs to detect and onboard DPUs. |
| **How to discover** | Identify the BMC IP addresses of all BlueField DPUs in your nodes. These are on the OOB management network. Check DHCP leases, or look at the DPU BMC web interface / `ipmitool`. For 2 nodes with 1 DPU each, you need a range covering 2 BMC IPs. |
| **Example** | `startIP: 172.16.0.101`, `endIP: 172.16.0.102` |

### 5. DPU PCI Device Name Prefix
> Discovery script: **Section 4 — BLUEFIELD / MELLANOX PCI DEVICES**

| | |
|-|-|
| **Variable** | `spectro.var.DPU` |
| **Where** | `dpf-control-plane` → `sriov-policy` manifest (SR-IOV `pfNames` selector) |
| **What it is** | The PCI device name prefix for the BlueField NIC PFs on the host. Used to configure SR-IOV VFs. The full PF name will be `<prefix>f0np0` (port 0) and `<prefix>f1np1` (port 1). |
| **How to discover** | SSH to the host and run: `lspci -d 15b3: -v` to find Mellanox/NVIDIA devices, then `ls /sys/class/net/` or `ip link` to find the interface names. For BF3: typically `enp<bus>s0`. |
| **Example** | `enp153s0` (resulting in `enp153s0f0np0` for port 0) |

### 6. Number of SR-IOV VFs
> Discovery script: **Section 5 — SR-IOV CAPABILITIES**

| | |
|-|-|
| **Variable** | `spectro.var.DPUNumVFs` |
| **Where** | `dpf-control-plane` → `sriov-policy` manifest |
| **What it is** | Number of Virtual Functions to create on the BlueField PF for SR-IOV. Must match or be less than `NUM_OF_VFS` in the DPU nvconfig (currently set to 46). |
| **Default** | The nvconfig sets `NUM_OF_VFS=46`. The SR-IOV policy PF range is `#2-45` (44 usable VFs, first 2 reserved). |
| **Recommendation** | Use `46` unless you have a reason to reduce. The VF range in the pfNames filter (`#2-45`) may need adjustment if you change this. |

### 7. Pod and Service CIDRs

| | |
|-|-|
| **Variables** | `spectro.var.K8sPodCIDR`, `spectro.var.K8sServiceCIDR` |
| **Where** | Infra profile, Kubernetes pack values (Cilium CNI configuration) |
| **What it is** | The CIDR ranges for Kubernetes pod and service networks. |
| **Defaults** | Typically `10.244.0.0/16` (pods) and `10.96.0.0/12` (services). |
| **Requirements** | Must not overlap with the host network, the DPU management network, or the HBN IPAM pools. |

---

## HBN-Specific: Must Discover for dpf-ovn-hbn

These values are **only required for the `dpf-ovn-hbn` cluster** (Test Case 3/4). They control the DOCA HBN BGP/EVPN-VXLAN fabric integration.

### 8. DPU Hostname Patterns
> Discovery script: **Section 6 — DPU SERIAL NUMBERS**

| | |
|-|-|
| **Where** | HBN addon → `dpuServiceConfigurations` → `perDPUValuesYAML` |
| **What it is** | Hostname patterns that match each DPU node. HBN uses these to assign per-DPU configuration (ASN, VRF, VLAN). The current profile has patterns like `dpu-node-mt24326005fn-mt24326005fn*` which are serial-number based hostnames from the original lab. |
| **How to discover** | After DPF provisions the DPUs and they join the DPU cluster, check: `kubectl get nodes` on the DPU cluster. The node names will contain the DPU serial numbers. |
| **Current values** | `dpu-node-mt24326005fn-mt24326005fn*` (ASN 65101), `dpu-node-mt2439600dak-mt2439600dak*` (ASN 65102) |
| **Action required** | **Replace with your actual DPU serial-number hostnames.** This is the most common HBN deployment failure — mismatched hostname patterns cause DPUs to fall through to the wildcard config which doesn't assign an ASN. |

### 9. BGP Autonomous System Numbers

| | |
|-|-|
| **Where** | HBN addon → `perDPUValuesYAML` → `bgp_autonomous_system` |
| **What it is** | The BGP ASN assigned to each DPU. Each DPU must have a unique ASN for eBGP peering with the ToR switch. |
| **Current values** | DPU1: `65101`, DPU2: `65102` |
| **Requirements** | Must be in the private ASN range (64512–65534 for 2-byte, or 4200000000–4294967294 for 4-byte). Must match the ToR switch BGP configuration which expects these specific ASNs as neighbors. |
| **Action required** | Coordinate with your network team. The ToR switch must be configured to accept BGP peers from these ASNs. |

### 10. ToR Switch BGP Configuration

| | |
|-|-|
| **Where** | Not in the Palette profile — configured on the physical ToR switch |
| **What it is** | The Top-of-Rack switch must be configured with BGP neighbors for each DPU uplink, EVPN-VXLAN, and ECMP. |
| **Required ToR config** | - eBGP peering on each interface connected to a BF DPU uplink<br>- Accept ASNs 65101, 65102 (or your chosen values)<br>- EVPN address family enabled<br>- ECMP multi-path enabled<br>- VXLAN tunnel endpoint configuration<br>- VRF-to-VNI mapping for RED VRF (VNI 100001) |
| **Action required** | Provide your network team with the DPU ASNs and request matching ToR configuration. Without this, BGP sessions will not establish. |

### 11. HBN IPAM Pools

| | |
|-|-|
| **Where** | HBN addon → `dpuServiceIPAMs` |
| **What it is** | IP address pools assigned to DPU interfaces for the HBN overlay network. |
| **Current values** | - `pool1`: `172.16.97.0/24` (gateway at .2, /29 subnets per DPU) — used for the RED VRF pf0hpf interface<br>- `loopback`: `11.0.0.0/24` (/32 per DPU) — used for VTEP source and BGP router-id |
| **Pre-allocations** | `dpu-node-mt2439600dak-mt2439600dak: 172.16.97.0/29`, `dpu-node-mt24326005fn-mt24326005fn: 172.16.97.8/29` |
| **Requirements** | - `pool1` network must not overlap with host, pod, or service CIDRs<br>- Loopback IPs must be routable in the fabric (advertised via BGP)<br>- Pre-allocations must use your actual DPU hostnames |
| **Action required** | Update the pool networks if they conflict with your environment. **Update the pre-allocation hostnames to match your DPUs.** |

### 12. VLAN / VNI / VRF Mappings

| | |
|-|-|
| **Where** | HBN addon → `perDPUValuesYAML` and `startupYAMLJ2` |
| **Current values** | RED VRF: VLAN `11`, L2VNI `10010`, L3VNI `100001` |
| **What it is** | The EVPN-VXLAN fabric parameters that map tenant VRFs to VLANs and VNIs. These define how traffic is segmented across the fabric. |
| **Requirements** | Must match the ToR switch EVPN configuration exactly. VLAN ID must be available on the switch. VNI values must be unique across the fabric. |
| **Note** | The profile also has commented-out BLUE VRF config (VLAN 21, L2VNI 10020, L3VNI 100002) for multi-tenant scenarios. Not needed for the current test cases. |

---

## Tuning: May Need Adjustment

These parameters have defaults that work for most BF3 deployments, but may need tuning for your specific hardware, network, or workload.

### 13. Hugepages Allocation

| | |
|-|-|
| **Where** | Passthrough and HBN addons → `dpuFlavors` → `grub.kernelParameters` |
| **Current** | `hugepagesz=2048kB`, `hugepages=3072` (= 6GB of hugepages on the DPU) |
| **What it affects** | OVS-DPDK uses hugepages for packet buffers and flow tables. Insufficient hugepages causes OVS to fail to start or degrade performance. |
| **When to tune** | If DPU has less memory, reduce. If running heavy service chains, increase. 6GB is typical for BF3. |

### 14. OVS-DPDK Parameters

| | |
|-|-|
| **Where** | Passthrough and HBN addons → `dpuFlavors` → `ovs.rawConfigScript` |
| **Parameters** | |
| `dpdk-max-memzones=50000` | Max DPDK memory zones. Increase for high VF count. |
| `hw-offload=true` | Enables hardware flow offload to BF ConnectX. **Critical for performance.** |
| `max-idle=20000` | Flow idle timeout (ms). Higher = less flow churn, more memory. |
| `max-revalidator=5000` | Flow revalidation interval (ms). |
| `ctl-pipe-size=1024` | Control message pipe size. |
| `pmd-quiet-idle=true` | Reduces PMD CPU usage when idle. |
| **When to tune** | The defaults are NVIDIA's recommended values for BF3. Only tune if you see specific issues (OVS crashes, flow table overflow, high PMD CPU usage). |

### 15. OVS Bridge & Port MTU

| | |
|-|-|
| **Where** | Passthrough and HBN addons → `ovs.rawConfigScript` |
| **Current** | `mtu_request=9216` on p0 (and p1 for HBN). HBN startup template: `mtu: 9000` on swp interfaces. |
| **What it affects** | Jumbo frame support. VXLAN encapsulation adds ~50 bytes overhead, so 9216 on the physical port supports 9000-byte inner frames. |
| **Requirements** | All switches and links between the nodes must support the configured MTU. If your fabric doesn't support jumbo frames, reduce to `1500` (physical) / `1450` (VXLAN inner). |
| **How to verify** | `ping -M do -s 9000 <remote-node-ip>` — if this fails, your fabric doesn't support jumbo frames. |

### 16. SR-IOV: VF Count and PF Port Configuration

| | |
|-|-|
| **Where** | Passthrough/HBN `nvconfig` and CP-Configs `sriov-policy` manifest |
| **Current** | `NUM_OF_VFS=46`, `PF_TOTAL_SF=20`, SR-IOV policy uses VFs `#2-45` on port 0 only |
| **Note** | Port 1 SR-IOV policy is **commented out** in `sriov-policy`. If you need SR-IOV on both ports (e.g., for HBN with dual-uplink ECMP), you may need to uncomment and configure the `bf3-p1-vfs` policy. |
| **When to tune** | If running fewer pods, reduce VFs. If you need dual-port SR-IOV (especially for HBN ECMP), uncomment the p1 policy. |

### 17. BFB (BlueField Bundle) Version

| | |
|-|-|
| **Where** | Passthrough and HBN addons → `bfb.url` |
| **Current** | `bf-bundle-3.2.1-34_25.11_ubuntu-24.04_64k_prod.bfb` |
| **What it is** | The DPU operating system image. Flashed to the BF during provisioning. |
| **Compatibility** | Must be compatible with the DPF operator version (`v25.10.1`) and the DPU hardware revision (BF2 vs BF3). The current BFB is for BF3 with Ubuntu 24.04. |
| **When to change** | Only if your DPUs require a different BFB (different HW revision, airgapped environment requiring a local mirror). |

### 18. DOCA HBN Container Version

| | |
|-|-|
| **Where** | HBN addon → `dpuServiceTemplates` → `doca-hbn` |
| **Current** | `image: nvcr.io/nvidia/doca/doca_hbn:3.2.1-doca3.2.1` |
| **Resources** | `memory: 6Gi`, `nvidia.com/bf_sf: 4` (4 subfunctions) |
| **When to tune** | Increase memory if HBN is managing many routes. The SF count is typically fine at 4. |

### 19. DPF Operator: Redfish BFB Registry Address

| | |
|-|-|
| **Where** | Infra profile → `nvidia-dpf-operator` pack → `dpf-operator-config.provisioningController` |
| **Current** | `bfbRegistryAddress: "{{ .spectro.system.cluster.kubevip }}:8080"` |
| **What it is** | The address from which DPUs download the BFB during Redfish-based provisioning. Uses the cluster's VIP on port 8080. |
| **Potential issue** | Port 8080 must not be blocked by firewall between the DPU BMC network and the host management network. |

### 20. DPF Operator: DMS Timeout

| | |
|-|-|
| **Where** | Infra profile → `nvidia-dpf-operator` pack → `dpf-operator-config.provisioningController` |
| **Current** | `dmsTimeout: 900` (15 minutes) |
| **What it is** | Timeout for DPU Management Software operations during provisioning. |
| **When to tune** | Increase if DPU provisioning consistently times out (e.g., slow BFB download over network). |

### 21. Longhorn Storage

| | |
|-|-|
| **Where** | Infra profile → `csi-longhorn` pack; referenced by kamaji-etcd, prometheus, grafana |
| **What it is** | Longhorn is the CSI storage provider. Multiple DPF components create PVCs using `storageClassName: longhorn`. |
| **Requirement** | Nodes must have local disk space for Longhorn replicas. The OS pack installs `nfs-common` for Longhorn and tags CP nodes with `node.longhorn.io/default-node-tags='["storage"]'`. |
| **Potential issue** | With only 2 nodes, Longhorn default replica count (3) will fail. You may need to set `defaultReplicaCount: 2` or `1` in the Longhorn config. |

### 22. Cilium CNI Tunnel Mode

| | |
|-|-|
| **Where** | Infra profile → `cni-cilium-oss` pack |
| **Current preset** | VXLAN tunnel mode with Kubernetes IPAM, eBPF kube-proxy replacement |
| **Relevance** | Cilium runs on the host and provides the K8s CNI. In Zero Trust mode, the DPU's OVN overlay handles pod networking on the DPU cluster, while Cilium handles the host cluster. These should not conflict. |
| **When to tune** | Normally no changes needed. If you see CNI conflicts, check that Cilium's pod CIDR doesn't overlap with the DPU cluster's network. |

### 23. Keepalived Virtual Router ID

| | |
|-|-|
| **Where** | `dpu-cluster` manifest → `keepalived.virtualRouterID` |
| **Current** | `126` |
| **What it is** | VRRP virtual router ID. Must be unique on the L2 network segment. If another keepalived/VRRP instance uses the same ID on the same network, they'll conflict. |
| **When to change** | If you already have VRRP/keepalived on the management network, check for ID conflicts. |

### 24. DPU Cluster Max Nodes

| | |
|-|-|
| **Where** | `dpu-cluster` manifest → `spec.maxNodes` |
| **Current** | `10` |
| **What it is** | Maximum number of DPU nodes in the Kamaji-managed DPU cluster. |
| **For this test** | 2 nodes × 1 DPU each = 2 DPU nodes. Default of 10 is fine. |

### 25. NFD Worker DNS Policy

| | |
|-|-|
| **Where** | Infra profile → `nvidia-dpf-prereqs` → `node-feature-discovery.worker` |
| **Current** | `dnsPolicy: ClusterFirstWithHostNet` with comment: "Change dnsPolicy to 'Default' when deploying on MAAS" |
| **Relevance** | Since we're using edge-native (not MAAS), the current value is correct. No change needed. |

---

## Palette Spectro Variables Summary

All `spectro.var.*` variables must be set in the Palette cluster configuration at deployment time.

| Variable | Required By | Description | Must Discover |
|----------|------------|-------------|---------------|
| `controlPlaneInterface` | Infra (dpf-zt-cluster) | Host management NIC name | Yes |
| `controlPlaneVIP` | Infra (dpf-zt-cluster) | Free IP on management subnet | Yes |
| `dpuOobPassword` | Infra (dpf-zt-cluster) | DPU BMC password | Yes |
| `dpfDiscoveryStartIP` | Infra (dpf-zt-cluster) | First DPU BMC IP | Yes |
| `dpfDiscoveryEndIP` | Infra (dpf-zt-cluster) | Last DPU BMC IP | Yes |
| `dpuClusterInterface` | Addon (CP-Configs) | Same as controlPlaneInterface | Yes (same value) |
| `dpuClusterIP` | Addon (CP-Configs) | Same as controlPlaneVIP | Yes (same value) |
| `DPU` | Addon (CP-Configs) | BF PCI device prefix (e.g., `enp153s0`) | Yes |
| `DPUNumVFs` | Addon (CP-Configs) | SR-IOV VF count (default: 46) | No (use default) |
| `K8sPodCIDR` | Infra (k8s/cilium) | Pod network CIDR | No (use default) |
| `K8sServiceCIDR` | Infra (k8s/cilium) | Service network CIDR | No (use default) |

---

## Pre-Deployment Checklist

### Hardware Discovery (run on each node)

```bash
# 1. Management interface name
ip addr show | grep "state UP" 
# Look for the interface with your management IP

# 2. BlueField PCI device name
lspci -d 15b3: | grep -i bluefield
ls /sys/class/net/ | grep enp
# Cross-reference: ip link show <interface>

# 3. DPU BMC IPs (from the host)
ipmitool -I lanplus -H <dpu-bmc-ip> -U admin -P <password> mc info
# Or check DHCP leases for DPU BMC MACs

# 4. Verify jumbo frame support
ping -M do -s 8972 <other-node-management-ip>

# 5. Check available disk space for Longhorn
df -h /var/lib/longhorn
```

### Network Team Coordination (for HBN only)

- [ ] ToR switch ports identified for each BF DPU uplink
- [ ] BGP ASNs agreed upon (per DPU)
- [ ] ToR BGP neighbor config applied
- [ ] EVPN-VXLAN enabled on ToR
- [ ] ECMP multi-path enabled on ToR
- [ ] VLAN 11 (RED) allowed on ToR ports
- [ ] VNI 10010 (L2) and 100001 (L3) configured on ToR
- [ ] Loopback subnet (`11.0.0.0/24`) routable in fabric
- [ ] Pool1 subnet (`172.16.97.0/24`) routable in RED VRF

### Palette Variables to Collect

```
controlPlaneInterface = ____________
controlPlaneVIP       = ____________
dpuOobPassword        = ____________
dpfDiscoveryStartIP   = ____________
dpfDiscoveryEndIP     = ____________
DPU (PCI prefix)      = ____________
DPUNumVFs             = 46 (default)
K8sPodCIDR            = 10.244.0.0/16 (default)
K8sServiceCIDR        = 10.96.0.0/12 (default)
```

### HBN Additional Variables (dpf-ovn-hbn only)

```
DPU1 hostname pattern  = ____________
DPU1 BGP ASN           = ____________
DPU2 hostname pattern  = ____________
DPU2 BGP ASN           = ____________
Pool1 network          = 172.16.97.0/24 (default)
Loopback network       = 11.0.0.0/24 (default)
RED VLAN               = 11 (default)
RED L2VNI              = 10010 (default)
RED L3VNI              = 100001 (default)
```
