#!/usr/bin/env python3
"""Aggregate TC4 pod-to-pod OVN+HBN iperf3 *text* output.

iperf 3.16 on the DPU host segfaults on multi-stream, so the matrix was run
with iperf 3.19 via `crictl exec`; crictl's stdio occasionally drops the final
result-exchange (exit 1), leaving the per-second interval lines but no
"0.00-30.00 ... receiver" summary. This parser uses the summary when present
and otherwise averages the steady-state per-second [SUM]/[ID] interval lines.

Layout: results/dpf-ovn-hbn/pod-to-pod-ovn/{*.txt, ecmp-scaling/*.txt}
Runs 2-5 used for stats (run 1 = warmup).
"""
import re, glob, os, statistics, sys

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pod-to-pod-ovn")

# Gbps regardless of unit reported (iperf3 prints Mbits/Kbits for tiny datagrams)
def _to_gbps(val, unit):
    v = float(val)
    return {"G": v, "M": v / 1e3, "K": v / 1e6, "b": v / 1e9}[unit[0]]


SUM_RECV = re.compile(
    r'\[SUM\]\s+0\.00-\d+\.\d+\s+sec.*?([\d.]+)\s+([GMK]?)bits/sec.*receiver')
ONE_RECV = re.compile(
    r'\[\s*\d+\]\s+0\.00-\d+\.\d+\s+sec.*?([\d.]+)\s+([GMK]?)bits/sec.*receiver')
INT_SUM = re.compile(
    r'\[SUM\]\s+(\d+)\.\d+-\d+\.\d+\s+sec.*?([\d.]+)\s+([GMK]?)bits/sec')
INT_ONE = re.compile(
    r'\[\s*\d+\]\s+(\d+)\.\d+-\d+\.\d+\s+sec.*?([\d.]+)\s+([GMK]?)bits/sec')
UDP_RECV = re.compile(
    r'\[(?:SUM|\s*\d+)\]\s+0\.00-\d+\.\d+\s+sec.*?([\d.]+)\s+([GMK]?)bits/sec\s+'
    r'[\d.]+\s+ms\s+\d+/\d+\s+\(([\d.]+|-?nan|-?inf)%\)\s+receiver')


def tcp_gbps(path):
    """Aggregate throughput in Gbps from a TCP iperf3 text file, or None.

    Prefers the [SUM] 0.00-30 receiver line; falls back to the single [ID]
    summary; finally averages steady-state [SUM]/[ID] interval lines (used
    when crictl drops the final result exchange)."""
    try:
        txt = open(path, errors="replace").read()
    except OSError:
        return None
    m = SUM_RECV.search(txt) or ONE_RECV.search(txt)
    if m:
        return _to_gbps(m.group(1), m.group(2) or "G")
    rows = INT_SUM.findall(txt) or INT_ONE.findall(txt)
    vals = [_to_gbps(v, u or "G") for s, v, u in rows if int(s) >= 5]
    return statistics.mean(vals) if vals else None


def udp_gbps_loss(path):
    try:
        txt = open(path, errors="replace").read()
    except OSError:
        return None, None
    m = UDP_RECV.search(txt)
    if m:
        loss = m.group(3)
        g = _to_gbps(m.group(1), m.group(2) or "G")
        return g, (float(loss) if "nan" not in loss and "inf" not in loss else None)
    return tcp_gbps(path), None


def stat(vals):
    if not vals:
        return None
    m = statistics.mean(vals)
    sd = statistics.stdev(vals) if len(vals) > 1 else 0.0
    return m, sd, min(vals), max(vals)


def collect(pat, fn, runs=(2, 3, 4, 5)):
    vals, ok = [], 0
    for r in runs:
        f = glob.glob(os.path.join(BASE, pat.format(r=r)))
        if not f:
            continue
        v = fn(f[0])
        if v is not None:
            vals.append(v)
            ok += 1
    return vals, ok, len(runs)


def main():
    print("=" * 76)
    print("TC4 POD-TO-POD  —  OVN VPC + HBN  —  hardware SF / OVS-DOCA offload")
    print("MTU 1500 | iperf 3.19 | runs 2-5 (run1 warmup) | n shown per row")
    print("=" * 76)

    print("\n## TCP throughput (Gbps, receiver)")
    print(f"{'test':<20}{'mean':>9}{'stdev':>8}{'min':>8}{'max':>8}{'n':>6}")
    tcp = {}
    for p in (1, 8, 16):
        vals, ok, tot = collect(f"iperf3-tcp-{p}stream-run{{r}}.txt", tcp_gbps)
        s = stat(vals)
        tcp[p] = s
        if s:
            print(f"TCP {p:>2}-stream      {s[0]:>9.2f}{s[1]:>8.2f}{s[2]:>8.2f}{s[3]:>8.2f}{ok:>4}/{tot}")
        else:
            print(f"TCP {p:>2}-stream      {'no data':>9}{'':<24}{ok:>4}/{tot}")

    print("\n## UDP (Gbps / loss%)")
    for tag, pat in (("UDP max", "iperf3-udp-max-run{r}.txt"),
                     ("UDP 64-byte", "iperf3-udp-64b-run{r}.txt"),
                     ("UDP 1400-byte", "iperf3-udp-1400b-run{r}.txt")):
        g, ok, tot = collect(pat, lambda f: udp_gbps_loss(f)[0])
        l, _, _ = collect(pat, lambda f: udp_gbps_loss(f)[1])
        s = stat(g)
        if s:
            lm = statistics.mean(l) if l else float("nan")
            print(f"{tag:<20}{s[0]:>9.2f} Gbps   loss {lm:>6.2f}%   n={ok}/{tot}")
        else:
            print(f"{tag:<20}{'no data':>9}   n={ok}/{tot}")

    print("\n## ECMP scaling sweep (TCP, P parallel flows)")
    print(f"{'flows':<10}{'mean Gbps':>12}{'stdev':>8}{'n':>7}")
    ecmp = {}
    for p in (1, 2, 4, 8, 16, 32):
        vals, ok, tot = collect(f"ecmp-scaling/{p}-flows-run{{r}}.txt", tcp_gbps)
        s = stat(vals)
        ecmp[p] = s
        if s:
            print(f"P={p:<8}{s[0]:>12.2f}{s[1]:>8.2f}{ok:>5}/{tot}")
        else:
            print(f"P={p:<8}{'no data':>12}{'':<8}{ok:>5}/{tot}")

    print("\n## HBN ECMP — measured finding (see BENCHMARK_REPORT.md 8.5)")
    sat = ecmp.get(8)
    if sat:
        print(f"  single pod-pair ceiling : {sat[0]:>7.2f} Gbps  (one 40G HBN uplink)")
    print("  All 4 HBN BGP sessions up; VTEP route has 2 ECMP next-hops, but a")
    print("  single OVN geneve tunnel hashes onto ONE uplink (p0:p1 ~30:1).")
    print("  2-uplink ECMP does NOT multiply a single pair -> no x2. HBN ECMP")
    print("  gives fleet-level aggregate scale across many DPU pairs, not")
    print("  single-flow speedup.")


if __name__ == "__main__":
    main()
