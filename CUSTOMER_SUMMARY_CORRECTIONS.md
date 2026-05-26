# Customer Summary — Corrections Before External Share

Review of Ehud's customer-summary draft (DPF Pod-to-Pod Acceleration Benchmark Report) against the source report at `BENCHMARK_REPORT.md` on `main`. **The numbers all check out.** One release-blocker correction remains; **items 2 and 3 from the original review have been resolved by running sockperf UDP on HBN**, so the draft should be updated with the real data shown below.

> **Release-blocker:** item 1 (an internal contradiction with our own § 7.8 / § 7.9). Items 2 & 3 are now data-supply items (new measurements available — use them). Items 4–6 are polish — strongly recommended but won't actively mislead anyone if left.

---

## 1. Release-blocker — "(hardware eswitch does the work)" overclaims and contradicts the very next paragraph

**Where:** "HBN/ECMP Results" → "Host CPU Under HBN" bullets.

**Draft says:**

> DPU Arm CPU indistinguishable from idle under load **(hardware eswitch does the work)**

…and then two lines later correctly states:

> HBN's round-trip and connection-rate performance sits at the non-offloaded level… some per-packet flows in the HBN setup fall to the software OVS datapath rather than the hardware eswitch.

**Why it's a problem:** the two statements contradict each other. The first claims every packet rides hardware; the second concedes part of the per-packet path is in software. § 7.8 of the report addresses this directly: OVS-DOCA PMD threads run in **poll mode** at ~100 % on isolated Arm cores regardless of traffic, so `mpstat`'s "all"-averaged 8 % can't distinguish busy PMDs from idle traffic. The flat figure proves **no incremental Arm work** under bench load — *not* that every packet rides hardware.

**Suggested fix:**

> DPU Arm CPU indistinguishable from idle under load **(no incremental Arm CPU under bench load — see report § 7.8)**

This is accurate and harmonises with the RR/CRR caveat that follows.

---

## 2. RESOLVED — sockperf UDP p99.9 now measured for HBN

**Original concern:** the three-way table mixed sockperf p99.9 (T1/T2) with netperf p99 (HBN) in the same cell.

**Update:** we re-ran sockperf UDP ping-pong on the HBN cluster matching the T1/T2 methodology exactly (5 × 60 s, n=4 over runs 2-5, ~900K samples per run). The image-pull blocker that drove the original netperf-p99 substitution was solved by side-loading `docker.io/cerotyki/sockperf:latest` with `LD_PRELOAD=""` to disable its broken `libgrwrap.so` preload, and wrapping the server in a respawn loop. Real numbers, apples-to-apples:

| sockperf UDP ping-pong p99.9 (n=4) | Passthrough (A) | VPC-OVN HW (B) | **OVN+HBN (B′)** |
|---|---:|---:|---:|
| | 963 µs | 104 µs | **132.85 ± 1.97 µs** |

**Suggested fix:** replace the mixed "~97 µs (p99)" cell in the three-way table with **`132.85 ± 1.97 µs (sockperf UDP p99.9, n=4)`**. Now strictly apples-to-apples.

Raw data is in `results/mtu9000-hbn/sockperf-udp/` (5 run files + SUMMARY.md). HBN sits **+29 µs over the VPC-OVN HW arm** — the same +29 µs gap seen in TCP_RR (43 → 72 µs), confirming a constant per-packet software-path overhead from the OVN+HBN `dp:ovs` fallback (§ 7.9). The chart `results/charts/tail_latency.png` has been regenerated with the HBN 4th bar.

---

## 3. RESOLVED — sockperf was used on HBN

**Original concern:** the Methodology Highlights bullet listed sockperf as a tool used in all arms; in the original measurement sockperf was only run on T1/T2.

**Update:** sockperf UDP ping-pong has now been run on HBN as well (see item 2). The methodology bullet can stay as written: **"Tools: iperf3, netperf, sockperf, mpstat — all running inside pod containers."** No fix needed beyond using the new sockperf-p99.9 numbers in the table.

---

## 4. Polish — pod placement difference is invisible in the summary

**Where:** "Methodology Highlights" → "running inside pod containers" bullet, and the Host-CPU bullet under HBN.

**Why worth adding:** T1/T2 bench pods ran on the **DPU tenant cluster** (so iperf3's app CPU was on the DPU Arm, and host `mpstat` saw only the dataplane). HBN bench pods ran on the **host cluster** (iperf3 on host x86, so host `mpstat` includes the application's `%usr`). This is in § 7.0 of the report and matters for interpreting the host-CPU comparison:

