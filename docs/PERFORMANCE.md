# Mobile Sales — Performance (v1.0.0)

What was measured, what was slow and why, what was changed, and how to measure again. All numbers are from the
test site `mstest.local` on the production server (4 CPUs, 16 GB, MariaDB 10.11, Frappe 16.32 / ERPNext 16.33),
with the measuring process at `nice -n 10 ionice -c3` while agrosys and the Gills sites stayed live.

Targets (spec §8): phone API calls < 2 s, settlement draft < 3 s, reports < 5 s.

## 1. Volume

`mobilesales/perf/seed.py` builds its own company "_MS Perf Co": 10 agents, each with a van, a route of 30 shops and
a full day every day. One day per agent: morning load, 30 visits (sales with cash, credit and cheque, returns
against earlier invoices, collections of earlier credit, no-sale and shop-closed visits), End Day and the settlement
through the whole workflow (store keeper, cashier, supervisor), each step as its real role user.

| | 30 days | 60 days |
|---|---|---|
| Trips / settlements | 300 | 600 |
| Customer visits | 9,000 | 18,000 |
| Sales Invoices (incl. credit notes) | 6,431 | 12,901 |
| Payment Entries | 4,981 | 10,239 |
| GL Entries | 38,065 | 76,905 |
| Stock Ledger Entries | 39,706 | 79,573 |

A year at this rate: about 3,650 trips, 110,000 visits, 78,000 invoices, 460,000 GL and 480,000 stock ledger rows.

## 2. Results against the targets

Server-side wall time without HTTP, median (worst) of 3 runs, `mobilesales/perf/timings.py`. Reports cover the last
60 days as the supervisor; at 30 days that range holds 300 trips, at 60 days 600.

| | 30 days | 60 days | target |
|---|---|---|---|
| **Phone API** (agent) | | | < 2 s |
| get_context / get_visits / search_customers | 0.003–0.004 (0.012) | 0.002–0.005 (0.007) | |
| get_route_plan | 0.013 (0.042) | 0.013 (0.106) | |
| get_van_stock | 0.124 (0.134) | 0.031 (0.032) | |
| get_my_day | 0.020 (0.044) | 0.023 (0.026) | |
| get_customer (card) / get_customer_invoices | 0.006 / 0.036 | 0.008 / 0.036 (0.065) | |
| price_cart, 4 lines | 0.065 (0.068) | 0.065 (0.069) | |
| price_cart, 4 lines + return + previous invoice | 0.080 (0.087) | 0.119 (0.141) | |
| visit submit, sale + payment (§3.2, warm median) | 0.85 | 1.09 | |
| visit submit, sale + return (§3.2, warm median) | 1.44 | 1.37 | |
| **Settlement** | | | < 3 s |
| get_settlement_draft (30 visits) | 0.036 (0.047) | 0.041 (0.050) | |
| save_settlement | 0.084 (0.204) | 0.083 (0.377) | |
| **Reports**, supervisor, 60-day range | 300 trips | 600 trips | < 5 s |
| Salesperson Performance | 1.7 | 4.64 (5.93) | |
| Daily Trip Summary | 1.9 | 4.72 (6.72) | |
| Customer Visit Register | 1.4 | 2.38 (2.82) | |
| Discount Report | 1.1 | 2.47 (3.09) | |
| Customer Returns Register | 1.1 | 2.34 (2.59) | |
| Mobile Stock Variance | 1.1 | 2.11 (2.25) | |
| Route Coverage | 0.75 | 1.35 (1.49) | |
| No Sale Reason Analysis / Mobile Cash Variance | 0.34 / 0.21 | 0.54 / 0.51 | |
| Customer Stock Position / Outstanding by Agent | 0.18 / 0.05 | 0.34 / 0.05 | |
| any report, 1 day; Mobile Trip Day Report | ≤ 0.1 | ≤ 0.1 | |
| workspace charts (30 days) | ≤ 0.03 (no trips yet in the window) | 0.24–1.59 (2.02) | |
| Customer Visit Register as an agent (own trips) | 0.48 | 0.28 (0.59) | |

The 30-day report column is after the report change of §3.6 (5 runs, warm); the old code took 3.3–7.1 s there.

