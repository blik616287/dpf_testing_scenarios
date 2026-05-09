# DPF Acceleration A/B Test Plan — Pod-to-Pod

> Aim: produce a defensible apples-to-apples measurement of what the BlueField DPU adds when it offloads the OVN-Kubernetes dataplane for pod-to-pod traffic. Same CNI in both arms, same pod placement, same benchmarks, same hardware. The only variable is **where the dataplane runs** (host CPU vs DPU silicon).

---

## Why the previous host-PF benchmarks alone aren't enough

The host-PF-to-host-PF run (already completed for cluster `dpf-ovn-baseline`) measures the **fabric ceiling**: ~40 Gbps TCP, ~60 µs latency. There's no overlay, no encap, no conntrack — just L2 frames passing through the DPU eswitch. **DPU acceleration cannot improve those numbers** because there's nothing to offload. Use those numbers as the **reference ceiling**, not as cluster A.

The acceleration comparison has to use a path that has *something* for the DPU to offload — i.e., pod-to-pod traffic on an overlay network.

---

## Comparison structure

Three measurements per benchmark, all on the same physical pair of nodes, same fabric:

| Configuration | Path under test | Where dataplane runs |
|---|---|---|
| **R — Reference ceiling** | host PF ↔ host PF (no overlay) | nowhere (just L2 passthrough) |
| **A — Software baseline** | pod ↔ pod over OVN-K8s overlay | **host CPU** (DPF in passthrough; DPU is a wire) |
| **B — DPU accelerated** | pod ↔ pod over OVN-K8s overlay | **DPU silicon** (DPF VPC-OVN offload active) |

**The acceleration value is `B vs A`**, not `B vs R`. R is included to bound the discussion (B can never exceed R).

---

## Invariants both A and B must satisfy

| Item | Required state |
|---|---|
| Hardware | gpu1 + gpu2, same fabric switch port config |
| K8s version | identical (currently v1.33.6) |
| CNI | **OVN-Kubernetes** in both A and B (this is what DPF accelerates) |
| Pod placement | client pod on gpu1, server pod on gpu2 (`bench-role` labels) |
| Pod overlay encap | identical (Geneve or VXLAN — whatever OVN-K8s default) |
| Pod CIDR / service CIDR | identical |
| Benchmark images | identical (iperf3, netperf, sockperf) |
| Benchmark commands | identical (matrix from §"Benchmark Matrix" below) |
| Run count per benchmark | identical (5 runs, discard run 1 as warmup) |

The **only** intentional difference between A and B is whether the DPF VPC-OVN DPUService is deployed (B) or not (A). When deployed, OVS-DOCA on the DPU takes over the dataplane work; when not, that work runs on the host kernel.

---

## What this test should make obvious

If DPF acceleration is working as designed:

| Metric | A (host CPU) | B (DPU) | Reasoning |
|---|---|---|---|
| TCP throughput | well below R | approaches R | DPU silicon eliminates host CPU bottleneck on encap/decap |
| TCP small-packet PPS | small fraction of R | many-fold of A | per-packet softirq cost gone from host |
| TCP_RR latency | A + 5–20 µs vs R | minimal addition vs R | DPU's HW pipeline cheaper than host softirq path |
| Host CPU during peak load | several cores ~100 % | near-idle | the whole point of offload |
| TCP_CRR (conn/s) | conntrack-bound on host | DPU conntrack engine | major uplift if working |
| UDP loss at line rate | nontrivial | minimal | host kernel can't keep up; DPU can |

If A ≈ B, either (a) DPF offload is not active, (b) the workload is not stressing the dataplane, or (c) something is misconfigured. The R ceiling helps detect (b).

---

## Required cluster posture

The current cluster uses **cilium**. Cilium does not have a DPF/BlueField acceleration path in DPF v25.10.1. So the current cluster cannot be used for this A/B. Two options:

### Option I — Re-cut the cluster with OVN-K8s as CNI

This matches the original `TEST_CASES.md` plan. Two cluster profiles needed:
- `dpf-ovn-baseline`: edge-native BYOI + OVN-K8s + DPF Zero Trust **Passthrough** addon. OVN runs on host. DPU is in passthrough. This is the **A** configuration.
- `dpf-ovn-accelerated`: edge-native BYOI + OVN-K8s + DPF Zero Trust + **VPC-OVN DPUService** addon (per `docs/public/user-guides/zero-trust/use-cases/vpc/`). OVN dataplane offloaded to DPU. This is the **B** configuration.

Sequence:
1. Tear down current `dpf-ovn-baseline` (cilium-based) cluster.
2. Deploy `dpf-ovn-baseline` with OVN-K8s. Run benchmarks → A data.
3. Tear down. Deploy `dpf-ovn-accelerated`. Verify offload is active. Run benchmarks → B data.
4. Compare.

### Option II — Cilium with native routing as A, cilium-on-DPU as B

