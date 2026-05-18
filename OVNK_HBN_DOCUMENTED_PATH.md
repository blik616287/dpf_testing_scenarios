# Documented path: vanilla Kubernetes → HBN ECMP-offloaded pod-to-pod benchmark

**Goal:** OVN-Kubernetes as the **primary cluster CNI**, offloaded to BlueField-3
DPUs, with **DOCA HBN** providing a BGP/EVPN + **ECMP** underlay — then a
pod-to-pod benchmark. This replaces the previous hand-rolled
zero-trust + VPC-OVN-secondary build (the one that produced the rejected numbers).

Every phase below maps to an **explicit NVIDIA document**. Nothing here is
improvised — where this lab must deviate from the documented assumptions it is
called out in **§ Fabric divergence** and flagged inline.

---

## 0. Source documents (the explicitly-defined NVIDIA path)

| # | Document | URL |
|---|---|---|
| D1 | **hbn-ovnk use-case guide** — "OVN Kubernetes with Host Based Networking" (the primary path followed below) | `github.com/NVIDIA/doca-platform/tree/v25.10.1/docs/public/user-guides/host-trusted/use-cases/hbn-ovnk` |
| D2 | DPF System Prerequisites — Host Trusted | `.../host-trusted/prerequisites/system.md` |
| D3 | DPF Operator Helm Prerequisites | `.../getting-started/helm-prerequisites.md` |
| D4 | Host Network Configuration Prerequisites | `.../host-trusted/prerequisites/host-network-configuration-prerequisite.md` |
| D5 | **RDG** — "RDG for DPF Host Trusted with OVN-Kubernetes and HBN Services" (full lab walk-through incl. fabric/ToR config) | `docs.nvidia.com/networking/display/public/SOL/RDG-for-DPF-Host-Trusted-with-OVN-Kubernetes-and-HBN-Services` |
| D6 | DPF v25.10.1 product docs | `docs.nvidia.com/networking/display/dpf25101` |
| D7 | DOCA HBN Service Deployment (SDK — the HBN container itself, SFC modes) | `docs.nvidia.com/doca/sdk/hbn-service-deployment/index.html` |

D1 is the spine of this document. D5 is the same deployment written as a
reference lab including Top-of-Rack switch config — use it for the fabric side.
D7 is the **lower-level** HBN container doc; in the DPF path HBN is delivered as
a DPUService (Helm chart `doca-hbn`), **not** the static-pod model in D7 — D7
explicitly does *not* cover BGP/ECMP, that lives in the HBN DPUServiceConfiguration
(Phase 5).

---

## 1. What changes vs. the current cluster

| | Current (rejected) build | Documented target |
|---|---|---|
| DPF mode | `zero-trust` | **`host-trusted`** (`DPFOperatorConfig.spec.deploymentMode: host-trusted`) — D1/D2 |
| Primary CNI | Cilium | **OVN-Kubernetes** (Helm chart, Phase 1) — D1 |
| OVN role | VPC-OVN as a **secondary** Multus network | OVN-Kubernetes **is the cluster CNI**, offloaded to the DPU |
| HBN | hand-rolled DPUService + manual SFC patching | `DPUDeployment`-managed service, SFC auto-programmed — D1 |
| ECMP | peered numbered over the p0 VLAN SVI (deviation) | NVUE `path-selection.multipath` + unnumbered eBGP on **both** uplinks — D1 |
| Pod attach | manual OVN LSP + `iface-id` | SR-IOV VF auto-injected by the OVN-K8s resource-injector webhook — D1 |

A primary-CNI swap **cannot be done in place** — hence the hard reset: the
workload cluster is rebuilt from kubeadm with **no CNI and no kube-proxy**, then
OVN-Kubernetes is installed as the CNI (Phase 1).

---

## 2. Fabric divergence — READ THIS BEFORE COMMITTING

The documented path (D1, the HBN `startupYAMLJ2`) configures BGP like this:

```yaml
neighbor:
  p0_if: { peer-group: hbn, type: unnumbered }
  p1_if: { peer-group: hbn, type: unnumbered }
path-selection:
  multipath: { aspath-ignore: on }
```

**Both uplinks are routed L3 ports running unnumbered eBGP to the ToR.** ECMP =
two equal-cost BGP next-hops, one per uplink. D5 wires both leaf ports as
`no switchport` routed interfaces.

**This lab's fabric (stated, non-negotiable without a network request):**
- `p0` → **switchport** (L2 access, VLAN 497)
- `p1` → **routed, numbered /31**

