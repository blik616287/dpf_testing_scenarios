#!/usr/bin/env python3
"""Generate statistical charts comparing all three test datasets.

Reads runs 2-5 (warmup discarded) from:
  - results/dpf-ovn-baseline/             (Cilium, Test Set 1 baseline)
  - results/dpf-ovn-accelerated-no-offload/ (VPC-OVN sw, Test Set 2 baseline)
  - results/dpf-ovn-accelerated/          (VPC-OVN HW, Test Set 1 cluster B = Test Set 2 accel)

Charts go to results/charts/.
"""

import json, os, statistics
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

CIL = "/home/ubuntu/dpf_testing_scenarios/results/dpf-ovn-baseline"
OFF = "/home/ubuntu/dpf_testing_scenarios/results/dpf-ovn-accelerated-no-offload"
ON  = "/home/ubuntu/dpf_testing_scenarios/results/dpf-ovn-accelerated"
OUT = "/home/ubuntu/dpf_testing_scenarios/results/charts"
os.makedirs(OUT, exist_ok=True)

# ── parsers ──────────────────────────────────────────────────────────────────
def iperf3_tcp(p):
    try: return json.load(open(p))["end"]["sum_received"]["bits_per_second"]/1e9
    except: return None
def iperf3_udp_send(p):
    try: return json.load(open(p))["end"]["sum"].get("bits_per_second", 0)/1e9
    except: return None
def iperf3_udp_loss(p):
    try: return json.load(open(p))["end"]["sum"].get("lost_percent", 0)
    except: return None
def netperf(p):
    try:
        for line in reversed(open(p).readlines()):
            line = line.strip()
            if not line: continue
            cols = line.split()
            if len(cols) >= 4 and cols[0].replace(".","").isdigit():
                return float(cols[-1])
    except: pass
    return None
def sockperf_p999(p):
    try:
        for line in open(p):
            if "percentile 99.990" in line:
                return float(line.split("=")[-1].strip())
    except: pass
    return None
def host_cpu_busy(p):
    if not os.path.exists(p): return None
    busy=[]
    for line in open(p):
        c=line.split()
        if len(c)>=12 and c[1]=="all":
            try:
                usr=float(c[2]); sysc=float(c[4]); irq=float(c[6]); soft=float(c[7])
                busy.append(usr+sysc+irq+soft)
            except: pass
    return statistics.mean(busy) if busy else None

def collect(prefix, rdir, fn, runs=range(2, 6)):
    return [fn(f"{rdir}/{prefix}-run{r}") for r in runs if os.path.exists(f"{rdir}/{prefix}-run{r}")]
def stats(vals):
    vals = [v for v in vals if v is not None]
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
COL_C = "#5b6878"  # Cilium baseline — grey-blue
COL_S = "#d4a017"  # VPC-OVN software (hw-off) — amber
COL_H = "#2e8b57"  # VPC-OVN hardware-offloaded — green
EDGE  = "#222"

def grouped3(ax, labels, c_means, c_errs, s_means, s_errs, h_means, h_errs,
             ylabel, title, log=False, fmt=".1f", suffix=""):
    x = np.arange(len(labels)); w = 0.27
    b1 = ax.bar(x - w, c_means, w, yerr=c_errs, capsize=3, color=COL_C, edgecolor=EDGE, label="Cilium (host kernel)")
    b2 = ax.bar(x,     s_means, w, yerr=s_errs, capsize=3, color=COL_S, edgecolor=EDGE, label="VPC-OVN sw (hw-offload=false)")
    b3 = ax.bar(x + w, h_means, w, yerr=h_errs, capsize=3, color=COL_H, edgecolor=EDGE, label="VPC-OVN HW (hw-offload=true)")
    if log: ax.set_yscale("log")
    ax.set_ylabel(ylabel); ax.set_title(title)
    ax.set_xticks(x); ax.set_xticklabels(labels, rotation=20, ha="right")
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    ax.legend(frameon=False, loc="best", fontsize=9)
    for bars, means in [(b1,c_means),(b2,s_means),(b3,h_means)]:
        for b, m in zip(bars, means):
            ax.text(b.get_x()+b.get_width()/2, b.get_height(),
                    f"{m:{fmt}}{suffix}", ha="center", va="bottom", fontsize=8)