Cilium does have a DPU offload path via [cilium-mesh](https://github.com/cilium/cilium-mesh) but it's not part of DPF. Not recommended unless you specifically want to test cilium acceleration; doesn't match "DPF accelerates OVN-K8s" story.

### Option III — Two-arm test inside a single cluster (lightest)

Possible if both arms can coexist by selecting different network attachments per pod, but DPF VPC-OVN uses cluster-wide CNI; not a clean comparison. Skip unless time-constrained.

**Recommendation: Option I.** It's the supported, defensible comparison; results map cleanly to NVIDIA's positioning.

---

## Benchmark matrix (identical in A and B; from TEST_CASES.md §"Test Case 2")

| # | Benchmark | Tool | Parameters | Duration | Runs |
|---|---|---|---|---|---|
| 1 | TCP throughput, 1 stream | iperf3 | `-c <ip> -t 60 --json` | 60 s | 5 |
| 2 | TCP throughput, 8 streams | iperf3 | `-c <ip> -t 60 -P 8 --json` | 60 s | 5 |
| 3 | TCP throughput, 16 streams | iperf3 | `-c <ip> -t 60 -P 16 --json` | 60 s | 5 |
| 4 | UDP throughput (max) | iperf3 | `-c <ip> -u -b 0 -t 60 --json` | 60 s | 5 |
| 5 | UDP, 64 B packets | iperf3 | `-c <ip> -u -b 0 -l 64 -t 60 --json` | 60 s | 5 |
| 6 | UDP, 1400 B packets | iperf3 | `-c <ip> -u -b 0 -l 1400 -t 60 --json` | 60 s | 5 |
| 7 | TCP request/response | netperf | `-H <ip> -t TCP_RR -l 60` | 60 s | 5 |
| 8 | UDP request/response | netperf | `-H <ip> -t UDP_RR -l 60` | 60 s | 5 |
| 9 | TCP stream, 1 B msgs | netperf | `-H <ip> -t TCP_STREAM -l 60 -- -m 1` | 60 s | 5 |
| 10 | Tail latency (P50/P99/P99.9) | sockperf | `ping-pong -i <ip> -t 60 --full-rtt` | 60 s | 5 |
| 11 | Conn rate | netperf | `-H <ip> -t TCP_CRR -l 60` | 60 s | 5 |

Discard run 1 as warmup. Idle 30 s between runs.

### Per-run supplementary captures
- `mpstat -P ALL 1 60` on **both** client and server hosts (CPU per-core)
- `ethtool -S enp14s0f0np0` delta on both hosts
- B only: `kubectl exec -n dpf-operator-system <ovn-controller-on-DPU pod> -- ovs-appctl dpctl/dump-flows type=offloaded | wc -l` to confirm flows are HW-offloaded
- `/proc/interrupts` delta on both hosts (look for irq distribution differences)

### Pod manifests

```yaml
# server (gpu2)
apiVersion: v1
kind: Pod
metadata:
  name: bench-server
  labels: {bench-role: server}
spec:
  nodeSelector: {bench-role: server}
  containers:
  - name: tools
    image: networkstatic/iperf3
    command: ["sleep","infinity"]
    securityContext: {capabilities: {add: ["NET_ADMIN"]}}
    ports:
    - containerPort: 5201
    - containerPort: 12865   # netserver
    - containerPort: 11111   # sockperf
  terminationGracePeriodSeconds: 0
```

```yaml
# client (gpu1)
apiVersion: v1
kind: Pod
metadata:
  name: bench-client
  labels: {bench-role: client}
spec:
  nodeSelector: {bench-role: client}
  containers:
  - name: tools
    image: networkstatic/iperf3
    command: ["sleep","infinity"]
    securityContext: {capabilities: {add: ["NET_ADMIN"]}}
  terminationGracePeriodSeconds: 0
```

The `networkstatic/iperf3` image needs `netperf` and `sockperf` binaries added — recommend a small derived image with all three (or use one container per tool).

The benchmark driver runs from outside via `kubectl exec`:
```bash
kubectl exec bench-client -- iperf3 -c <bench-server-pod-ip> -t 60 --json
```

---

## How to verify offload is actually active in B (critical)

Before declaring B's numbers valid, confirm:

1. **OVN-K8s is the active CNI** on the cluster
   ```
   kubectl get pods -n ovn-kubernetes
   ```
2. **DPU has VPC-OVN DPUService running**
   ```
   kubectl get dpuservices -A | grep -i ovn
   ```
3. **Flows are being HW-offloaded** during a sustained iperf3 run, run on the DPU OS:
   ```
   sudo ovs-appctl dpctl/dump-flows type=offloaded | wc -l   # > 0 during traffic
   ```
4. **Host CPU during heavy iperf3** is *low* in B but *high* in A — visible in `mpstat`. If host CPU is high in B, offload isn't actually engaged.

If any of these checks fail in B, the B numbers are not valid acceleration measurements — they're software-OVN-K8s with extra steps. Re-investigate before recording results.

---

## Deliverables

1. **Three CSV result files**: `results/host-pf-reference/`, `results/dpf-ovn-baseline/`, `results/dpf-ovn-accelerated/` — one row per (benchmark, run).
2. **Summary table**: 11 rows × 4 columns (R / A / B / `B−A` delta) with mean ± stddev.
3. **Charts**: bar chart per benchmark with all three configs side-by-side, plus a CPU heatmap from `mpstat` for the heaviest TCP run.
4. **Validation evidence** (B): screenshot or log showing `dpctl/dump-flows type=offloaded | wc -l > 0` during a benchmark.

---

## Summary

- The host-PF benchmarks already done are the **reference ceiling R**, not configuration A.
- A and B both run pod-to-pod through the same OVN-K8s overlay; the only variable is where the dataplane runs.
- The current cilium cluster cannot provide either A or B. Re-cut as `Option I` for the real comparison.
- For the comparison to be defensible, B must be verified to be HW-offloaded (`dpctl/dump-flows type=offloaded`) and host CPU usage must drop in B.