So the documented two-path unnumbered-ECMP model **does not fit p0 as-is**.
Three options, explicitly:

1. **File the network request** to make the leaf `p0` port a routed interface
   (numbered /31 or unnumbered). Then the documented path works verbatim and you
   get true 2-path ECMP. *Recommended — it is the only by-the-book path.*
2. **Documented deviation:** keep p0 a switchport, peer HBN BGP **numbered over
   the VLAN 497 SVI** for the p0 path and unnumbered/numbered on p1. ECMP still
   works (two next-hops) but the p0 neighbour stanza deviates from D1. This is
   the model the previous build used — it works but is not "the documented path."
3. **Single-path:** run the documented path with **p1 only** as the BGP uplink
   (1 ECMP member). No network request, fully by-the-book, but no ECMP
   multiplication — and § "one geneve tunnel = one uplink" still caps a single
   pod-pair regardless.

**Decision needed from you / network engineering before Phase 5.** Everything
up to Phase 5 is identical regardless of which option is chosen.

---

## 3. Prerequisites — the "vanilla Kubernetes" starting state  (D2, D3, D4)

### 3.1 Cluster (D2)
- Kubernetes **1.33–1.35**.
- Control-plane nodes labelled `node-role.kubernetes.io/control-plane: ""`.
- **No CNI installed. No kube-proxy installed.** (OVN-Kubernetes replaces both.)
- CoreDNS pinned to control-plane nodes via NodeAffinity; control plane fully
  up before workers join.
- Worker nodes (the DPU hosts) are **bare-metal x86_64**, ≥16 GB / 8 CPU.
- Per-node identity for OVN-K8s:
  - control plane: label `k8s.ovn.org/zone-name: <node>`
  - workers: labels `k8s.ovn.org/dpu-host: ""`, `k8s.ovn.org/zone-name: <node>`;
    annotation `k8s.ovn.org/remote-zone-migrated: <node>`.
- **Control-plane** nodes: OVS packages installed; OOB mgmt port made an OVS
  bridge tagged `bridge-uplink`. **Workers**: OVS **not** installed; PF0 on DHCP,
  MTU 1500 (D1 prerequisites).

### 3.2 DPU / hardware (D2)
- BlueField-3, 32 GB, flashed with a DOCA ≥2.5 BFB; all firmware (BMC/CEC/UEFI)
  on the same supported bundle.
- MFT (`mst`, `mlxconfig`), `ipmitool` present on hosts; `rshim` **not** installed
  on workers; In-Band Manageability enabled in BIOS.
- A management-subnet **VIP** reserved (non-DHCP) for the DPU control plane;
  OOB fabric must permit VRRP multicast.

### 3.3 DPF Operator Helm dependencies (D3) — install BEFORE the DPF chart
Since DPF v25.7 the DPF chart bundles no dependencies. Install (helmfile at
`deploy/helmfiles/` in the repo, or manually):

| Chart | Version |
|---|---|
| cert-manager | v1.19.3 |
| argo-cd | 9.4.1 |
| node-feature-discovery | 0.18.3 |
| maintenance-operator | 0.3.0 |
| kamaji | 1.2.0 |
| local-path-provisioner | 0.0.34 |

---

## 4. The documented deployment path  (D1 — `hbn-ovnk`, Steps 0–6)

Work from the guide directory:
`cd docs/public/user-guides/host-trusted/use-cases/hbn-ovnk`

### Phase 0 — Environment (`manifests/00-env-vars/envvars.env`)
Set and `source` the env file; `../../../../check-required-env.sh` verifies it.
Key vars: `TARGETCLUSTER_API_SERVER_HOST/PORT`, `TARGETCLUSTER_NODE_CIDR`,
`DPUCLUSTER_VIP`, `DPUCLUSTER_INTERFACE`, `POD_CIDR` (e.g. `10.233.64.0/18`),
`SERVICE_CIDR`, `REGISTRY=https://helm.ngc.nvidia.com/nvidia/doca`,
`TAG=v25.10.1`, `BFB_URL`, `OVN_KUBERNETES_REPO_URL=oci://ghcr.io/mellanox/charts`,
`OVN_KUBERNETES_CHART_TAG`, `HBN_NGC_IMAGE_URL`.

