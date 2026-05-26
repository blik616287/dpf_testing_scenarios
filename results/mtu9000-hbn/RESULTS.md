# Accelerated pod-to-pod over HBN @ MTU 9000 — RESULT

Date: 2026-05-25

## Topology
- iperf-client pod on host .90 (edge-...), DPU-offloaded via gpu1 DPU (OVN VF, VTEP 10.0.120.9)
- iperf-server pod on host .253 (gpu-sm02), DPU-offloaded via gpu2 DPU (OVN VF, VTEP 10.0.120.1)
- Cross-node traffic: pod VF -> DPU OVN (geneve encap) -> HBN (BGP/ECMP) -> p0/p1 uplinks -> leaf -> reverse on the other DPU
- Pod MTU 8940 (jumbo; OVN mtu=8940), HBN SF interfaces (p0_if/p1_if/pf2dpu2_if) MTU 9216, underlay p0/p1 9216

## Results (iperf3, 10s)
- Single-stream:        37.2 Gbit/s
- 8 parallel streams:   36.8 Gbit/s
- Reverse, 8 streams:   37.9 Gbit/s
(vs ~9.5 Gbit/s single-stream at MTU 1400 — jumbo gives ~4x)

## State at test time
- Both DPU nodes Ready in kamaji; both ovnkube-node pods 8/8 Running; doca-hbn ready on both DPUs
- Both hosts dpu-host; host ovnkube-node + cluster-manager healthy