Every phone call and the settlement draft are far inside the targets at 60 days. Two reports over 600 trips have a
median under 5 s and a worst run above it: Salesperson Performance and Daily Trip Summary build the full trip summary
(visits, discounts, payments, settlement lines and the van's stock ledger) for every trip. The worst run is the first
one, with the rows read from disk (next section).

Guards on standard documents that touch nothing mobile (the office path): 1.3–3.7 µs per call.

## 3. The investigation

### 3.1 The symptom

The first 30-day seed got slower every day: 238 s for day 1, 448 s for day 20, about 520–570 s from day 22. Postings
in date order should cost the same each day, so this was investigated before release.

### 3.2 The app's own cost does not grow

One complete visit was profiled (cProfile + every SQL statement timed) on an empty day and on day 30. Medians of
repeated runs, no profiler:

| step | empty day | day 30 |
|---|---|---|
| sale + payment | 0.95 s | 0.85 s |
| sale + return (against an earlier invoice) | 1.43 s | 1.44 s |
| load (Mobile Trip submit, stock issue) | 1.54 s | 1.39 s |
| settlement, the whole workflow | 2.47 s | 1.97 s |
| price_cart | 0.06–0.08 s | 0.06–0.08 s |

A whole seed day (3 agents × 30 visits, fresh process): 113 s on an empty day, 136 s on day 30 (day 30 also has
returns and collections of earlier credit, which an empty day cannot have).

### 3.3 Where the growth came from

Both causes were in the seed, not in the app, and neither happens in production.

1. **Frappe's `currently_saving` list (Frappe core, long processes only).** Frappe appends every document it saves to
   `frappe.flags.currently_saving` and removes it after the save, but an inserted document's entry stays (its name
   changes during naming). Every save scans the list. The seed is one process for 30 days, so the list reached about
   200,000 entries; with it pre-filled to that size one seed day took 23 % longer. Frappe resets the flags for every
   web request and background job, so phones and Desk never see it. The seed now clears it before each posting.
