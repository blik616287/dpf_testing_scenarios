#!/usr/bin/env python3
"""Aggregate TC4 pod-to-pod OVN+HBN iperf3 JSON results.

Parses results/dpf-ovn-hbn/pod-to-pod-ovn/ and emits a summary table.
Run 1 is treated as warmup and excluded from stats (runs 2-5).
Timed-out runs (empty/invalid JSON) are reported and excluded.
"""
import json, glob, os, statistics, sys

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pod-to-pod-ovn")


def load(path):
    try:
        with open(path) as f:
            d = json.load(f)
        if "end" not in d:
            return None
        return d
    except Exception:
        return None


def tcp_gbps(d):
    return d["end"]["sum_received"]["bits_per_second"] / 1e9


def tcp_retr(d):
    return d["end"]["sum_sent"].get("retransmits", 0)


def udp_gbps(d):
    s = d["end"].get("sum") or d["end"].get("sum_received")
    return s["bits_per_second"] / 1e9


def udp_loss(d):
    s = d["end"].get("sum") or {}
    return s.get("lost_percent", float("nan"))


def stats(vals):
    if not vals:
        return None
    m = statistics.mean(vals)
    sd = statistics.stdev(vals) if len(vals) > 1 else 0.0
    return m, sd, min(vals), max(vals)


def collect(pattern, metric_fn, runs=(2, 3, 4, 5)):
    """Return (values, n_ok, n_total) over the given run numbers."""
    vals, ok, tot = [], 0, 0
    for r in runs:
        tot += 1
        files = glob.glob(os.path.join(BASE, pattern.format(r=r)))
        if not files:
            continue
        d = load(files[0])
        if d is None:
            continue
        try:
            vals.append(metric_fn(d))
            ok += 1
        except Exception:
            pass
    return vals, ok, tot


def main():
    print("=" * 78)
    print("TC4 POD-TO-POD over OVN VPC + HBN  —  hardware SF / OVS-DOCA offload")
    print("MTU 9000  |  runs 2-5 (run1=warmup)  |  timed-out runs excluded")
    print("=" * 78)

    print("\n## TCP throughput")
    print(f"{'test':<22}{'mean Gbps':>12}{'stdev':>9}{'min':>9}{'max':>9}{'runs ok':>10}")
    for p in (1, 8, 16):
        vals, ok, tot = collect(f"iperf3-tcp-{p}stream-run{{r}}.json", tcp_gbps)
        st = stats(vals)
        if st:
            print(f"TCP {p:>2}-stream{'':<10}{st[0]:>12.2f}{st[1]:>9.2f}"
                  f"{st[2]:>9.2f}{st[3]:>9.2f}{ok:>7}/{tot}")
        else:
            print(f"TCP {p:>2}-stream{'':<10}{'no data':>12}{'':<27}{ok:>7}/{tot}")

    print("\n## UDP throughput / loss")
    for tag, pat in (("UDP max", "iperf3-udp-max-run{r}.json"),
                     ("UDP 64-byte", "iperf3-udp-64b-run{r}.json"),
                     ("UDP 1400-byte", "iperf3-udp-1400b-run{r}.json")):
        vals, ok, tot = collect(pat, udp_gbps)
        loss, _, _ = collect(pat, udp_loss)
        st = stats(vals)
        if st:
            lm = statistics.mean(loss) if loss else float("nan")
            print(f"{tag:<22}{st[0]:>12.2f} Gbps   loss {lm:>6.2f}%   {ok}/{tot} ok")
        else:
            print(f"{tag:<22}{'no data':>12}   {ok}/{tot} ok")

    print("\n## ECMP scaling sweep (TCP, P parallel flows)")
    print(f"{'flows':<10}{'mean Gbps':>12}{'stdev':>9}{'runs ok':>10}")
    ecmp = {}
    for p in (1, 2, 4, 8, 16, 32):
        vals, ok, tot = collect(f"ecmp-scaling/{p}-flows-run{{r}}.json", tcp_gbps)
        st = stats(vals)
        ecmp[p] = st
        if st:
            print(f"P={p:<8}{st[0]:>12.2f}{st[1]:>9.2f}{ok:>7}/{tot}")
        else:
            print(f"P={p:<8}{'no data':>12}{'':<9}{ok:>7}/{tot}")

    # 4-path extrapolation (measured reflects 3 functional HBN ECMP paths)
    print("\n## 4-path HBN ECMP extrapolation (measured = 3 functional paths)")
    for p in (8, 16, 32):
        st = ecmp.get(p)
        if st:
            print(f"P={p:<4} measured {st[0]:>7.2f} Gbps (3 paths)  ->  "
                  f"{st[0] * 4 / 3:>7.2f} Gbps extrapolated (4 paths)")


if __name__ == "__main__":
    main()
