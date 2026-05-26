# Customer Summary — Corrections Before External Share

Review of Ehud's customer-summary draft (DPF Pod-to-Pod Acceleration Benchmark Report) against the source report at `BENCHMARK_REPORT.md` on `main`. **The numbers all check out.** Four corrections are needed before sharing externally — three are correctness fixes, one is nice-to-have polish that strengthens credibility.

> **Release-blocker:** item 1 (an internal contradiction with our own § 7.8 / § 7.9). Items 2–3 are smaller but should be fixed in the same pass. Items 4–6 are polish — strongly recommended but won't actively mislead anyone if left.

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

## 2. Three-way table — apples-to-oranges in the tail-latency row

**Where:** "Three-Way Comparison" table.

**Draft has:**

| Metric | Passthrough (A) | VPC-OVN HW (B) | OVN+HBN (B′) |
|---|---:|---:|---:|
| Tail latency p99.9 | 963 µs | 104 µs | ~97 µs (p99) |

**Why it's a problem:** the first two cells are **sockperf p99.9**; the HBN cell is **netperf p99** — a smaller percentile from a different tool. (sockperf wasn't pullable in our HBN env, so netperf p99 was used as a substitute — see report § 7.0 methodology box.) At a glance a customer will read this as "HBN tail latency ≈ VPC-OVN HW," which isn't a fair comparison.

**Suggested fix (either option works):**

**Option A — drop HBN cell + footnote:**

| Metric | Passthrough (A) | VPC-OVN HW (B) | OVN+HBN (B′) |
|---|---:|---:|---:|
| sockperf p99.9 tail latency | 963 µs | 104 µs | n/a¹ |

> ¹ HBN not measured at p99.9 (sockperf image unavailable). For reference, netperf TCP_RR p99 on HBN was 97 µs.

**Option B — split into two rows:**

| Metric | Passthrough (A) | VPC-OVN HW (B) | OVN+HBN (B′) |
|---|---:|---:|---:|
| sockperf p99.9 tail latency | 963 µs | 104 µs | — (not measured) |
| netperf TCP_RR p99 | — | — | 97 µs |

Either keeps each row comparing within a single metric.

---

## 3. Methodology lists "sockperf" — not used on HBN

**Where:** "Methodology Highlights" → tools bullet.

**Draft says:**

> Tools: iperf3, netperf, sockperf, mpstat — all running inside pod containers

**Why it's a problem:** sockperf only ran on T1/T2 (DPU tenant cluster pods). For HBN, the sockperf image was not pullable in our environment, so netperf TCP_RR p99 was used instead. The summary as written implies sockperf data exists for HBN.

**Suggested fix:**

> Tools: iperf3, netperf, mpstat (all arms); sockperf p99.9 (T1/T2 only — image unavailable for HBN, netperf p99 used in its place)

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

## Suggested reply skeleton

> Hi Ehud — thanks for the great summary, it tracks the report closely. Before we share externally, four small corrections that need to land first (one is a contradiction with a caveat later in the same summary, so worth catching):
>
> 1. Change "(hardware eswitch does the work)" → "(no incremental Arm CPU under bench load)" — aligns with § 7.8 of the report and removes the contradiction with the RR/CRR caveat in the next paragraph.
> 2. In the three-way table, the HBN "tail latency" cell is netperf p99 (different metric from the sockperf p99.9 used for A and B). Either drop the HBN cell with a footnote, or split into two rows.
> 3. The Methodology bullet lists sockperf as a tool used in all arms; it was only run on T1/T2.
> 4. (Optional polish) One line noting pod placement differs (T1/T2 on DPU tenant; HBN on host), so the fair host-CPU comparison is `%sys+%soft` (≈4 % both for VPC-OVN HW and HBN).
>
> With those four, I'm comfortable sharing.

Full detail and verbatim text for each fix is in `CUSTOMER_SUMMARY_CORRECTIONS.md` on the repo's main branch.
