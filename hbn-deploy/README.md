# HBN Full Takeover — Deploy Runbook

Hand-rolled deployment of the DOCA HBN service (`nvcr.io/nvidia/doca/doca_hbn:3.2.1-doca3.2.1`)
as a kubelet static pod, replacing host FRR and VPC-OVN as the L3/L2 data plane.

## Files

| Path | Purpose |
|---|---|
| `gpu1/startup.yaml` | NVUE config for gpu1 (AS 65010, lo 10.99.99.1, p0_if=.98/27, p1_if=.249/31) |
| `gpu2/startup.yaml` | NVUE config for gpu2 (AS 65020, lo 10.99.99.2, p0_if=.102/27, p1_if=.251/31) |
| `manifests/doca_hbn.yaml` | kubelet static pod manifest (hostNetwork, privileged, mounts) |
| `scripts/01-snapshot.sh` | Snapshot pre-takeover state to `/var/lib/hbn/pre-takeover/<ts>/` |
| `scripts/02-create-sfs.sh` | Create SF representors (`p0_if`, `p1_if`, `pf0hpf_if`) + wire to `br-hbn` |
| `scripts/03-deploy.sh` | Drop static pod manifest, stop host FRR, stage startup.yaml |
| `scripts/04-verify.sh` | Post-deploy verification (BGP/EVPN/ECMP/nl2docad) |

## Pre-flight (already done)

- [x] DPDK p0 + p1 with hardware offload on both DPUs
- [x] 2-path ECMP underlay (BGP /31 + VLAN 497 SVI) Established and route-installed
- [x] HBN image pulled to both DPUs (`crictl images | grep hbn`)
- [x] HBN container internals understood (supervisord, FRR, nl2docad, `/tmp/config-data`)
- [x] startup.yaml files authored per DPU
- [x] Static pod manifest authored

## Execution order (per DPU — do gpu1 first, validate, then gpu2)

> **Maintenance window required.** Each step changes state on the live DPU.
> Workload pods using VPC-OVN will be impacted starting at step 4 (VPC-OVN teardown).

### Step 1 — Snapshot (safe, repeatable)
```bash
ssh ubuntu@<DPU>  bash /path/to/hbn-deploy/scripts/01-snapshot.sh
```
Captures FRR config, OVS topology, IP/route state to `/var/lib/hbn/pre-takeover/latest/`.

### Step 2 — Create SFs + wire br-hbn (additive, no traffic disruption)
```bash
ssh ubuntu@<DPU>  bash /path/to/hbn-deploy/scripts/02-create-sfs.sh
```
- Creates 3 SFs on PF0/PF1 via devlink, renames to `p0_if`, `p1_if`, `pf0hpf_if`
- Adds them to `br-hbn` as type=dpdk ports
- Creates patch ports `br-hbn↔br-sfc` and `br-hbn↔br-p1`
- **Verify before continuing**: `ovs-vsctl show` shows br-hbn populated, leaf BGP still Established on host FRR.

### Step 3 — Drop manifest, stop host FRR, deploy HBN (DESTRUCTIVE — host BGP goes down)
```bash
ssh ubuntu@<DPU>  HBN_HOST_ROLE=gpu1 bash /path/to/hbn-deploy/scripts/03-deploy.sh
```
- Copies `startup.yaml` to `/var/lib/hbn/config-data/` (host) → `/tmp/config-data/` (in container)
- Stops + disables `frr.service` on host
- Flushes kernel IPs from `p1_l3` and `ovnvtep` (HBN will reclaim them via SF representors)
- Drops `manifests/doca_hbn.yaml` to `/etc/kubelet.d/`
- Waits up to 2 min for kubelet to start the pod
- Tails `supervisorctl status` inside container

**Downtime window**: BGP/forwarding offline between host-FRR-stop and HBN-FRR-converged.
Expect 30–90 seconds; longer if startup.yaml has a syntax error.

### Step 4 — VPC-OVN teardown (BREAKS pod networking — only after pf0hpf_if migration)
NOT automated. Manual steps:
1. `kubectl drain <dpu-node>` to evict pod workloads
2. Delete `br-int` and `br-ovn-ext` (`ovs-vsctl del-br ...`)
3. Stop `vpc-ovn-node`, `ovn-controller`, `sfc-controller` daemonsets on the DPU
4. Re-add workload pods using HBN's `pf0hpf_if` access port on VLAN 11 (matches startup.yaml)

### Step 5 — Verify
```bash
ssh ubuntu@<DPU>  bash /path/to/hbn-deploy/scripts/04-verify.sh
```
Expected:
- `supervisorctl status` — frr/nl2doca/nvued/neighmgr all RUNNING
- `vtysh -c "show ip bgp summary"` — 2 numbered neighbors Established (.248 + .125)
- `vtysh -c "show bgp l2vpn evpn summary"` — same 2 neighbors Established for EVPN AF
- `vtysh -c "show ip route"` — ECMP routes with 2 next-hops to remote loopback
- `/cumulus/nl2docad/run/software-tables/19_ecmp_table` — non-empty (ECMP offloaded to ASIC)

## Rollback

If anything goes wrong at Step 3 or after:
```bash
# Stop the container
sudo rm /etc/kubelet.d/doca_hbn.yaml
sudo crictl rmp -f $(sudo crictl pods -q --name doca-hbn)

# Restore host FRR
sudo systemctl enable --now frr
SNAP=/var/lib/hbn/pre-takeover/latest
sudo vtysh -c "configure terminal" -c "$(cat $SNAP/frr-running.conf)"

# Restore kernel IPs
sudo ip addr add 172.16.97.249/31 dev p1_l3      # gpu1; .251 for gpu2
sudo ip addr add 172.16.97.98/27 dev ovnvtep     # gpu1; .102 for gpu2

# Validate BGP comes back on host
sudo vtysh -c "show ip bgp summary"
```

## Known risks

1. **MTU mismatch** is the #1 BGP failure mode per NVIDIA docs. We use 9216 everywhere;
   leaf side confirmed 9216 capable on the /31 links (engineer pre-stage).
2. **TX checksum offload** quirk we hit on `p1_l3` may reappear on the new SF representors.
   If BGP TCP/179 fails to establish post-takeover, try
   `ethtool -K p0_if tx off; ethtool -K p1_if tx off` inside the container.
3. **Leaf EVPN support unknown**. Underlay BGP will work regardless. If leaf is not
   EVPN-capable, the L2VPN-EVPN AF will negotiate but no MAC/IP routes will exchange via
   leaf — DPU↔DPU EVPN will still work directly over underlay reachability.
4. **VPC-OVN pod workload disruption** if Step 4 is run. Pods need re-deployment via
   HBN's pf0hpf_if access port.
