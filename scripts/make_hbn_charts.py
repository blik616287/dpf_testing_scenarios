#!/usr/bin/env python3
"""Standalone HBN-specific charts (Test Cases 3 & 4, MTU 9000) for report §7.

Generates into results/charts/:
  - hbn_aggregation.png   single-pair flow scaling (flat) vs concurrent pod-pairs (rising)
  - hbn_uplink_balance.png per-uplink ECMP distribution at the 8-pair peak (both DPUs)
  - hbn_failover.png       per-second throughput across a real BGP-layer uplink failover

Data: results/mtu9000-hbn/ (t3_t4_results.csv, agg-bandwidth-test.txt, failover-persec.txt).
"""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

OUT = "/home/ubuntu/dpf_testing_scenarios/results/charts"
MT  = "/home/ubuntu/dpf_testing_scenarios/results/mtu9000-hbn"
os.makedirs(OUT, exist_ok=True)
plt.rcParams.update({"font.size": 11, "axes.titlesize": 13, "axes.labelsize": 11,
                     "axes.spines.top": False, "axes.spines.right": False, "figure.dpi": 110})
COL_HBN = "#1f6feb"; COL_P0 = "#1f6feb"; COL_P1 = "#e8710a"; COL_FLAT = "#5b6878"; EDGE = "#222"

# ── 1. aggregation: flows-in-one-pair (flat) vs concurrent pairs (rising) ──────
flows   = [1, 2, 4, 8, 16, 32];  flow_g = [34.2, 35.5, 36.1, 36.9, 37.1, 36.3]
pairs   = [1, 2, 4, 6, 8];       pair_g = [36.3, 70.1, 76.3, 69.7, 78.0]
fig, ax = plt.subplots(figsize=(10, 5.8))
ax.plot(flows, flow_g, "o-", color=COL_FLAT, lw=2, ms=7, label="Single pod-pair — N parallel flows (one VF pair)")
ax.plot(pairs, pair_g, "s-", color=COL_HBN, lw=2.4, ms=8, label="N concurrent pod-pairs (separate VFs)")
ax.axhline(37, ls="--", color=COL_FLAT, alpha=0.6); ax.text(33, 37.6, "per-VF/endpoint ceiling ~37", color=COL_FLAT, fontsize=9, ha="right")
ax.axhline(77, ls="--", color=COL_HBN, alpha=0.6);  ax.text(33, 78.2, "2×40G fabric ceiling ~77", color=COL_HBN, fontsize=9, ha="right")
for x, y in zip(pairs, pair_g): ax.annotate(f"{y:.0f}", (x, y), textcoords="offset points", xytext=(0, 8), ha="center", fontsize=9, color=COL_HBN)
ax.set_xscale("log", base=2); ax.set_xticks(sorted(set(flows + pairs)))
ax.get_xaxis().set_major_formatter(matplotlib.ticker.ScalarFormatter())
ax.set_xlabel("parallel units (log₂): flows within one pair, or concurrent pod-pairs")
ax.set_ylabel("Aggregate throughput (Gbps)")
ax.set_title("HBN bandwidth aggregation — flows don't scale a pair, but pairs do (MTU 9000)")
ax.set_ylim(0, 90); ax.grid(axis="y", ls="--", alpha=0.4); ax.legend(frameon=False, loc="center right", fontsize=9)
fig.text(0.01, 0.005, "Single pod-pair shares one src/dst VF → caps at ~37 Gbps regardless of flow count. "
         "Multiple concurrent pairs spread across all 4 uplinks → ~77 Gbps ≈ 2×40G (each uplink ~96% saturated).", fontsize=7.5, style="italic", color="#444")
fig.tight_layout(rect=[0, 0.03, 1, 1]); fig.savefig(f"{OUT}/hbn_aggregation.png"); plt.close(fig)

