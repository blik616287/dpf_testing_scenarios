#!/usr/bin/env python3
"""Generate statistical charts for the DPF benchmark report.

Reads runs 2-5 (warmup discarded) from both clusters, plots:
  1. throughput.png       — TCP/UDP throughput bar charts with stdev error bars
  2. transactions.png     — TCP_RR / UDP_RR / TCP_CRR rates with error bars
  3. tail_latency.png     — sockperf p99.9 (log scale)
  4. host_cpu.png         — host CPU% during each test
  5. distribution.png     — per-run scatter for the four headline tests
  6. summary_table.png    — clean summary table image
"""

import json, os, statistics
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

RA = "/home/ubuntu/dpf_testing_scenarios/results/dpf-ovn-accelerated"
RB = "/home/ubuntu/dpf_testing_scenarios/results/dpf-ovn-baseline"
OUT = "/home/ubuntu/dpf_testing_scenarios/results/charts"
os.makedirs(OUT, exist_ok=True)

# ── parsers ──────────────────────────────────────────────────────────────────
def iperf_tcp(p):
    try:
        d = json.load(open(p))
        return d["end"]["sum_received"]["bits_per_second"] / 1e9  # Gbps
    except Exception:
        return None

def iperf_udp_send(p):
    try:
        d = json.load(open(p))
        return d["end"]["sum"].get("bits_per_second", 0) / 1e9
    except Exception:
        return None

def iperf_udp_loss(p):
    try:
        d = json.load(open(p))
        return d["end"]["sum"].get("lost_percent", 0)
    except Exception:
        return None

def netperf_value(p):
    try:
        for line in reversed(open(p).readlines()):
            line = line.strip()
            if not line: continue
            cols = line.split()
            if len(cols) >= 4 and cols[0].replace(".", "").isdigit():
                return float(cols[-1])
    except Exception:
        pass
    return None

def sockperf_p999(p):
    try:
        for line in open(p):
            if "percentile 99.990" in line:
                return float(line.split("=")[-1].strip())
    except Exception: pass
    return None

def host_cpu_busy(p):
    if not os.path.exists(p): return None
    busy = []
    for line in open(p):
        cols = line.split()
        if len(cols) >= 12 and cols[1] == "all":
            try:
                usr = float(cols[2]); sysc = float(cols[4])
                irq = float(cols[6]); soft = float(cols[7])
                busy.append(usr + sysc + irq + soft)
            except ValueError: pass
    return statistics.mean(busy) if busy else None

def collect(prefix, rdir, fn, runs=range(2, 6)):
    out = []
    for r in runs:
        v = fn(f"{rdir}/{prefix}-run{r}")
        if v is not None: out.append(v)
    return out

def stats(vals):
    if not vals: return (0, 0)
    if len(vals) < 2: return (vals[0], 0)
    return (statistics.mean(vals), statistics.stdev(vals))

# ── styling ──────────────────────────────────────────────────────────────────
plt.rcParams.update({
    "font.size": 11,
    "axes.titlesize": 13,
    "axes.labelsize": 11,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "figure.dpi": 110,
})
COLOR_A = "#5b6878"   # passthrough — neutral grey-blue
COLOR_B = "#2e8b57"   # VPC-OVN — accelerated green
EDGE = "#222"

def grouped_bar(ax, labels, a_means, a_errs, b_means, b_errs, ylabel, title, log=False, fmt=".1f"):
    x = np.arange(len(labels))
    w = 0.36
    bars_a = ax.bar(x - w/2, a_means, w, yerr=a_errs, capsize=4,
                    color=COLOR_A, edgecolor=EDGE, label="Passthrough (A)")
    bars_b = ax.bar(x + w/2, b_means, w, yerr=b_errs, capsize=4,
                    color=COLOR_B, edgecolor=EDGE, label="VPC-OVN accelerated (B)")
    if log: ax.set_yscale("log")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=20, ha="right")
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    ax.legend(frameon=False, loc="best")
    # value labels on top
    for bars, means in [(bars_a, a_means), (bars_b, b_means)]:
        for b, m in zip(bars, means):
            ax.text(b.get_x() + b.get_width()/2, b.get_height(),
                    f"{m:{fmt}}", ha="center", va="bottom", fontsize=9)