> Host CPU at line rate: ~4–6 % busy — on par with VPC-OVN accelerated

That's true at the **busy %** level, but the *composition* differs (HBN: `%usr` includes the app; T1/T2: it doesn't). The fair offload indicator is `%sys+%soft`, where HBN ≈ 4 % vs VPC-OVN accelerated ≈ 4 % — which **does** support the "on par" claim cleanly.

**Suggested addition** (one line under Methodology):

> Bench pod placement: T1/T2 on the DPU tenant cluster (iperf3 on DPU Arm); HBN on the host cluster (iperf3 on host x86). The fair offload indicator across arms is `%sys`+`%soft`, which is roughly equal between VPC-OVN HW and HBN (~4 %).

---

## 5. Polish — clarify the "tied (wire-limited)" line

**Where:** Passthrough vs VPC-OVN table, "TCP 8/16-stream" row.

**Draft has:** "Tied (wire-limited)"

**Why worth adding:** a customer evaluating BF-3 on a newer 100 / 200 G fabric needs to know **the 40 G is a switchport configuration choice in this lab, not a BF-3 silicon limit**. BF-3 supports 200 G per port — flagged in the report as Limitation 7 but lost in the summary.

**Suggested fix:**

> Tied (limited by the lab's 40 GbE fabric configuration; BF-3 supports 200 G/port — see report § 8 limitation 7)

---

## 6. Polish — UDP "+160 %" is sender-side; effective received rate is lower

**Where:** Passthrough vs VPC-OVN table, "UDP send rate" row.

**Why worth adding:** the +160 % is the **sender-side** number; both arms are receiver-bound (single-threaded iperf3 RX socket-drain — § 4.2 of the report), so the *effective received* rate is much lower than the sender numbers in both arms. The Limitations list does include "UDP loss is iperf3-bound" so the caveat is technically present, but a casual reader of the +160 % headline won't connect the two.

**Suggested fix:** add a parenthetical to the UDP row:

> UDP send rate | ~9 Gbps | ~24 Gbps | +160 % (sender; both arms receiver-bound — see Limitations)

---

## What the summary gets right (just so it's on record)

These items are all accurate and well-handled — no change needed:

- All numeric values match the source report (verified against `BENCHMARK_REPORT.md` §§ 1, 4, 5, 6, 7).
- The reproducibility caveat is **prominently flagged** in Limitations with the ~40–80 engineer-hours estimate. Critical that this stays.
- The RR/CRR non-offload nuance (§ 7.9) is surfaced with the workload-guidance split (HBN for throughput/aggregation; VPC-OVN-HW for latency-sensitive RPC). Exactly right.
- The "40 GbE fabric is a lab constraint, not a BF-3 limit" caveat is in Limitations.
- The "PCIe Gen3 (old Supermicro chassis)" caveat is in Limitations.
- The "Bottom Line" summary fairly characterises both the VPC-OVN win (clean CPU/latency/transaction gains) and the HBN trade-off (aggregation win + RR latency cost + deployment complexity).

---

## Suggested reply skeleton (updated)

> Hi Ehud — thanks for the great summary, it tracks the report closely. One release-blocker correction and one data update before we share externally, plus three optional polish items:
>
> 1. **Must-fix:** change "(hardware eswitch does the work)" → "(no incremental Arm CPU under bench load)" on the DPU Arm CPU bullet — aligns with § 7.8 and removes the contradiction with the RR/CRR caveat in the next paragraph.
> 2. **Data update:** we re-ran sockperf UDP ping-pong on HBN (5 × 60 s, n=4, ~900K samples/run). Real p99.9 = **132.85 ± 1.97 µs**. Please replace the "~97 µs (p99)" cell in the three-way table with **132.85 ± 1.97 µs (sockperf UDP p99.9, n=4)** — now strictly apples-to-apples with the T1/T2 sockperf p99.9 numbers. The chart `results/charts/tail_latency.png` and report § 7 / § 7.6 / § 7.9 have been updated to match.
> 3. **Polish (optional):** one line noting pod placement differs (T1/T2 on DPU tenant; HBN on host) — the fair host-CPU comparison is `%sys+%soft` (≈4 % both for VPC-OVN HW and HBN), which actually *strengthens* the "on par" claim. Two more small polish items in the doc.
>
> With items 1 and 2, I'm comfortable sharing.

Full breakdown including the source citations and verbatim suggested text is in `CUSTOMER_SUMMARY_CORRECTIONS.md` on the repo's main branch.
