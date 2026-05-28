#!/usr/bin/env python3
"""Generate statistical charts comparing the test datasets.

Reads runs 2-5 (warmup discarded) from:
  - results/dpf-ovn-baseline/             (Cilium, Test Set 1 baseline)
  - results/dpf-ovn-accelerated-no-offload/ (VPC-OVN sw, Test Set 2 baseline)
  - results/dpf-ovn-accelerated/          (VPC-OVN HW, Test Set 1 cluster B = Test Set 2 accel)

A 4th "DPF + HBN (MTU 9000)" bar is overlaid on the comparable charts from the
Test Cases 3 & 4 v2 matrix (results/mtu9000-hbn/matrix_v2/, n=4 runs 2-5, 60 s,
host-cluster pods — same sample strength as Test Sets 1-2). See the footnote on
each HBN chart for the residual methodology delta (pod placement). Charts with
no comparable HBN metric (sockperf p99.9 tail latency, per-run distribution)
stay 3-way.

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

# ── HBN (Test Cases 3 & 4) summary values — measured 2026-05-26 matrix_v2, MTU 9000 ──
# Source: results/mtu9000-hbn/matrix_v2/SUMMARY.md. n=4 (runs 2-5), 60s runs,
# host-cluster pods. Methodology now matches Test Sets 1-2 (n=4, 60s, 30s idle).
# Values are (mean, stdev). np.nan = no comparable HBN measurement for that test.
NA = np.nan
HBN = {
    # throughput (Gbps)
    "iperf3-tcp-1stream":   (36.63, 0.40), "iperf3-tcp-8stream":  (36.96, 0.44),
    "iperf3-tcp-16stream":  (36.80, 0.65), "iperf3-udp-max":      (16.21, 0.38),
    "iperf3-udp-1400b":     (4.40,  0.04), "iperf3-udp-64b":      (0.227, 0.003),
    # transactions / conn rate (per second)
    "netperf-tcp-rr":    (13858.0, 390.0), "netperf-udp-rr":  (15079.0, 485.0),
    "netperf-tcp-crr":   (2398.0,    8.0),
    # host CPU busy % (gpu1 client mpstat sliced to per-test window, n=4)
    "cpu-iperf3-tcp-1stream":  (5.05, 0), "cpu-iperf3-tcp-8stream":  (5.94, 0),
    "cpu-iperf3-tcp-16stream": (6.35, 0), "cpu-iperf3-udp-max":      (4.96, 0),
    "cpu-netperf-tcp-rr":      (3.77, 0), "cpu-netperf-tcp-crr":     (3.76, 0),
    # UDP receiver loss %
    "loss-iperf3-udp-max": (41.66, 6.67), "loss-iperf3-udp-64b": (12.43, 2.66),
    "loss-iperf3-udp-1400b": (8.12, 1.65),
    # sockperf UDP ping-pong TRUE p99.9 (sockperf 99.900 line), n=4 runs 2-5
    "sockperf-p999": (132.85, 1.97),
}
def hbn_m(k):  # mean
    v = HBN.get(k); return v[0] if isinstance(v, tuple) else NA
def hbn_e(k):  # stdev
    v = HBN.get(k); return v[1] if isinstance(v, tuple) else 0
HBN_NOTE = ("* DPF + HBN: MTU 9000, n=4 (runs 2-5), 60 s — same sample strength as Test Sets 1-2. "
            "Pods are host-cluster (so %usr includes the iperf3 app); dataplane indicator is %sys+%soft.")

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
def sockperf_p999(p):  # TRUE p99.9 (sockperf "percentile 99.900" line)
    try:
        for line in open(p):
            if "percentile 99.900" in line:
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
COL_C   = "#5b6878"  # Cilium baseline — grey-blue
COL_S   = "#d4a017"  # VPC-OVN software (hw-off) — amber
COL_H   = "#2e8b57"  # VPC-OVN hardware-offloaded — green
COL_HBN = "#1f6feb"  # DPF + HBN — blue
EDGE    = "#222"

def grouped3(ax, labels, c_means, c_errs, s_means, s_errs, h_means, h_errs,
             ylabel, title, log=False, fmt=".1f", suffix="",
             hbn_means=None, hbn_errs=None):
    x = np.arange(len(labels))
    if hbn_means is None:
        w = 0.27
        series = [(-w, c_means, c_errs, COL_C, "Cilium (host kernel)"),
                  (0,  s_means, s_errs, COL_S, "VPC-OVN sw (hw-offload=false)"),
                  (w,  h_means, h_errs, COL_H, "VPC-OVN HW (hw-offload=true)")]
    else:
        w = 0.20
        if hbn_errs is None: hbn_errs = [0]*len(labels)
        series = [(-1.5*w, c_means, c_errs, COL_C, "Cilium (host kernel)"),
                  (-0.5*w, s_means, s_errs, COL_S, "VPC-OVN sw (hw-offload=false)"),
                  (0.5*w,  h_means, h_errs, COL_H, "VPC-OVN HW (hw-offload=true)"),
                  (1.5*w,  hbn_means, hbn_errs, COL_HBN, "DPF + HBN (MTU 9000)*")]
    if log: ax.set_yscale("log")
    ax.set_ylabel(ylabel); ax.set_title(title)
    ax.set_xticks(x); ax.set_xticklabels(labels, rotation=20, ha="right")
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    drawn = []
    for off, means, errs, col, lab in series:
        m = np.array([np.nan if v is None else v for v in means], dtype=float)
        e = np.array([0 if v is None else v for v in errs], dtype=float)
        bars = ax.bar(x + off, m, w, yerr=e, capsize=3, color=col, edgecolor=EDGE, label=lab)
        drawn.append((bars, m))
    ax.legend(frameon=False, loc="best", fontsize=8)
    for bars, means in drawn:
        for b, mval in zip(bars, means):
            if np.isnan(mval): continue
            ax.text(b.get_x()+b.get_width()/2, b.get_height(),
                    f"{mval:{fmt}}{suffix}", ha="center", va="bottom", fontsize=7.5)

def footnote(fig, text):
    fig.text(0.01, 0.005, text, fontsize=7.5, style="italic", color="#444", wrap=True)

# ── 1. throughput ────────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(11, 5.8))
tests = [("iperf3-tcp-1stream","TCP\n1 stream",iperf3_tcp),
         ("iperf3-tcp-8stream","TCP\n8 streams",iperf3_tcp),
         ("iperf3-tcp-16stream","TCP\n16 streams",iperf3_tcp),
         ("iperf3-udp-max","UDP max\n(sender)",iperf3_udp_send),
         ("iperf3-udp-1400b","UDP 1400B\n(sender)",iperf3_udp_send)]
labels=[t[1] for t in tests]
cm=[]; ce=[]; sm=[]; se=[]; hm=[]; he=[]; bm=[]; be=[]
for prefix,_,fn in tests:
    a=stats(collect(prefix,CIL,fn)); b=stats(collect(prefix,OFF,fn)); c=stats(collect(prefix,ON,fn))
    cm.append(a[0]); ce.append(a[1]); sm.append(b[0]); se.append(b[1]); hm.append(c[0]); he.append(c[1])
    bm.append(hbn_m(prefix)); be.append(hbn_e(prefix))
grouped3(ax, labels, cm, ce, sm, se, hm, he,
         "Throughput (Gbps)", "Pod-to-Pod Throughput — with DPF+HBN",
         fmt=".1f", hbn_means=bm, hbn_errs=be)
footnote(fig, HBN_NOTE)
fig.tight_layout(rect=[0,0.03,1,1])
fig.savefig(f"{OUT}/throughput.png")
plt.close(fig)

# ── 2. transactions ─────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(10, 5.8))
tests = [("netperf-tcp-rr","TCP_RR\n(trans/s)",netperf),
         ("netperf-udp-rr","UDP_RR\n(trans/s)",netperf),
         ("netperf-tcp-crr","TCP_CRR\n(conn/s)",netperf)]
labels=[t[1] for t in tests]
cm=[]; ce=[]; sm=[]; se=[]; hm=[]; he=[]; bm=[]; be=[]
for prefix,_,fn in tests:
    a=stats(collect(prefix,CIL,fn)); b=stats(collect(prefix,OFF,fn)); c=stats(collect(prefix,ON,fn))
    cm.append(a[0]); ce.append(a[1]); sm.append(b[0]); se.append(b[1]); hm.append(c[0]); he.append(c[1])
    bm.append(hbn_m(prefix)); be.append(hbn_e(prefix))
grouped3(ax, labels, cm, ce, sm, se, hm, he,
         "Rate (per second)", "Transaction & Connection Rates — with DPF+HBN",
         fmt=".0f", hbn_means=bm, hbn_errs=be)
footnote(fig, HBN_NOTE)
fig.tight_layout(rect=[0,0.03,1,1])
fig.savefig(f"{OUT}/transactions.png")
plt.close(fig)

# ── 3. tail latency (4-way: sockperf UDP ping-pong p99.9, incl. HBN) ──────────
fig, ax = plt.subplots(figsize=(9, 5.8))
a=stats(collect("sockperf-pingpong",CIL,sockperf_p999))
b=stats(collect("sockperf-pingpong",OFF,sockperf_p999))
c=stats(collect("sockperf-pingpong",ON,sockperf_p999))
h=(hbn_m("sockperf-p999"), hbn_e("sockperf-p999"))
xs=np.arange(4)
means=[a[0],b[0],c[0],h[0]]
errs=[a[1],b[1],c[1],h[1]]
bars=ax.bar(xs,means,0.55,yerr=errs,capsize=6,
            color=[COL_C,COL_S,COL_H,COL_HBN],edgecolor=EDGE)
ax.set_yscale("log")
ax.set_xticks(xs)
ax.set_xticklabels(["Cilium\n(host kernel)","VPC-OVN sw\n(hw-offload=false)","VPC-OVN HW\n(hw-offload=true)","DPF + HBN\n(MTU 9000)*"])
ax.set_ylabel("p99.9 round-trip latency (µs, log scale)")
ax.set_title("Tail Latency (sockperf p99.9 — true 99.900 percentile, n=4)")
ax.grid(axis="y",linestyle="--",alpha=0.4,which="both")
for b_,m in zip(bars,means):
    if m is None or m == 0: continue
    ax.text(b_.get_x()+b_.get_width()/2,b_.get_height()*1.05,f"{m:.0f} µs",
            ha="center",va="bottom",fontsize=11)
footnote(fig, HBN_NOTE)
fig.tight_layout(rect=[0,0.04,1,1])
fig.savefig(f"{OUT}/tail_latency.png")
plt.close(fig)

# ── 4. host CPU ──────────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(11, 5.8))
tests = [("iperf3-tcp-1stream","TCP 1 stream"),
         ("iperf3-tcp-8stream","TCP 8\n(line rate)"),
         ("iperf3-tcp-16stream","TCP 16\n(line rate)"),
         ("iperf3-udp-max","UDP max"),
         ("netperf-tcp-rr","TCP_RR"),
         ("netperf-tcp-crr","TCP_CRR")]
labels=[t[1] for t in tests]
cm=[]; ce=[]; sm=[]; se=[]; hm=[]; he=[]; bm=[]; be=[]
for prefix,_ in tests:
    cvals=[host_cpu_busy(f"{CIL}/{prefix}-run{r}.mpstat.txt") for r in range(2,6)]
    svals=[host_cpu_busy(f"{OFF}/{prefix}-run{r}.host-gpu1.mpstat") for r in range(2,6)]
    hvals=[host_cpu_busy(f"{ON}/{prefix}-run{r}.host-gpu1.mpstat") for r in range(2,6)]
    a=stats(cvals); b=stats(svals); c=stats(hvals)
    cm.append(a[0]); ce.append(a[1]); sm.append(b[0]); se.append(b[1]); hm.append(c[0]); he.append(c[1])
    bm.append(hbn_m(f"cpu-{prefix}")); be.append(hbn_e(f"cpu-{prefix}"))
grouped3(ax, labels, cm, ce, sm, se, hm, he,
         "Host CPU busy % (usr+sys+irq+soft)",
         "Host CPU — DPU offload frees host cores (incl. DPF+HBN)",
         fmt=".1f", suffix="%", hbn_means=bm, hbn_errs=be)
footnote(fig, HBN_NOTE + "  Dataplane indicator at line rate: HBN %sys+%soft ≈ 4 % (≈ accel arm, well below passthrough).")
fig.tight_layout(rect=[0,0.04,1,1])
fig.savefig(f"{OUT}/host_cpu.png")
plt.close(fig)

# ── 5. per-run distribution scatter (3-way — variance check on A/B/C runs) ────
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
fig, axes = plt.subplots(1, 2, figsize=(14, 5.4))
tests=[("iperf3-udp-max","UDP max"),
       ("iperf3-udp-64b","UDP 64B"),
       ("iperf3-udp-1400b","UDP 1400B")]
labels=[t[1] for t in tests]
# left — sender
cm=[]; ce=[]; sm=[]; se=[]; hm=[]; he=[]; bm=[]; be=[]
for prefix,_ in tests:
    a=stats(collect(prefix,CIL,iperf3_udp_send))
    b=stats(collect(prefix,OFF,iperf3_udp_send))
    c=stats(collect(prefix,ON,iperf3_udp_send))
    cm.append(a[0]); ce.append(a[1]); sm.append(b[0]); se.append(b[1]); hm.append(c[0]); he.append(c[1])
    bm.append(hbn_m(prefix)); be.append(hbn_e(prefix))
grouped3(axes[0],labels,cm,ce,sm,se,hm,he,"Sender Gbps","UDP Sender Throughput — with DPF+HBN",fmt=".1f",hbn_means=bm,hbn_errs=be)
# right — loss
cm=[]; ce=[]; sm=[]; se=[]; hm=[]; he=[]; bm=[]; be=[]
for prefix,_ in tests:
    a=stats(collect(prefix,CIL,iperf3_udp_loss))
    b=stats(collect(prefix,OFF,iperf3_udp_loss))
    c=stats(collect(prefix,ON,iperf3_udp_loss))
    cm.append(a[0]); ce.append(a[1]); sm.append(b[0]); se.append(b[1]); hm.append(c[0]); he.append(c[1])
    bm.append(hbn_m(f"loss-{prefix}")); be.append(hbn_e(f"loss-{prefix}"))
grouped3(axes[1],labels,cm,ce,sm,se,hm,he,"Receiver loss %","UDP Receiver Loss — with DPF+HBN",fmt=".0f",suffix="%",hbn_means=bm,hbn_errs=be)
footnote(fig, HBN_NOTE)
fig.tight_layout(rect=[0,0.04,1,1])
fig.savefig(f"{OUT}/udp_split.png")
plt.close(fig)

print(f"charts written to {OUT}:")
for f in sorted(os.listdir(OUT)):
    print(f"  {f}")
