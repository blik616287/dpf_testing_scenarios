# Reply to Ehud — one-pager delivery + report confirmation

**Subject: RE: DPU Benchmarks**

Hi Ehud,

Yes — all the additions and corrections are on the report link you have (`BENCHMARK_REPORT.md`, `main`), including the HBN sockperf data and the supporting analysis.

And here's the customer-facing one-pager you asked for:

**https://github.com/blik616287/dpf_testing_scenarios/blob/main/CUSTOMER_ONEPAGER.md**

It's a single page covering all four configurations side-by-side — Cilium passthrough, OVN with hardware-offload **off**, OVN with hardware-offload **on**, and OVN + HBN — with:

- The full-stack value (Cilium → DPU-accelerated): host CPU −77 %, TCP_RR +175 %, TCP_CRR +286 %.
- The apples-to-apples silicon contribution (hw-offload off → on): multi-stream 15.7 → 39.4 Gbps, host CPU −51 %, 1.7× better Arm-cycle efficiency.
- HBN: ~77 Gbps 4-uplink aggregation + sub-second failover, plus the bounded latency trade-off.
- Customer caveats (40 GbE is a lab config not a BF-3 limit, PCIe Gen3, sample size, and HBN deployment maturity).

Two things worth flagging before this goes to customers:

1. **Tail-latency number corrected.** While finalizing, we found the report's "p99.9" had been reading sockperf's p99.99 line. Corrected throughout: the true **p99.9 reduction is 5.1×** (327.7 → 63.9 µs); the deeper **p99.99 is 9.3×** (963 → 104 µs). Both are real — just label them correctly if you reuse the earlier draft summary.

2. **HBN latency, characterized.** We measured the offload directly: large/long-lived flows are **~100 % hardware-offloaded** (line rate); the latency trade-off is confined to connection-churn (TCP_CRR) and small-packet RPC, not bulk traffic. The one-pager states this precisely.

One small correction still outstanding in the internal summary draft you generated — the "(hardware eswitch does the work)" line should read "(no incremental Arm CPU under load)" to match §7.8. Details and verbatim suggested edits are in `CUSTOMER_SUMMARY_CORRECTIONS.md` on the repo if useful.

Happy to tweak the one-pager's tone/length for whatever channel you're sharing it through.

Thanks,
Martin