2. **Repost Item Valuation (ERPNext core, triggered by the seed's clock).** ERPNext reposts later stock ledger entries
   when a stock posting is back-dated, and its test (`future_sle_exists`) uses `posting_datetime >=`: a posting at the
   same moment as an existing one on the same item and warehouse counts. The seed posted every van's load at exactly
   06:00:00 and every settlement at exactly 20:00:00 on the same store warehouse, which queued about 740 item-wise
   reposts per day (22,180 by day 30). Nothing was back-dated by date. The test site's scheduler was on, so these
   ran on the shared workers, holding row locks against the seed (the last one ran 26 minutes and timed out).
   The seed now staggers postings by minute (loads 06:00 + n, visits 08:00 + 15 min steps, settlements
   20:00 + 3 min steps), the test sites' scheduler is off (CLAUDE.md rule 22), and the seed runs any job it
   enqueues inline instead of on the shared workers.

After the fix the per-day time is flat:

| day | 1 | 5 | 10 | 15 | 20 | 25 | 30 | 35 | 40 | 45 | 50 | 55 | 60 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| old seed (s) | 238 | 263 | 300 | 353 | 448 | 507 | 536 | | | | | | |
| fixed seed (s) | 233 | 242 | 242 | 261 | 256 | 226 | 262 | 259 | 299 | 252 | 264 | 283 | 305 |

Full curve (seconds per seed day of 10 agents × 30 visits):

- old: 238 218 242 238 263 257 275 267 279 300 320 329 350 403 353 373 396 436 405 448 472 509 509 469 507 516 503 571
  520 536
- fixed: 233 215 238 233 242 242 237 233 240 242 245 254 258 251 261 267 225 266 245 256 233 238 243 220 226 252 239
  264 236 262
- fixed, days 31–60 (a second run that continued the first): 268 234 282 272 259 263 269 296 281 299 278 303 279 260
  252 290 282 282 282 264 328 270 273 271 265 283 260 268 270 305

Ten-day means of the fixed seed: 236, 253, 241, 272, 277, 279 s. Each 30-day run is flat on its own (0.41 and
0.37 s per day); the step at day 31 is where the second run started and the database (532 MB by then) outgrew more of
the server's database cache (§4). A straight line through all 60 days gives 0.92 s per day.

Reposts still queued by the fixed seed: 178 in 30 days (was 22,180). They come from the settlement: its return entry
and its damage entry leave the van at the same posting time, so the second one counts as back-dated when both carry
the same item. Each is small and the scheduler runs it within the hour; see DEFERRED.md §9.

### 3.4 Queries whose cost grows with the data

Every query shape of a profiled visit and settlement on day 30 (446 shapes) was run through EXPLAIN. Two scanned a
whole table that grows with every sale, both in ERPNext core:

| query | caller | day 30 EXPLAIN | per call |
|---|---|---|---|
| `tabSales Invoice Item WHERE sales_invoice_item IN (…)` | `erpnext.controllers.sales_and_purchase_return.get_filters_for_packed_item` (3 calls per return) | ALL, 14,103 rows | 9.43 ms |
| `tabSerial and Batch Bundle WHERE voucher_no = …` | ERPNext's bundle lookup on every batch line posted, returned or cancelled | ALL, 5,772 rows | 2.74 ms |

The only query of ours whose cost depends on the volume is `reconciliation.get_agent_cash_balance` (the settlement's
post-condition): a range on an indexed account, 2.6 ms on day 30, estimated 30 ms after a year. Left as is.

### 3.5 The indexes the app adds to ERPNext tables

| table | column | index | serves |
|---|---|---|---|
| `tabSales Invoice Item` | `sales_invoice_item` | `ms_sales_invoice_item` | rows already returned against an invoice row |
| `tabSerial and Batch Bundle` | `voucher_no` | `ms_voucher_no` | the batch bundles of a voucher |

- Added only by the patch `mobilesales.patches.v1_0.add_core_lookup_indexes` (migrate) and by `after_install`
  (install marks patches done without running them); never by hand. `before_uninstall` drops them.
- The patch skips an index when the table already has one (unique or not) whose first column is that field, so a
  later ERPNext release that adds its own does not get a duplicate. The `ms_` prefix keeps the names apart from
  ERPNext's own; Frappe's schema sync only manages indexes named after a field and leaves these alone.
- They serve standard ERPNext as well: every sales return made in Desk (credit note against an invoice) runs the same
  `sales_invoice_item` lookup, and every batch-tracked voucher, mobile or not, the `voucher_no` lookup.
- Test: `test_integrity.test_core_lookup_indexes` (both exist, EXPLAIN uses them, the patch run twice does nothing).

Effect on day 30 (per call): 9.43 → 0.50 ms and 2.74 → 0.51 ms. Per visit, A/B with the indexes dropped and re-added
in alternating rounds (medians, no profiler): sale + payment 1.053 → 1.015 s (32 visits), sale + return 1.725 →
1.488 s (20 visits). The difference grows with the tables: without the index a return after a year scans about
170,000 invoice rows three times.

### 3.6 Reports

The day-30 timings found four reports over 5 s for a 60-day range (Salesperson Performance 7.1 s, Discount Report
6.9 s, Daily Trip Summary 6.3 s, Mobile Stock Variance worst 5.4 s). The SQL log showed why: each report loaded every
trip on its own, about 19 small queries per trip (visits, invoices, payments, journals, the settlement with its five
child tables, route plan, discounts, sale lines, stock ledger), plus one query per invoice in the Discount Report.
The cost grew with the number of trips in the range, so a 60-day range at 10 agents would have taken about 13 s.

`services/reports.py` now loads 50 trips at a time with one query per table (`iter_trip_documents`,
`trips_documents`); a single trip (Day Report, "My day") goes through the same loader. Reports that do not need the
trip summary skip its stock ledger, sale lines and payment references. On day 30 (300 trips): 5,693 queries → 176
for Daily Trip Summary. All 11 reports, the 4 workspace charts, 40 Day Reports and 40 "My day" results were compared
with the old code on the same data: identical.

| report, 300 trips | before | after |
|---|---|---|
| Salesperson Performance | 6.23 s | 2.24 s |
| Daily Trip Summary | 5.94 s | 1.91 s |
| Customer Visit Register | 5.60 s | 1.43 s |
| Discount Report | 7.27 s | 1.12 s |
| Customer Returns Register | 4.88 s | 1.09 s |
| Mobile Stock Variance | 4.11 s | 1.08 s |
| Mobile Cash Variance | 3.30 s | 0.21 s |
| Customer Stock Position | 1.28 s | 0.19 s |

(first run in a fresh process, so slightly above the warm medians in §2)

## 4. Extrapolation

### 4.1 What still grows with history

Profiling the same visit and settlement on day 60 (`profile.run`) against day 30 found the same query count in every
step and two statements whose cost grows with the whole history, not with the day:

| statement | owner | day 30 | day 60 |
|---|---|---|---|
| batch availability for FIFO (sum of every Serial and Batch Entry of the item in the warehouse) | ERPNext core, at load and on every batch sale | 8 ms per call warm | 13–40 ms warm, up to 0.6 s cold |
| `reconciliation.get_agent_cash_balance`: sum of the agent cash account's whole GL history (settlement post-condition) | ours | 11–28 ms | 0.38–1.17 s cold (1,119 rows per agent) |

Both read rows scattered over their tables (Frappe names are random, so rows are not stored together), so their cost
is small when the rows are cached and one disk read per row when they are not.

### 4.2 The database cache

MariaDB on this server runs with the default `innodb_buffer_pool_size` of 128 MB, shared by every site of every bench
(about 30 databases; mstest alone was 532 MB at 60 days). The 60-day timings run read 33,000 pages (about 520 MB) from
disk. This, not the queries' plans, is what separates a report's median from its worst run and what makes the two
history sums above slow when cold. Raising the pool (the server has 16 GB, about 7 GB available) would help every
bench on the server; it is a server setting, outside the app (decision for the server owner).

### 4.3 Estimates

Linear in the measured growth, warm cache unless stated; volume as in §1 (10 agents).

| | measured 30 days | measured 60 days | 1 year (estimate) |
|---|---|---|---|
| seed day (10 agents × 30 visits, every role step) | 241 s (days 21–30) | 279 s (days 51–60) | ≤ 569 s (straight line through 60 days) |
| phone API calls | ≤ 0.13 s | ≤ 0.14 s (one cold 0.39 s) | < 0.6 s |
| visit submit, sale + payment / sale + return | 0.85 / 1.44 s | 1.09 / 1.37 s | about 1.5 / 1.8 s warm; 1–2 s more cold (batch sum) |
| settlement draft | 0.05 s | 0.05 s | < 0.1 s |
| settlement submit post-condition (GL sum) | 0.01–0.03 s | 0.4–1.2 s cold | about 0.1 s warm, 3–7 s cold |
| 60-day reports (600 trips in range) | — | 4.6–4.7 s median, ≤ 6.7 s | about the same: they read the trips in the range by index, not the history; a wider range grows with its trips |

The reports' cost follows the number of trips in the chosen range (10 agents × 60 days = 600 trips), not the age of
the database; with 3 agents a 60-day range is 180 trips (about 1.5 s).

### 4.4 Follow-ups (DEFERRED.md §10)

- The cash post-condition reads the whole account history. Options: a covering index on GL Entry
  (`account, is_cancelled, debit, credit`, a third index on an ERPNext table, needs approval), or a bounded check
  from the last settled zero balance.
- The two full-summary reports: store each trip's summary figures on the trip at settlement and read those, so a
  report reads one row per trip.
- Frappe switches a script report to "Prepared Report" (background job) by itself when one run takes over 15 s
  (`Report.execute_script_report`). It happened once on the test site during a cold run; if a Mobile Sales report
  shows "generating" in Desk, untick *Prepared Report* on the Report record (ADMIN_GUIDE.md §8).

## 5. How to measure again

All on `mstest.local` (never agrosys), as rajerp, with the scheduler off (`bench --site mstest.local scheduler
status`), at low priority, outside 08:00–18:00 Colombo if the live sites slow down (CLAUDE.md rule 22).

```bash
cd /home/rajerp/AgroPublic
# backup first: the seed commits after every day; restore the backup afterwards (CLAUDE.md rule 21)
bench --site mstest.local backup
nice -n 10 ionice -c3 bench --site mstest.local execute mobilesales.perf.seed.run \
  --kwargs '{"agents": 10, "days": 60, "visits": 30, "only": 30}'   # first 30 days; run again with 60 to continue
nice -n 10 ionice -c3 bench --site mstest.local execute mobilesales.perf.timings.run
nice -n 10 ionice -c3 bench --site mstest.local execute mobilesales.perf.profile.run --kwargs '{"out": "/tmp/p.json"}'
nice -n 10 ionice -c3 bench --site mstest.local execute mobilesales.perf.profile.reports
```

- `seed.run` prints the seconds per day; it waits between days while `/tmp/ms_seed.pause` exists.
- `profile.run`: three agents on their own new days (cold, warm, profiled), each step's median, cProfile output,
  every SQL shape with count and time, EXPLAIN of the heaviest; rolled back.
- `profile.reports`: each report's time, query count and heaviest query shapes.
- `profile.process_growth`: several seed days in one process with the size of Frappe's process-local state per day
  (how the `currently_saving` growth was found).

## 6. Operating notes

- Keep the scheduler on for agrosys: reposts queued by settlements (DEFERRED.md §9) and ERPNext's own are processed
  by it.
- Never seed or profile on agrosys; the perf company exists only on the test site.
- After an ERPNext upgrade, run `profile.run` on a restored copy and check its EXPLAIN list for new full scans.
