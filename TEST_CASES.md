# DPF A/B Performance Test Cases

## Table of Contents

- [Test Environment](#test-environment)
- [Test Case 1: OVN-Only — Non-Accelerated vs BF-Accelerated](#test-case-1-ovn-only--non-accelerated-vs-bf-accelerated)
- [Test Case 2: OVN-Only — A/B Performance Metrics](#test-case-2-ovn-only--ab-performance-metrics)
- [Test Case 3: OVN+HBN — Advanced BF-Accelerated OVN with BGP/ECMP](#test-case-3-ovnhbn--advanced-bf-accelerated-ovn-with-bgpecmp)
- [Test Case 4: OVN+HBN — A/B Performance Metrics](#test-case-4-ovnhbn--ab-performance-metrics)
- [Benchmark Tools](#benchmark-tools)
- [Pod Placement Strategy](#pod-placement-strategy)
- [Results Collection](#results-collection)

---

## Test Environment

### Hardware

| Component | Specification |
|-----------|--------------|
| Nodes | 2x bare-metal servers |
| DPU | NVIDIA BlueField-3 (per node) |
| Connectivity | 100GbE / 200GbE (BlueField uplinks) |
| Node 1 Role | Control plane + worker |
| Node 2 Role | Worker |

### Cluster Configurations

All clusters use the **DPF Zero Trust Control Plane - Agent** edge-native infrastructure profile. The only variable between test runs is the addon profile combination, which controls how the BlueField DPU processes network traffic.

| Cluster | Infra Profile | Addon Profiles | DPU Behavior |
|---------|--------------|----------------|--------------|
| `dpf-ovn-baseline` | DPF Zero Trust CP - Agent | Spectro-DPU-DPF-CP-Configs, **Passthrough** | DPU is present but passes traffic through without processing. OVN-K8s runs entirely on the host CPU. |
| `dpf-ovn-accelerated` | DPF Zero Trust CP - Agent | Spectro-DPU-DPF-CP-Configs | OVN dataplane is offloaded to the BlueField DPU. The DPU handles OVS flow processing, connection tracking, and packet forwarding in hardware. |
| `dpf-ovn-hbn` | DPF Zero Trust CP - Agent | Spectro-DPU-DPF-CP-Configs, **DOCA HBN** | OVN dataplane offloaded to BlueField + DOCA Host-Based Networking enabled. HBN adds BGP peering from each DPU to the ToR switch, enabling ECMP multi-path routing across uplinks. |

### Deployment Sequence

The same 2 physical nodes are reused for all tests. Clusters are deployed, tested, and torn down sequentially to ensure clean state between runs:

```
Deploy dpf-ovn-baseline → Run benchmarks → Collect results → Tear down
Deploy dpf-ovn-accelerated → Run benchmarks → Collect results → Tear down
Deploy dpf-ovn-hbn → Run benchmarks → Collect results → Tear down
```

---

## Test Case 1: OVN-Only — Non-Accelerated vs BF-Accelerated

### Objective

Quantify the performance uplift of offloading the OVN-Kubernetes dataplane from the host CPU to the NVIDIA BlueField DPU using DPF, compared to a standard software-only OVN-K8s deployment.

### Hypothesis

With DPF offloading OVN dataplane operations (OVS flow matching, connection tracking, encapsulation/decapsulation) to the BlueField DPU's hardware accelerators, we expect to observe:

- Significant increase in throughput (approaching line rate)
- Reduction in latency (fewer CPU hops in the packet path)
- Dramatic reduction in host CPU utilization for network processing
- Higher sustained packet-per-second (PPS) rates

### Configurations Under Test

| Side | Cluster | Description |
|------|---------|-------------|
| **A** (Baseline) | `dpf-ovn-baseline` | OVN-K8s running on host CPU. BlueField DPU is in passthrough mode — present but not offloading any network functions. All OVS flow processing, connection tracking, and VXLAN encapsulation happen in host software. |
| **B** (Accelerated) | `dpf-ovn-accelerated` | OVN-K8s with DPF offload. The BlueField DPU handles OVS dataplane operations in hardware. The host CPU is freed from network processing. OVN control plane still runs on host; only the datapath is offloaded. |

### What Is Being Compared

The **only variable** between A and B is whether the BlueField DPU actively processes OVN dataplane traffic. Both clusters:
- Use identical hardware
- Run the same Kubernetes version and OVN-K8s CNI
- Have the same pod placement (client on Node 1, server on Node 2)
- Use the same benchmark tools and parameters

This isolates the DPF offload as the single independent variable.

### Metrics to Capture

| Metric | Tool | Why It Matters |
|--------|------|----------------|
| TCP throughput (Gbps) | iperf3 | Primary measure of bulk data transfer performance |
| UDP throughput (Gbps) | iperf3 | Measures forwarding without TCP congestion control overhead |
| TCP latency (us) | netperf (TCP_RR) | Round-trip latency for request/response workloads |
| UDP latency (us) | netperf (UDP_RR) | Minimum achievable latency without TCP stack |
| Packets per second (PPS) | iperf3 (small packets) | Stress-tests the forwarding plane with high packet rates |
| Host CPU utilization (%) | mpstat / node_exporter | Measures CPU freed by offloading to DPU |
| P50/P99 latency (us) | sockperf | Tail latency under load |
| Jitter (us) | iperf3 -u | Latency variance, critical for real-time workloads |
| OVS flow offload count | `ovs-appctl dpctl/dump-flows type=offloaded` | Confirms DPF is actually offloading flows (B only) |

### Test Procedure

#### Phase 1: Baseline (Cluster A — `dpf-ovn-baseline`)

1. Deploy `dpf-ovn-baseline` cluster
2. Wait for `Running` state
3. Deploy iperf3 server pod on Node 2, iperf3 client pod on Node 1 (see [Pod Placement](#pod-placement-strategy))
4. Run benchmark suite:
   - TCP throughput: `iperf3 -c <server-ip> -t 60 -P 8`
   - UDP throughput: `iperf3 -c <server-ip> -u -b 0 -t 60`
   - TCP latency: `netperf -H <server-ip> -t TCP_RR -l 60`
   - UDP latency: `netperf -H <server-ip> -t UDP_RR -l 60`
   - Small packet PPS: `iperf3 -c <server-ip> -u -b 0 -l 64 -t 60`
   - Tail latency: `sockperf ping-pong -i <server-ip> -t 60 --full-log`
5. Capture host CPU utilization during each test: `mpstat -P ALL 1 60`
6. Record all results
7. Tear down cluster

#### Phase 2: Accelerated (Cluster B — `dpf-ovn-accelerated`)

1. Deploy `dpf-ovn-accelerated` cluster
2. Wait for `Running` state
3. Verify DPF offload is active:
   - SSH to node, run `ovs-appctl dpctl/dump-flows type=offloaded | wc -l`
   - Confirm offloaded flow count > 0 after traffic starts
4. Deploy identical benchmark pods with same placement
5. Run the exact same benchmark suite as Phase 1
6. Capture host CPU utilization during each test
7. Record all results
8. Tear down cluster

#### Phase 3: Analysis

Compare A vs B across all metrics. Key comparisons:
- Throughput uplift percentage
- Latency reduction percentage
- CPU utilization reduction (this should be dramatic)
- PPS improvement factor

### Expected Outcomes

| Metric | Expected Direction | Reasoning |
|--------|--------------------|-----------|
| TCP throughput | B >> A | Hardware offload eliminates CPU bottleneck in packet path |
| Latency | B < A | Fewer context switches; DPU processes packets in hardware pipeline |
| Host CPU usage | B << A | Network processing moved off host CPU entirely |
| PPS | B >> A | DPU ASIC handles small packets far more efficiently than host CPU |

---

## Test Case 2: OVN-Only — A/B Performance Metrics

### Objective

Produce a comprehensive, presentation-ready A/B comparison dataset across the full range of performance metrics for the OVN-only use case. This test case uses the same clusters as Test Case 1 but focuses on structured, repeatable measurement with statistical rigor.

### Methodology

Each benchmark is run **5 times** on each cluster configuration to establish statistical confidence. Results are reported as mean with standard deviation.

### Benchmark Matrix

| # | Benchmark | Tool | Parameters | Duration | Runs |
|---|-----------|------|------------|----------|------|
| 1 | Single-stream TCP throughput | iperf3 | `-c <ip> -t 60` | 60s | 5 |
| 2 | Multi-stream TCP throughput (8 streams) | iperf3 | `-c <ip> -t 60 -P 8` | 60s | 5 |
| 3 | Multi-stream TCP throughput (16 streams) | iperf3 | `-c <ip> -t 60 -P 16` | 60s | 5 |
| 4 | UDP throughput (max bandwidth) | iperf3 | `-c <ip> -u -b 0 -t 60` | 60s | 5 |
| 5 | UDP throughput (64-byte packets) | iperf3 | `-c <ip> -u -b 0 -l 64 -t 60` | 60s | 5 |
| 6 | UDP throughput (1400-byte packets) | iperf3 | `-c <ip> -u -b 0 -l 1400 -t 60` | 60s | 5 |
| 7 | TCP request/response latency | netperf | `-H <ip> -t TCP_RR -l 60` | 60s | 5 |
| 8 | UDP request/response latency | netperf | `-H <ip> -t UDP_RR -l 60` | 60s | 5 |
| 9 | TCP streaming latency (1-byte) | netperf | `-H <ip> -t TCP_STREAM -l 60 -- -m 1` | 60s | 5 |
| 10 | Tail latency (P50/P99/P99.9) | sockperf | `ping-pong -i <ip> -t 60` | 60s | 5 |
| 11 | Sustained connections/sec | netperf | `-H <ip> -t TCP_CRR -l 60` | 60s | 5 |

### Supplementary Data Collected Per Run

- **Host CPU**: `mpstat -P ALL 1` (per-core utilization over test duration)
- **DPU offload stats** (B only): `ovs-appctl dpctl/dump-flows type=offloaded | wc -l`
- **Interrupt counts**: `/proc/interrupts` delta before/after each test
- **Network interface counters**: `ethtool -S <iface>` delta before/after

### Deliverables

1. **Summary table**: Mean and stddev for every metric, side-by-side A vs B
2. **Bar charts**: Throughput, latency, PPS, and CPU for each benchmark
3. **Latency histogram**: P50/P95/P99/P99.9 distribution overlay for A vs B
4. **CPU heatmap**: Per-core utilization during peak throughput test, A vs B

---

## Test Case 3: OVN+HBN — Advanced BF-Accelerated OVN with BGP/ECMP

### Objective

Demonstrate the performance characteristics of the advanced DPF networking stack that combines BF-accelerated OVN-K8s with DOCA Host-Based Networking (HBN). HBN enables BGP peering from each BlueField DPU directly to the Top-of-Rack (ToR) switch, providing Equal-Cost Multi-Path (ECMP) routing across multiple uplinks.

### Background: What HBN Adds

In the `dpf-ovn-accelerated` configuration, traffic between nodes follows a single path through the fabric. With HBN enabled:

- Each BlueField DPU establishes **BGP sessions** with the ToR switch
- The ToR learns multiple equal-cost paths to each pod subnet
- Traffic is distributed across all available uplinks using **ECMP hashing**
- This provides both **higher aggregate bandwidth** and **path redundancy**

```
                    ┌──────────┐
                    │ToR Switch│
                    │ (BGP/ECMP)│
                    └─┬──────┬─┘
                      │      │
              ┌───────┘      └───────┐
              │                      │
        ┌─────┴─────┐         ┌─────┴─────┐
        │ BlueField │         │ BlueField │
        │  DPU + HBN│         │  DPU + HBN│
        │  (BGP peer)│        │  (BGP peer)│
        └─────┬─────┘         └─────┬─────┘
              │                      │
        ┌─────┴─────┐         ┌─────┴─────┐
        │  Node 1   │         │  Node 2   │
        │  (CP+W)   │         │  (Worker) │
        └───────────┘         └───────────┘
```

### Configurations Under Test

This test case supports **two comparisons** using three cluster deployments:

#### Comparison A: Full Stack vs No Acceleration

| Side | Cluster | Description |
|------|---------|-------------|
| **A** | `dpf-ovn-baseline` | Passthrough — no DPF, no HBN. Software OVN on host CPU. |
| **B** | `dpf-ovn-hbn` | Full DPF + HBN stack — OVN offload + BGP/ECMP routing. |

This measures the **total uplift** of the complete DPF+HBN solution compared to a non-accelerated baseline.

#### Comparison B: OVN-Only Offload vs OVN + HBN

| Side | Cluster | Description |
|------|---------|-------------|
| **A** | `dpf-ovn-accelerated` | DPF OVN offload only — single-path forwarding through fabric. |
| **B** | `dpf-ovn-hbn` | DPF OVN offload + HBN — multi-path ECMP routing through fabric. |

This isolates the **incremental value of HBN** on top of DPF OVN offload. The OVN offload is identical in both; the only difference is whether HBN's BGP/ECMP routing is active.

### Metrics to Capture

All metrics from Test Cases 1 and 2, plus HBN-specific metrics:

| Metric | Tool | Why It Matters |
|--------|------|----------------|
| BGP session state | `birdc show protocols` (on DPU) | Confirms BGP peering is established with ToR |
| ECMP path count | `birdc show route` (on DPU) | Validates multiple equal-cost paths are learned |
| Per-uplink traffic distribution | `ethtool -S` per interface | Confirms ECMP is actually distributing traffic across uplinks |
| Multi-flow aggregate throughput | iperf3 (multiple parallel flows) | ECMP benefits increase with multiple flows due to hash distribution |
| Single-flow throughput | iperf3 (single stream) | ECMP may not improve single flows (pinned to one path by hash) |
| Failover time | Kill one uplink, measure recovery | HBN should reroute via surviving paths within BGP convergence time |

### Test Procedure

#### Phase 1: Validate HBN is Active

Before running benchmarks on `dpf-ovn-hbn`, confirm:

1. BGP sessions are established:
   ```bash
   # On the DPU (via SSH or kubectl exec into DPU management pod)
   birdc show protocols
   # Should show BGP sessions in "Established" state
   ```

2. ECMP routes are learned:
   ```bash
   birdc show route
   # Should show multiple next-hops for pod subnets
   ```

3. OVS offload is active:
   ```bash
   ovs-appctl dpctl/dump-flows type=offloaded | wc -l
   # Should be > 0 once traffic flows
   ```

#### Phase 2: Run Benchmarks

Run the full benchmark matrix from Test Case 2 on `dpf-ovn-hbn`. Key additions:

- **Multi-flow throughput scaling**: Run iperf3 with 1, 2, 4, 8, 16, 32 parallel streams to demonstrate ECMP scaling as more flows hit different hash buckets
- **Per-uplink monitoring**: Capture `ethtool -S` on each physical interface before and after to show traffic distribution

#### Phase 3: Failover Test (if supported by topology)

1. Establish a sustained iperf3 flow between pods
2. Administratively disable one uplink on Node 1
3. Measure:
   - Time to detect failure (BGP hold timer expiry)
   - Time to re-converge (traffic shifts to remaining paths)
   - Packet loss during failover
4. Re-enable uplink, measure re-convergence

### Expected Outcomes

| Metric | OVN Baseline → OVN+HBN | OVN Accel → OVN+HBN |
|--------|------------------------|----------------------|
| Multi-flow throughput | Massive uplift (offload + multi-path) | Moderate uplift (multi-path aggregation) |
| Single-flow throughput | Large uplift (offload) | Minimal change (single hash bucket) |
| Latency | Significant reduction | Similar or slight improvement |
| CPU utilization | Dramatic reduction | Similar (already offloaded) |
| Path redundancy | N/A → Active ECMP | N/A → Active ECMP |

---

## Test Case 4: OVN+HBN — A/B Performance Metrics

### Objective

Produce structured, repeatable A/B datasets for the OVN+HBN comparisons with statistical rigor, suitable for executive-level reporting and customer-facing presentations.

### Test Matrix

The full benchmark matrix from Test Case 2 is run on all three clusters. This produces two A/B comparison datasets:

#### Dataset 1: Full Stack Uplift (Baseline vs OVN+HBN)

| Benchmark | `dpf-ovn-baseline` (A) | `dpf-ovn-hbn` (B) | Delta |
|-----------|------------------------|--------------------|-------|
| Single-stream TCP (Gbps) | _measured_ | _measured_ | _calculated_ |
| 8-stream TCP (Gbps) | _measured_ | _measured_ | _calculated_ |
| 16-stream TCP (Gbps) | _measured_ | _measured_ | _calculated_ |
| UDP max throughput (Gbps) | _measured_ | _measured_ | _calculated_ |
| TCP_RR latency (us) | _measured_ | _measured_ | _calculated_ |
| UDP_RR latency (us) | _measured_ | _measured_ | _calculated_ |
| PPS (64-byte) | _measured_ | _measured_ | _calculated_ |
| TCP_CRR (conn/s) | _measured_ | _measured_ | _calculated_ |
| Host CPU (%) | _measured_ | _measured_ | _calculated_ |
| P99 latency (us) | _measured_ | _measured_ | _calculated_ |

#### Dataset 2: HBN Incremental Value (OVN Accel vs OVN+HBN)

| Benchmark | `dpf-ovn-accelerated` (A) | `dpf-ovn-hbn` (B) | Delta |
|-----------|---------------------------|--------------------|-------|
| Single-stream TCP (Gbps) | _measured_ | _measured_ | _calculated_ |
| 8-stream TCP (Gbps) | _measured_ | _measured_ | _calculated_ |
| 16-stream TCP (Gbps) | _measured_ | _measured_ | _calculated_ |
| UDP max throughput (Gbps) | _measured_ | _measured_ | _calculated_ |
| TCP_RR latency (us) | _measured_ | _measured_ | _calculated_ |
| UDP_RR latency (us) | _measured_ | _measured_ | _calculated_ |
| PPS (64-byte) | _measured_ | _measured_ | _calculated_ |
| TCP_CRR (conn/s) | _measured_ | _measured_ | _calculated_ |
| Host CPU (%) | _measured_ | _measured_ | _calculated_ |
| P99 latency (us) | _measured_ | _measured_ | _calculated_ |

### ECMP Scaling Benchmark (HBN-Specific)

This benchmark is unique to the OVN+HBN test case and demonstrates how ECMP improves aggregate throughput as the number of parallel flows increases.

| # Parallel Flows | `dpf-ovn-accelerated` (single path) | `dpf-ovn-hbn` (ECMP) | ECMP Uplift |
|-------------------|--------------------------------------|-----------------------|-------------|
| 1 | _measured_ | _measured_ | _calculated_ |
| 2 | _measured_ | _measured_ | _calculated_ |
| 4 | _measured_ | _measured_ | _calculated_ |
| 8 | _measured_ | _measured_ | _calculated_ |
| 16 | _measured_ | _measured_ | _calculated_ |
| 32 | _measured_ | _measured_ | _calculated_ |

### Statistical Requirements

- **Minimum 5 runs** per benchmark per cluster
- Report: **mean**, **standard deviation**, **min**, **max**
- Discard the first run of each benchmark as warmup
- Allow 30 seconds of idle time between consecutive runs
- Capture timestamps for every run to enable post-hoc correlation with system events

### Deliverables

1. **Executive summary**: One-page table with key metrics and uplift percentages
2. **Detailed results**: Full benchmark matrix with statistical data
3. **Comparison charts**:
   - Side-by-side bar charts for throughput, latency, CPU
   - Latency distribution overlays (CDF or histogram)
   - ECMP scaling curve (flows vs aggregate throughput)
4. **System validation**: Evidence of DPF offload (flow counts) and HBN activation (BGP state, ECMP paths)
5. **Raw data**: CSV exports of all individual runs for reproducibility

---

## Benchmark Tools

### Required Tools (deploy as pods)

| Tool | Purpose | Image |
|------|---------|-------|
| [iperf3](https://iperf.fr/) | Throughput and UDP jitter measurement | `networkstatic/iperf3` |
| [netperf](https://hewlettpackard.github.io/netperf/) | Latency (TCP_RR, UDP_RR) and connection rate (TCP_CRR) | `networkstatic/netperf` |
| [sockperf](https://github.com/Mellanox/sockperf) | High-precision tail latency measurement | `mellanox/sockperf` |

### System Tools (on host)

| Tool | Purpose |
|------|---------|
| `mpstat` | Per-core CPU utilization |
| `ethtool -S` | NIC interface counters |
| `ovs-appctl` | OVS flow statistics and offload verification |
| `birdc` | BGP session and route inspection (HBN only, on DPU) |
| `/proc/interrupts` | Interrupt distribution across CPUs |

---

## Pod Placement Strategy

All benchmarks require the client pod on Node 1 and the server pod on Node 2 to force traffic across the physical network through the BlueField DPUs.

### Node Labeling

```bash
kubectl label node <node1-name> bench-role=client
kubectl label node <node2-name> bench-role=server
```

### Example: iperf3 Server Pod (Node 2)

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: iperf3-server
spec:
  nodeSelector:
    bench-role: server
  containers:
  - name: iperf3
    image: networkstatic/iperf3
    command: ["iperf3", "-s"]
    ports:
    - containerPort: 5201
  terminationGracePeriodSeconds: 0
```

### Example: iperf3 Client Pod (Node 1)

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: iperf3-client
spec:
  nodeSelector:
    bench-role: client
  containers:
  - name: iperf3
    image: networkstatic/iperf3
    command: ["sleep", "infinity"]
  terminationGracePeriodSeconds: 0
```

Run benchmarks from the client pod:

```bash
kubectl exec -it iperf3-client -- iperf3 -c <iperf3-server-pod-ip> -t 60 -P 8
```

---

## Results Collection

### Directory Structure

```
results/
├── dpf-ovn-baseline/
│   ├── iperf3-tcp-1stream-run1.json
│   ├── iperf3-tcp-1stream-run2.json
│   ├── ...
│   ├── netperf-tcp-rr-run1.txt
│   ├── mpstat-run1.txt
│   └── system-info.txt
├── dpf-ovn-accelerated/
│   ├── ...
│   ├── ovs-offload-flows.txt
│   └── system-info.txt
├── dpf-ovn-hbn/
│   ├── ...
│   ├── ovs-offload-flows.txt
│   ├── bgp-state.txt
│   ├── ecmp-routes.txt
│   ├── ecmp-scaling/
│   │   ├── 1-flow.json
│   │   ├── 2-flows.json
│   │   └── ...
│   └── system-info.txt
└── summary/
    ├── results.csv
    └── charts/
```

### iperf3 JSON Output

Use `iperf3 --json` for machine-parseable results:

```bash
iperf3 -c <ip> -t 60 -P 8 --json > results/dpf-ovn-baseline/iperf3-tcp-8stream-run1.json
```

### System Info Capture (run once per cluster)

```bash
kubectl get nodes -o wide > system-info.txt
uname -a >> system-info.txt
cat /proc/cpuinfo | head -30 >> system-info.txt
lspci | grep -i mellanox >> system-info.txt
```