### Phase 1 — Install OVN-Kubernetes as the primary CNI
```bash
envsubst < manifests/01-cni-installation/helm-values/ovn-kubernetes.yml | \
  helm upgrade --install --create-namespace --namespace ovn-kubernetes \
  ovn-kubernetes ${OVN_KUBERNETES_REPO_URL}/ovn-kubernetes-chart \
  --version ${OVN_KUBERNETES_CHART_TAG} --values -
```
Values enable `commonManifests`, `nodeWithoutDPUManifests`,
`controlPlaneManifests`, `nodeWithDPUManifests`;
`nodeMgmtPortDpResourceName: nvidia.com/ovnk-mgmt-vf`;
`gatewayOpts: --gateway-interface=derive-from-mgmt-port`; `podNetwork`,
`serviceNetwork`, `k8sAPIServer` from env.
**Gate:** control-plane nodes Ready; `ovn-kubernetes-cluster-manager` +
`ovn-kubernetes-node`/`-identity` rolled out.

### Phase 2 — DPF Operator
Install the Helm prerequisites (§3.3), point NFD at the API server, then:
```bash
helm repo add --force-update dpf-repository ${REGISTRY} && helm repo update
helm upgrade --install -n dpf-operator-system dpf-operator \
  dpf-repository/dpf-operator --version=$TAG
```
**Gate:** `dpf-operator-controller-manager` rolled out.

### Phase 3 — DPF System
```bash
kubectl create ns dpu-cplane-tenant1
cat manifests/03-dpf-system-installation/*.yaml | envsubst | kubectl apply -f -
```
- **`DPFOperatorConfig`** — `spec.deploymentMode: host-trusted`,
  `kamajiClusterManager.disable: false`, `nodeSRIOVDevicePluginController.disable: false`.
- **`DPUCluster`** — `type: kamaji`, `clusterEndpoint.keepalived` on the
  `DPUCLUSTER_VIP`/`DPUCLUSTER_INTERFACE`, `virtualRouterID: 126`.
**Gate:** `DPFOperatorConfig` `SystemComponentsReconciled`; `DPUCluster` Ready.

### Phase 4 — Accelerated CNI components
- **NVIDIA Network Operator** v26.1.0 (provides Multus) — Helm.
- **OVN-Kubernetes resource-injector webhook** — Helm (`ovn-kubernetes-resource-injector.enabled: true`); this is what auto-injects an SR-IOV VF into pods.
- **`NicClusterPolicy`** — Multus image.
- **`NodeSRIOVDevicePluginConfig` `bf3-p0-vfs`** — exposes VF1 as
  `nvidia.com/ovnk-mgmt-vf` and VF2–45 as `nvidia.com/bf3-p0-vfs`.
**Gate:** network-operator + resource-injector rolled out.

### Phase 5 — DPU provisioning + services  (BFB flash happens here)
```bash
cat manifests/05-dpudeployment-installation/*.yaml | envsubst | kubectl apply -f -
```
Objects:
- **`BFB`** — `spec.url: $BFB_URL` (DPU bitstream).
- **`DPUFlavor` `hbn-ovnk`** — nvconfig (`PER_PF_NUM_SF=1`, `PF_TOTAL_SF=20`,
  `NUM_OF_VFS=46`, `LINK_TYPE_P1/P2=ETH`, …), `mlnx-bf.conf`
  (`ENABLE_ESWITCH_MULTIPORT=yes`), `mlnx-ovs.conf` (`OVS_DOCA=yes`,
  `CREATE_OVS_BRIDGES=no`), and an `ovs.rawConfigScript` that builds the bridges
  **`br-sfc`, `br-hbn`, `br-dpu`, `br-ovn`** with `doca-init=true`,
  `hw-offload=true`, `p0`/`pf0hpf` at **MTU 9216**, and the
  `pbrovntobrdpu ↔ pbrdputobrovn` patch pair.
- **`DPUDeployment` `ovn-hbn`** — binds BFB + flavor and the four services
  (`ovn`, `hbn`, `dts`, `blueman`), and declares the **service chains**:
  ```
  p0  ─ serviceInterface uplink=p0  → hbn p0_if
  p1  ─ serviceInterface uplink=p1  → hbn p1_if
  ovn ─ serviceInterface port=ovn   → hbn pf2dpu2_if
  ```
  SFC is programmed **by the DPF controllers** from this — no manual
  `ovs-ofctl` flow patching (the failure mode of the previous build).
