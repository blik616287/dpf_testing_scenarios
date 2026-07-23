# MaaS ZT add-on cluster profiles — apples-to-apples parity with `dpf_testing_scenarios/§7`

Two add-on profiles that pair with **`DPF Zero Trust Control Plane - MaaS`**
(`69834a90e0eb282a294a8648`, Palette project `ISC-Strategic-Alliance`) to
reproduce the previously-measured baseline / accelerated / HBN benchmark arms on
MaaS-provisioned metal in the `forde-dpf` pool.

## Profiles

### `vpc-ovn-v2-parametrized/`

Fork of upstream `DPF ZT Use Case - VPC-OVN Accelerated v2`
(`69fb7b33c4934d2627f3a67c`), with the hardcoded IPs
(NB/SB endpoint 172.16.30.90, VTEP subnet 172.16.97.96/27, VPC gateway subnet
172.16.97.128/27) replaced by `{{ .spectro.var.* }}` placeholders so the same
profile can be reused across different MaaS lease outcomes.

Preserves the 5 upstream workaround CronJobs verbatim:
- dpu-install-interface-fixer
- dpunode-external-reboot-acker
- dpu-bmc-rshim-forcer
- tenant-bootstrap-token-generator
- dpu-rebooted-condition-patcher

### `hbn-v2/`

Fresh HBN payload, NOT the broken upstream `DPF Zero Trust Use Case - DOCA HBN`
(`698dd2dd4b0c719b6c763605`). The broken profile uses unnumbered BGP + EVPN
VXLAN + RED/BLUE VLAN tenants — the fabric leaf is configured for numbered /31
eBGP with a flat underlay per `env_fabric_switchports` / `bgp-ecmp-state.txt`,
so unnumbered never establishes.

This profile encodes the actually-measured §7 topology:
- 4 uplinks, ALL /31 routed eBGP
- Leaf AS 65001, DPU1 AS 65010, DPU2 AS 65020
- MTU 9000 on swp interfaces
- No EVPN, no VXLAN, no VLAN tenants — pure IPv4 underlay
- ECMP with `aspath-ignore on`
- Loopback IPs from `loopback` DPUServiceIPAM
- Same 5 workaround CronJobs from vpc-ovn-v2 + a `dpu-use-case=hbn` labeler

## Required cluster-create variables

Both profiles consume `{{ .spectro.var.* }}` placeholders that must be supplied
at cluster-create time. Baseline values for the `forde-dpf` topology below;
substitute per deploy.

### Common (both profiles)

| Variable | Value for forde-dpf | Purpose |
|---|---|---|
| `BfbUrl` | `https://content.mellanox.com/BlueField/BFBs/Ubuntu24.04/bf-bundle-3.2.1-34_25.11_ubuntu-24.04_64k_prod.bfb` | BFB image for BFB CR |

### vpc-ovn-v2-parametrized only

| Variable | Value | Purpose |
|---|---|---|
| `tenantCPHostIP` | (host IP of the CP node hosting kamaji NodePorts) | ovn-central NB/SB access |
| `ovnNbNodePort` | `30641` | NB NodePort on tenant cluster |
| `ovnSbNodePort` | `30642` | SB NodePort on tenant cluster |
| `VtepSubnet` | `172.16.97.96/27` | Geneve VTEP pool |
| `VtepGateway` | `172.16.97.97` | VTEP gateway |
| `VpcGatewaySubnet` | `172.16.97.128/27` | VPC egress gw pool |
| `VpcGatewayGateway` | `172.16.97.129` | VPC gw first-hop |

### hbn-v2 only

| Variable | Value for forde-dpf | Purpose |
|---|---|---|
| `HbnChartVersion` | `1.0.5` | doca-hbn Helm chart tag |
| `HbnImageTag` | `3.2.1-doca3.2.1` | doca-hbn container image tag |
| `HbnSwpMTU` | `9000` | swp link MTU on p0_if/p1_if/pf0hpf_if |
| `HbnLoopbackCIDR` | `11.0.0.0/24` | Loopback IPAM pool |
| `FabricLeafAsn` | `65001` | Leaf BGP ASN |
| `Dpu1HostnamePattern` | `*mt24326005fn*` | gpu1 DPU hostname glob |
| `Dpu1BgpAsn` | `65010` | gpu1 DPU BGP ASN |
| `Dpu1P0LocalIp` | `172.16.97.241` | gpu1 p0 local /31 |
| `Dpu1P0PeerIp` | `172.16.97.240` | gpu1 p0 leaf peer |
| `Dpu1P1LocalIp` | `172.16.97.249` | gpu1 p1 local /31 |
| `Dpu1P1PeerIp` | `172.16.97.248` | gpu1 p1 leaf peer |
| `Dpu2HostnamePattern` | `*mt2439600dak*` | gpu2 DPU hostname glob |
| `Dpu2BgpAsn` | `65020` | gpu2 DPU BGP ASN |
| `Dpu2P0LocalIp` | `172.16.97.245` | gpu2 p0 local /31 |
| `Dpu2P0PeerIp` | `172.16.97.244` | gpu2 p0 leaf peer |
| `Dpu2P1LocalIp` | `172.16.97.251` | gpu2 p1 local /31 |
| `Dpu2P1PeerIp` | `172.16.97.250` | gpu2 p1 leaf peer |

## Published profile revisions
- HBN v29 (`6a62a9b2045821571a9aa1b1`) — VF re-materialize self-heal + dynamic multiport eSwitch PCI (published 2026-07-23). Deploy with infra v14 `6a615582e61b15d543fb38aa`; payload `maas-create-v30.json`.