# ── 1. throughput ────────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(9, 5.4))
tests = [("iperf3-tcp-1stream", "TCP\n1 stream", iperf_tcp),
         ("iperf3-tcp-8stream", "TCP\n8 streams", iperf_tcp),
         ("iperf3-tcp-16stream", "TCP\n16 streams", iperf_tcp),
         ("iperf3-udp-max", "UDP max\n(sender)", iperf_udp_send),
         ("iperf3-udp-1400b", "UDP 1400B\n(sender)", iperf_udp_send)]
labels = [t[1] for t in tests]
am, ae, bm, be = [], [], [], []
for prefix, _, fn in tests:
    a = stats(collect(prefix, RB, fn))
    b = stats(collect(prefix, RA, fn))
    am.append(a[0]); ae.append(a[1]); bm.append(b[0]); be.append(b[1])
grouped_bar(ax, labels, am, ae, bm, be,
            "Throughput (Gbps)", "Pod-to-Pod Throughput — Passthrough vs VPC-OVN Accelerated", fmt=".1f")
fig.tight_layout()
fig.savefig(f"{OUT}/throughput.png")
plt.close(fig)

# ── 2. transactions / connection rate ────────────────────────────────────────
fig, ax = plt.subplots(figsize=(9, 5.4))
tests = [("netperf-tcp-rr", "TCP_RR\n(round-trips/s)", netperf_value),
         ("netperf-udp-rr", "UDP_RR\n(round-trips/s)", netperf_value),
         ("netperf-tcp-crr", "TCP_CRR\n(connections/s)", netperf_value)]
labels = [t[1] for t in tests]
am, ae, bm, be = [], [], [], []
for prefix, _, fn in tests:
    a = stats(collect(prefix, RB, fn))
    b = stats(collect(prefix, RA, fn))
    am.append(a[0]); ae.append(a[1]); bm.append(b[0]); be.append(b[1])
grouped_bar(ax, labels, am, ae, bm, be,
            "Rate (per second)", "Transaction & Connection Rates — Passthrough vs VPC-OVN", fmt=".0f")
fig.tight_layout()
fig.savefig(f"{OUT}/transactions.png")
plt.close(fig)

# ── 3. tail latency ──────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(7, 5.4))
a = stats(collect("sockperf-pingpong", RB, sockperf_p999))
b = stats(collect("sockperf-pingpong", RA, sockperf_p999))
xs = np.arange(2)
bars = ax.bar(xs, [a[0], b[0]], 0.5,
              yerr=[a[1], b[1]], capsize=6,
              color=[COLOR_A, COLOR_B], edgecolor=EDGE)
ax.set_yscale("log")
ax.set_xticks(xs)
ax.set_xticklabels(["Passthrough\n(A)", "VPC-OVN\nAccelerated (B)"])
ax.set_ylabel("p99.9 round-trip latency (µs, log scale)")
ax.set_title("Tail Latency (sockperf ping-pong, p99.9)")
ax.grid(axis="y", linestyle="--", alpha=0.4, which="both")
for b_, m in zip(bars, [a[0], b[0]]):
    ax.text(b_.get_x() + b_.get_width()/2, b_.get_height()*1.05,
            f"{m:.0f} µs", ha="center", va="bottom", fontsize=11)
fig.tight_layout()
fig.savefig(f"{OUT}/tail_latency.png")
plt.close(fig)

# ── 4. host CPU ──────────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(9, 5.4))
tests = [("iperf3-tcp-1stream", "TCP 1 stream"),
         ("iperf3-tcp-8stream", "TCP 8 streams\n(line rate)"),
         ("iperf3-tcp-16stream", "TCP 16 streams\n(line rate)"),
         ("iperf3-udp-max", "UDP max"),
         ("netperf-tcp-rr", "TCP_RR"),
         ("netperf-tcp-crr", "TCP_CRR")]