# ── 1. throughput ────────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(10, 5.6))
tests = [("iperf3-tcp-1stream","TCP\n1 stream",iperf3_tcp),
         ("iperf3-tcp-8stream","TCP\n8 streams",iperf3_tcp),
         ("iperf3-tcp-16stream","TCP\n16 streams",iperf3_tcp),
         ("iperf3-udp-max","UDP max\n(sender)",iperf3_udp_send),
         ("iperf3-udp-1400b","UDP 1400B\n(sender)",iperf3_udp_send)]
labels=[t[1] for t in tests]
cm=[]; ce=[]; sm=[]; se=[]; hm=[]; he=[]
for prefix,_,fn in tests:
    a=stats(collect(prefix,CIL,fn)); b=stats(collect(prefix,OFF,fn)); c=stats(collect(prefix,ON,fn))
    cm.append(a[0]); ce.append(a[1]); sm.append(b[0]); se.append(b[1]); hm.append(c[0]); he.append(c[1])
grouped3(ax, labels, cm, ce, sm, se, hm, he,
         "Throughput (Gbps)", "Pod-to-Pod Throughput — 3-way comparison",
         fmt=".1f")
fig.tight_layout()
fig.savefig(f"{OUT}/throughput.png")
plt.close(fig)

# ── 2. transactions ─────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(10, 5.6))
tests = [("netperf-tcp-rr","TCP_RR\n(trans/s)",netperf),
         ("netperf-udp-rr","UDP_RR\n(trans/s)",netperf),
         ("netperf-tcp-crr","TCP_CRR\n(conn/s)",netperf)]
labels=[t[1] for t in tests]
cm=[]; ce=[]; sm=[]; se=[]; hm=[]; he=[]
for prefix,_,fn in tests:
    a=stats(collect(prefix,CIL,fn)); b=stats(collect(prefix,OFF,fn)); c=stats(collect(prefix,ON,fn))
    cm.append(a[0]); ce.append(a[1]); sm.append(b[0]); se.append(b[1]); hm.append(c[0]); he.append(c[1])
grouped3(ax, labels, cm, ce, sm, se, hm, he,
         "Rate (per second)", "Transaction & Connection Rates — 3-way",
         fmt=".0f")
fig.tight_layout()
fig.savefig(f"{OUT}/transactions.png")
plt.close(fig)

# ── 3. tail latency ──────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(8, 5.6))
a=stats(collect("sockperf-pingpong",CIL,sockperf_p999))
b=stats(collect("sockperf-pingpong",OFF,sockperf_p999))
c=stats(collect("sockperf-pingpong",ON,sockperf_p999))
xs=np.arange(3)
bars=ax.bar(xs,[a[0],b[0],c[0]],0.55,yerr=[a[1],b[1],c[1]],capsize=6,
            color=[COL_C,COL_S,COL_H],edgecolor=EDGE)
ax.set_yscale("log")
ax.set_xticks(xs)
ax.set_xticklabels(["Cilium\n(host kernel)","VPC-OVN sw\n(hw-offload=false)","VPC-OVN HW\n(hw-offload=true)"])
ax.set_ylabel("p99.9 round-trip latency (µs, log scale)")
ax.set_title("Tail Latency (sockperf ping-pong p99.9)")
ax.grid(axis="y",linestyle="--",alpha=0.4,which="both")
for b_,m in zip(bars,[a[0],b[0],c[0]]):
    ax.text(b_.get_x()+b_.get_width()/2,b_.get_height()*1.05,f"{m:.0f} µs",
            ha="center",va="bottom",fontsize=11)
fig.tight_layout()
fig.savefig(f"{OUT}/tail_latency.png")
plt.close(fig)

# ── 4. host CPU ──────────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(10, 5.6))
tests = [("iperf3-tcp-1stream","TCP 1 stream"),
         ("iperf3-tcp-8stream","TCP 8\n(line rate)"),
         ("iperf3-tcp-16stream","TCP 16\n(line rate)"),
         ("iperf3-udp-max","UDP max"),
         ("netperf-tcp-rr","TCP_RR"),
         ("netperf-tcp-crr","TCP_CRR")]