- **OVN service** (`DPUServiceTemplate`/`Configuration` `ovn`) — the
  `ovn-kubernetes-chart` DPU manifests; `gatewayOpts: --gateway-interface=br-dpu`;
  `vtepCIDR: 10.0.120.0/22`, IPAM `pool1`.
- **HBN service** (`DPUServiceTemplate`/`Configuration` `hbn`) — Helm chart
  `doca-hbn` 1.0.5, image tag `3.2.1-doca3.2.1`, `nvidia.com/bf_sf: 3`.
  **ECMP/BGP lives here** — see §5.
- **`DPUServiceIPAM`** `pool1` (`10.0.120.0/22`, /29) and `loopback`
  (`11.0.0.0/24`, /32 — BGP router-ids).
- `DPUServiceInterface` `p0`/`p1` (physical) and `ovn` (patch to `br-ovn`);
  `DPUServiceCredentialRequest` `ovn-dpu`.
**Gates:** `BFB` Ready → `DPUDeployment` `PrerequisitesReady` →
`DPUServicesReconciled` → `ApplicationsReconciled` → `DPUIPAMObjectReconciled` →
`ServiceInterfaceSetReconciled` → `ServiceChainSetReconciled`.

### Phase 6 — Test traffic
Join the worker (DPU host) nodes, then `kubectl apply -f manifests/06-test-traffic`;
inspect with `dpfctl describe dpudeployments`; ping pod-to-pod.

---

## 5. How ECMP is configured (D1, HBN `DPUServiceConfiguration` → `startupYAMLJ2`)

HBN runs FRR on the DPU, configured via **NVUE**. The relevant stanzas:

```yaml
router:
  bgp:
    autonomous-system: {{ config.bgp_autonomous_system }}   # 65101 worker1*, 65201 worker2*
    router-id: {{ ipaddresses.ip_lo.ip }}                   # /32 from the loopback IPAM pool
vrf:
  default:
    router:
      bgp:
        address-family:
          ipv4-unicast: { enable: on, redistribute: { connected: { enable: on } } }
        neighbor:
          p0_if: { peer-group: hbn, type: unnumbered }
          p1_if: { peer-group: hbn, type: unnumbered }
        path-selection:
          multipath: { aspath-ignore: on }                  # ← ECMP across both uplinks
        peer-group:
          hbn: { remote-as: external }                      # eBGP
```

ECMP = the loopback /32 (and connected routes) are advertised over **both**
`p0_if` and `p1_if`; `multipath.aspath-ignore: on` lets FRR install both
next-hops even with different AS paths. The ToR must run the matching eBGP
(unnumbered) on both DPU-facing ports — see D5 for the leaf config.

**ECMP reality check (carry-over finding, still true):** ECMP multiplies
*aggregate* throughput across many DPU pairs. A **single** pod-to-pod flow rides
**one** OVN geneve tunnel (one outer VTEP 5-tuple) and hashes onto **one**
uplink — so 2-path ECMP does **not** double a single pair. The benchmark must
therefore report aggregate/many-pair throughput to show the ECMP win, not a
single iperf3 stream. This is why the previous single-pair numbers looked flat.

---

## 6. Benchmarking (Phase 6+)

To make ECMP visible, the benchmark must generate **outer-header entropy**:
- Many pod pairs across both DPUs simultaneously (each pair = its own VTEP
  tunnel → hashes independently across p0/p1).
- Report **aggregate** Gbps and the per-uplink byte split (expect ≈50/50 across
  p0/p1 with enough pairs — vs the ~30:1 skew seen with one pair).
- Single-pair iperf3 stays as a latency/CPU-offload datapoint, not the ECMP
  headline.
- Compare against the host-CPU / latency / CRR metrics already in
  `BENCHMARK_REPORT.md` §5–6 (offload story is unchanged and still valid).

---

## 7. Open decisions before execution

1. **Fabric (blocking, §2):** network request to make `p0` routed, OR documented
   deviation peering over the VLAN 497 SVI, OR single-path p1-only.
2. **Cluster rebuild tooling:** confirm how the workload K8s cluster is
   (re)installed — kubeadm with `--skip-phases=addon/kube-proxy` and no CNI, so
   OVN-Kubernetes can take over.
3. **DPF version pin:** `TAG=v25.10.1`, `doca-hbn` chart 1.0.5, HBN image
   `3.2.1-doca3.2.1`, Network Operator 26.1.0 — match the `hbn-ovnk` guide for
   the v25.10.1 tag exactly.

Once §2 is decided this document becomes directly executable, Phase 0 → 6.