labels = [t[1] for t in tests]
am, ae, bm, be = [], [], [], []
for prefix, _ in tests:
    bvals = [host_cpu_busy(f"{RB}/{prefix}-run{r}.mpstat.txt") for r in range(2, 6)]
    avals = [host_cpu_busy(f"{RA}/{prefix}-run{r}.host-gpu1.mpstat") for r in range(2, 6)]
    bvals = [v for v in bvals if v is not None]
    avals = [v for v in avals if v is not None]
    a = stats(bvals); b = stats(avals)
    am.append(a[0]); ae.append(a[1]); bm.append(b[0]); be.append(b[1])
grouped_bar(ax, labels, am, ae, bm, be,
            "Host CPU busy % (usr+sys+irq+soft, mean over 60s)",
            "Host CPU at Same Workload — DPU Acceleration Frees Host Cores", fmt=".1f")
fig.tight_layout()
fig.savefig(f"{OUT}/host_cpu.png")
plt.close(fig)

# ── 5. per-run distribution scatter ──────────────────────────────────────────
fig, axes = plt.subplots(2, 2, figsize=(11, 8))
panels = [
    ("iperf3-tcp-1stream", iperf_tcp,         "TCP 1-stream throughput (Gbps)"),
    ("netperf-tcp-rr",     netperf_value,     "TCP_RR (round-trips/s)"),
    ("netperf-tcp-crr",    netperf_value,     "TCP_CRR (connections/s)"),
    ("sockperf-pingpong",  sockperf_p999,     "sockperf p99.9 (µs, log scale)"),
]
for ax, (prefix, fn, title) in zip(axes.flat, panels):
    bvals = collect(prefix, RB, fn)
    avals = collect(prefix, RA, fn)
    ax.scatter([0]*len(bvals), bvals, color=COLOR_A, s=80, edgecolor=EDGE, label="Passthrough")
    ax.scatter([1]*len(avals), avals, color=COLOR_B, s=80, edgecolor=EDGE, label="VPC-OVN")
    if bvals: ax.hlines(statistics.mean(bvals), -0.2, 0.2, colors=COLOR_A, lw=2)
    if avals: ax.hlines(statistics.mean(avals), 0.8, 1.2, colors=COLOR_B, lw=2)
    ax.set_xticks([0, 1])
    ax.set_xticklabels(["Passthrough", "VPC-OVN"])
    ax.set_title(title)
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    if "p99.9" in title: ax.set_yscale("log")
fig.suptitle("Per-Run Distributions (n=4, runs 2–5)", y=1.00, fontsize=14)
fig.tight_layout()
fig.savefig(f"{OUT}/distribution.png")
plt.close(fig)

# ── 6. UDP loss panel (sender Gbps + loss% paired) ────────────────────────────
fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
tests = [("iperf3-udp-max", "UDP max"),
         ("iperf3-udp-64b", "UDP 64B pkt"),
         ("iperf3-udp-1400b", "UDP 1400B pkt")]
labels = [t[1] for t in tests]

# left: sender throughput
am, ae, bm, be = [], [], [], []
for prefix, _ in tests:
    a = stats(collect(prefix, RB, iperf_udp_send))
    b = stats(collect(prefix, RA, iperf_udp_send))
    am.append(a[0]); ae.append(a[1]); bm.append(b[0]); be.append(b[1])
grouped_bar(axes[0], labels, am, ae, bm, be,
            "Sender Gbps", "UDP Sender Throughput (TX-side offload)", fmt=".1f")

# right: receiver loss%
am, ae, bm, be = [], [], [], []
for prefix, _ in tests:
    a = stats(collect(prefix, RB, iperf_udp_loss))
    b = stats(collect(prefix, RA, iperf_udp_loss))
    am.append(a[0]); ae.append(a[1]); bm.append(b[0]); be.append(b[1])
grouped_bar(axes[1], labels, am, ae, bm, be,
            "Receiver loss %", "UDP Receiver Loss (iperf3 RX bottleneck, both arms)", fmt=".0f")
fig.tight_layout()
fig.savefig(f"{OUT}/udp_split.png")
plt.close(fig)

print(f"charts written to {OUT}:")
for f in sorted(os.listdir(OUT)):
    print(f"  {f}")