# ── 2. per-uplink balance at 8-pair peak ──────────────────────────────────────
# 8-pair peak byte delta (active direction): gpu1 rx p0/p1, gpu2 tx p0/p1 (GB)
g1 = [98.9, 94.5]; g2 = [97.6, 95.8]
fig, ax = plt.subplots(figsize=(9, 5.6))
x = np.arange(2); w = 0.36
b0 = ax.bar(x - w/2, [g1[0], g2[0]], w, color=COL_P0, edgecolor=EDGE, label="p0 uplink")
b1 = ax.bar(x + w/2, [g1[1], g2[1]], w, color=COL_P1, edgecolor=EDGE, label="p1 uplink")
for bars, vals, tot in [(b0, [g1[0], g2[0]], [sum(g1), sum(g2)]), (b1, [g1[1], g2[1]], [sum(g1), sum(g2)])]:
    for bar, v, t in zip(bars, vals, tot):
        ax.text(bar.get_x()+bar.get_width()/2, bar.get_height()+0.5, f"{v:.0f} GB\n({100*v/t:.0f}%)", ha="center", va="bottom", fontsize=9)
ax.set_xticks(x); ax.set_xticklabels(["gpu1 (client, rx)", "gpu2 (server, tx)"])
ax.set_ylabel("Bytes over 20 s (GB)"); ax.set_ylim(0, 115)
ax.set_title("HBN ECMP per-uplink distribution at 8-pair peak (~77 Gbps)")
ax.grid(axis="y", ls="--", alpha=0.4); ax.legend(frameon=False, loc="upper right")
fig.text(0.01, 0.005, "Both uplinks carry ~half the load on both DPUs → ECMP balanced across all 4 uplinks "
         "(measured on physical p0/p1 *_bytes_phy).", fontsize=7.5, style="italic", color="#444")
fig.tight_layout(rect=[0, 0.03, 1, 1]); fig.savefig(f"{OUT}/hbn_uplink_balance.png"); plt.close(fig)

# ── 3. failover timeline ──────────────────────────────────────────────────────
t = []; g = []; r = []
for line in open(f"{MT}/failover-persec.txt"):
    c = line.split()
    if len(c) >= 2:
        try: t.append(float(c[0])); g.append(float(c[1])); r.append(int(c[2]) if len(c) > 2 else 0)
        except: pass
DOWN, UP = 10.5, 31.0
fig, ax = plt.subplots(figsize=(11, 5.8))
ax.axvspan(DOWN, UP, color="#ffd9d9", alpha=0.5, label="p0_if down (single uplink)")
ax.plot(t, g, "-", color=COL_HBN, lw=2)
ax.axhline(36.3, ls=":", color="#888"); ax.text(t[-1], 36.3, " 36.3 single-uplink", va="center", fontsize=8, color="#666")
ax.axvline(DOWN, ls="--", color="#c0392b"); ax.axvline(UP, ls="--", color="#1e8449")
ax.annotate("p0_if DOWN\nBGP .240 → Active\n(250 retransmits)", (DOWN, 16), xytext=(DOWN+0.5, 10),
            fontsize=8.5, color="#c0392b", arrowprops=dict(arrowstyle="->", color="#c0392b"))
ax.annotate("p0_if UP\nBGP .240 re-Established\n(485 retransmits)", (UP, 16), xytext=(UP+0.5, 9),
            fontsize=8.5, color="#1e8449", arrowprops=dict(arrowstyle="->", color="#1e8449"))
# mark the retransmit spikes
for ti, gi, ri in zip(t, g, r):
    if ri >= 200: ax.plot(ti+0.5, gi, "v", color="#c0392b", ms=9)
ax.set_xlabel("time (s)"); ax.set_ylabel("Aggregate throughput (Gbps)")
ax.set_title("HBN uplink failover — 8-stream flow, p0 dropped at BGP layer (MTU 9000)")
ax.set_ylim(0, 44); ax.set_xlim(0, 45); ax.grid(axis="y", ls="--", alpha=0.4)
ax.legend(frameon=False, loc="lower center")
fig.text(0.01, 0.005, "Throughput held ~36.3 Gbps on the surviving uplink (no collapse); only sub-second loss "
         "at each transition. 45 s aggregate: 191 GB / 36.4 Gbps / 883 retransmits.", fontsize=7.5, style="italic", color="#444")
fig.tight_layout(rect=[0, 0.03, 1, 1]); fig.savefig(f"{OUT}/hbn_failover.png"); plt.close(fig)

print("HBN charts written:")
for f in ("hbn_aggregation.png", "hbn_uplink_balance.png", "hbn_failover.png"):
    print(f"  {OUT}/{f}")