labels=[t[1] for t in tests]
cm=[]; ce=[]; sm=[]; se=[]; hm=[]; he=[]
for prefix,_ in tests:
    cvals=[host_cpu_busy(f"{CIL}/{prefix}-run{r}.mpstat.txt") for r in range(2,6)]
    svals=[host_cpu_busy(f"{OFF}/{prefix}-run{r}.host-gpu1.mpstat") for r in range(2,6)]
    hvals=[host_cpu_busy(f"{ON}/{prefix}-run{r}.host-gpu1.mpstat") for r in range(2,6)]
    a=stats(cvals); b=stats(svals); c=stats(hvals)
    cm.append(a[0]); ce.append(a[1]); sm.append(b[0]); se.append(b[1]); hm.append(c[0]); he.append(c[1])
grouped3(ax, labels, cm, ce, sm, se, hm, he,
         "Host CPU busy % (usr+sys+irq+soft, mean over 60s)",
         "Host CPU — DPU offload frees host cores at the same workload",
         fmt=".1f", suffix="%")
fig.tight_layout()
fig.savefig(f"{OUT}/host_cpu.png")
plt.close(fig)

# ── 5. per-run distribution scatter ─────────────────────────────────────────
fig, axes = plt.subplots(2, 2, figsize=(11, 8))
panels = [
    ("iperf3-tcp-1stream", iperf3_tcp,     "TCP 1-stream throughput (Gbps)"),
    ("netperf-tcp-rr",     netperf,        "TCP_RR (round-trips/s)"),
    ("netperf-tcp-crr",    netperf,        "TCP_CRR (connections/s)"),
    ("sockperf-pingpong",  sockperf_p999,  "sockperf p99.9 (µs, log scale)"),
]
for ax,(prefix,fn,title) in zip(axes.flat,panels):
    cv=collect(prefix,CIL,fn); sv=collect(prefix,OFF,fn); hv=collect(prefix,ON,fn)
    for col,vals,xpos in [(COL_C,cv,0),(COL_S,sv,1),(COL_H,hv,2)]:
        ax.scatter([xpos]*len(vals),vals,color=col,s=80,edgecolor=EDGE)
        if vals: ax.hlines(statistics.mean(vals),xpos-0.2,xpos+0.2,colors=col,lw=2)
    ax.set_xticks([0,1,2])
    ax.set_xticklabels(["Cilium","VPC-OVN sw","VPC-OVN HW"])
    ax.set_title(title)
    ax.grid(axis="y",linestyle="--",alpha=0.4)
    if "p99.9" in title: ax.set_yscale("log")
fig.suptitle("Per-Run Distributions (n=4, runs 2–5)", y=1.00, fontsize=14)
fig.tight_layout()
fig.savefig(f"{OUT}/distribution.png")
plt.close(fig)

# ── 6. UDP split (sender Gbps + loss %) ─────────────────────────────────────
fig, axes = plt.subplots(1, 2, figsize=(13, 5.0))
tests=[("iperf3-udp-max","UDP max"),
       ("iperf3-udp-64b","UDP 64B"),
       ("iperf3-udp-1400b","UDP 1400B")]
labels=[t[1] for t in tests]
# left — sender
cm=[]; ce=[]; sm=[]; se=[]; hm=[]; he=[]
for prefix,_ in tests:
    a=stats(collect(prefix,CIL,iperf3_udp_send))
    b=stats(collect(prefix,OFF,iperf3_udp_send))
    c=stats(collect(prefix,ON,iperf3_udp_send))
    cm.append(a[0]); ce.append(a[1]); sm.append(b[0]); se.append(b[1]); hm.append(c[0]); he.append(c[1])
grouped3(axes[0],labels,cm,ce,sm,se,hm,he,"Sender Gbps","UDP Sender Throughput",fmt=".1f")
# right — loss
cm=[]; ce=[]; sm=[]; se=[]; hm=[]; he=[]
for prefix,_ in tests:
    a=stats(collect(prefix,CIL,iperf3_udp_loss))
    b=stats(collect(prefix,OFF,iperf3_udp_loss))
    c=stats(collect(prefix,ON,iperf3_udp_loss))
    cm.append(a[0]); ce.append(a[1]); sm.append(b[0]); se.append(b[1]); hm.append(c[0]); he.append(c[1])
grouped3(axes[1],labels,cm,ce,sm,se,hm,he,"Receiver loss %","UDP Receiver Loss",fmt=".0f",suffix="%")
fig.tight_layout()
fig.savefig(f"{OUT}/udp_split.png")
plt.close(fig)

print(f"charts written to {OUT}:")
for f in sorted(os.listdir(OUT)):
    print(f"  {f}")
