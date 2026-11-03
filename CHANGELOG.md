## v1.0.0 — Phase 7: hardening

Security (docs/SECURITY_REVIEW.md, 11 findings fixed):
- Visit, settlement and trip links to the vouchers they posted can no longer be typed in (REST save of a draft, or an
  update after submit). Cancel chains only cancel a voucher that points back to the document; a supervisor cancelling
  a forged visit could otherwise have cancelled an office invoice.
- Settlement verifiers (Verified by Store / Cashier) are set only by the workflow.
- Agents see only selling Item Prices, their own Serial and Batch Bundles, Contacts / Addresses of customers, and
  receivable accounts plus their own cash account in link searches.
- `price_cart` refuses other customers' invoices. Photo size is checked before decoding, and a retake replaces the
  earlier photo. Search text is capped. The return invoice picker searches one customer's invoices and keeps the
  typed text (bug).
- Per-user limits on the expensive phone calls (pricing, submit, uploads, invoice list, settlement draft, receipts).

Data integrity:
- Retries and double taps change nothing twice:
  - start / end day and Submit for Verification return the current state;
  - a settlement can't be started twice (locking read);
  - a retried visit that was cancelled meanwhile is refused, not shown as recorded.
- Tested with ledger snapshots (stock ledger, Bin, batches, GL, payment ledger, outstanding): visit, settlement and
  trip cancel restore everything.
- Real-thread races on a disposable site: last stock (one visit sells, the other is refused), the same visit sent
  twice at once (one visit), a settlement started twice at once (one settlement).
- No sale at a missing price: an item without a valid Item Price on the visit date is refused instead of being
  invoiced at 0.
- Invoices delivered with a Delivery Note are left out of the return pickers and refused with a clear message
  (return them at the office).
- Patches run twice without change (tested).

Upgrade safety (ERPNext version-16 head: frappe 16.54.0, erpnext 16.53.0, throwaway bench): 9 of 133 tests broke, all fixed:
- Stand-alone credit notes now carry a stock value (van, store or Item valuation). ERPNext 16.5x refuses them at 0 in
  a warehouse without history.
- Batch read for store keeper and cashier: ERPNext 16.5x `get_batch_qty` checks Batch select as the user, which
  blocked the cashier's settlement submit.
- The permission drift check compares the standard rules with a baseline taken when they were copied, and reports
  each change once. Rules other apps add as Custom DocPerm (ERPNext 16.5x adds Accounts Manager read on Address) are
  not drift.
- The desktop icon is imported only on the icon-grid desktop in Frappe 16.5x (test adjusted; the workspace and
  sidebar are unchanged).
- Full suite: 133/133 on the live versions (16.32 / 16.33) and on the v16 head.

Install / uninstall:
- `before_uninstall` removes the Mobile Sales role rules, every permission copy still equal to the standard rules,
  the settlement workflow and the agents' User Permissions.
- A fresh install, the setup checklist, a full day, the standard SO → DN → SI → PE as an office user, and uninstall
  (nothing left but the four roles; the office flow still works) were checked on a disposable site.

Phone:
- Today without a trip: one "No trip loaded" heading, "Ask the store keeper to load your van.", and the last trip
  ("Last trip MTRIP-… · Settled · sales …").

20:00 Day Report email: skipped (one log line, nothing queued) while the site has no default outgoing Email Account.

Performance (10 agents × 60 days × 30 visits; docs/PERFORMANCE.md): PERF_SUMMARY

Docs: ADMIN_GUIDE, USER_GUIDE_AGENT, USER_GUIDE_STORE_CASHIER, QUICK_START, DEFERRED, SECURITY_REVIEW, PERFORMANCE;
SPEC acceptance tests ticked with the tests that prove them. Tools: mobilesales/perf (seed, timings, install_check).

## v0.7.0 — Phase 6: reports, Mobile Trip Day Report, workspace

- Reports (Script Reports, module Mobile Sales; ref_doctype Mobile Trip; filters company, dates, agent, vehicle, route, territory):
  Salesperson Performance, Daily Trip Summary, Customer Visit Register (off route, manual discount, returns, credit applied),
  No Sale Reason Analysis (chart), Customer Stock Position, Route Coverage, Mobile Stock Variance, Mobile Cash Variance,
  Outstanding by Agent (ageing), new Customer Returns Register (adds up to the customer return warehouse's Stock Ledger) and new
  Discount Report (manual discounts vs the agent cap, pricing-rule effect apart). One shared module, services/reports.py.
- Roles: Supervisor, Store Keeper, Cashier, System Manager, Accounts Manager (now read / report on Mobile Trip, Customer Visit,
  Mobile Settlement). Agents: Customer Visit Register, Customer Stock Position, Outstanding by Agent and the Day Report, own trips only.
- Mobile Trip Day Report (spec §7.1): Script Report (filter trip) and A4 print format on Mobile Settlement — header with vehicle /
  helper, KPIs, visit log with map links, missed customers, customer updates, shelf stock, sales by invoice (return credit and cash
  apart) and by item, collections, customer returns, stock (issued / top-up / sold / returned / damaged / missing), cash with
  denominations and cheques, sign-off from the workflow log. The PDF is attached to the settlement on submit (background, after commit).
- Daily email at 20:00 (scheduler cron) of the day's settled trips' Day Reports to the Mobile Sales Supervisors; Mobile Sales
  Settings → Daily Report Email (default off).
- Workspace "Mobile Sales" with sidebar and desktop icon: shortcuts (incl. Mobile Visit Rejection), 7 number cards, 4 charts
  (sales by agent, strike rate, no-sale reasons, returns by reason), report links.
- Phone: Today screen "My day" card (visits / planned, sales, cash collected, returns, credit given) via get_my_day.
- Fix: settlement Credit Sales no longer counts return credit set off against the sale (MSET-26-00004 showed 1,825 credit sales for a
  day with no credit given).
- Tests: a seeded trip (discounts, top-up, credit sale, returns against today's and an older invoice, off-route no-sale, missed
  customer, stock and cash shortage) with every report's totals compared to GL / Payment Ledger / Stock Ledger; agent scoping and
  report roles; Day Report sections, A4 print, PDF attached once; email built (not sent), off by default, skipped without trips;
  number cards and charts; vitest for "My day".

## v0.6.1 — fixes from the v0.6.0 live run

- Fix: the Returns step dropped a return that was filled in but not added with "+ Add return" (live run
  MTRIP-26-00005: the visit was submitted without it). Next is now blocked while a return is pending, with a
  hint and a Clear button; the Review step lists every return line; the done screen shows the return credit.
- Mobile Invoice 4in: list price and discount per discounted line, Subtotal and Invoice discount lines, and
  Grand Total / Rounding adjustment when the total is rounded.
- Prints (4-inch, standard, module Mobile Sales; figures from mobilesales.services.prints via hooks.jinja):
  - New **Mobile Visit Bill** (Customer Visit): SALES (invoice, lines with list rate and discount, sales
    total, rounding), RETURNS per return note (negative lines "against <invoice> · <reason> · <condition>",
    return total), "Return credit applied" per invoice from the set-off journal, credit left on account,
    net payable, paid (cash), balance, previous outstanding, total due, customer / agent signature lines.
  - **Mobile Invoice 4in**: a credit set-off is never cash any more: "Return credit (MB-SRET-…) −x",
    "Paid (cash)", "Balance" (MB-SINV-26-00004 printed Paid 2,518 for 1,193 cash + 1,325 credit). Invoice
    discount prints one minus sign and the percentage without trailing zeros.
  - New **Mobile Return Note** (Sales Invoice, is_return): RETURN NOTE, against invoice, visit, lines with
    reason / condition / remarks, total credit, credit applied per invoice, credit left, signature lines.
  - Phone (success screen and History): Print Bill (primary), Print Invoice, Print Return Note (one per note),
    Print All (/mobile-sales-print: bill → invoice → return notes on one page), each only when the
    document exists; the Receipt print stays for visits with a Payment Entry.
- Fix: an invoice discount entered as a percentage stays a percentage on the invoice and the visit (the
  submit rebuild turned 5% into a fixed 132.50).
- New Mobile Visit Rejection log (supervisor: read, report, export): every submit_visit the server refuses
  is recorded with user, agent, trip, customer, outcome, client_ref and the message the agent saw. Written
  after the request rollback in its own transaction.
- Returns step: the invoice picker starts on "Choose invoice…" ("No invoice" is an explicit choice); the
  not-added hint appears only once an item or quantity is entered; while "+ Add return" is disabled the
  form says what is missing (invoice, item, qty, qty above returnable, reason, remarks for reason X).
- Return invoice picker: newest first, each invoice as "number · date · qty still returnable · total · owes x /
  paid" (MB-SINV-26-00001 and ACC-SINV-2026-00001 were easy to confuse).
- Collection: when the return credit covers the sale, Collect Now is set to the amount due (0), read-only,
  with "Return credit covers this invoice — nothing to collect."; Collect Now also drops to the due amount
  whenever the due falls below what was entered (no refused submit).
- Return reason and condition start empty ("Choose reason…", "Choose condition…") on every new return line:
  condition no longer defaults to Resaleable (CV-26-000008 was saved Resaleable), nothing is kept from the
  line before, and "+ Add return" stays disabled until both are chosen.
- Return lines show reason and condition as labelled badges (Damaged in red) with the remarks, on the
  Returns step and on Review.
- Submit visit asks for confirmation with a summary: sale lines (qty, rate, line discount), invoice
  discount, total, returns with invoice / reason / condition, credit applied, previous invoices and the cash
  to collect now; Cancel has the focus.
- Tests: the live-run steps through the phone API as the real agent (6% refused, return above the invoiced
  qty refused, 1 sold + 1 returned = no cash; visit 2: refused submit logged, 5% kept, prints split credit and
  cash); print render tests (sale only, sale + return with split set-off, return only with credit left,
  discounted sale with rounding; Print All page as agent / supervisor / other agent); SPA tests: a pending return blocks Next and is submitted, empty picker and missing-field text, the
  confirm dialog summary with Cancel focused, the print buttons per case and the Print All order.

## v0.6.0 — Phase 5b: Vehicles, discounts, customer returns

- Mobile Vehicle (vehicle no., description, van warehouse, default driver, active): "Create Van Warehouse"
  makes the van under the van group. Trips need a vehicle (default from the agent) and may name a helper;
  one open trip per vehicle and per agent; the vehicle's van must be empty before loading. The agent keeps
  the cash account; agent setup no longer creates a warehouse (Agent.van_warehouse is legacy data).
  Patch: every agent's existing van becomes Mobile Vehicle VAN-01, VAN-02, … (active only if the agent is),
  set as default vehicle and on the agent's old trips; it refuses to run while any trip is open.
- Discounts: per line % or amount on top of the pricing-rule rate; invoice discount on Net Total. Cap: the
  agent's manual discounts ÷ price-list value ≤ Max Discount % (pricing-rule discounts not counted). When a
  pricing-rule line also gets a manual discount the invoice keeps the priced rates (Ignore Pricing Rule);
  refused when that would drop a free-item offer.
- Customer returns (Settings: Returns Enabled, Customer Return Warehouse, credit note series MB-SRET):
  return lines on Sale / Collection Only and the new Return Only outcome (item, qty, against invoice,
  reason from Mobile Return Reason, condition Resaleable / Damaged). One credit note per original invoice
  (plus one without), into the customer return warehouse; batch items need the invoice and return the
  batches sold on that line; rate = the original net rate, else the price list. Per-visit limit on the
  agent (0 = supervisor only).
- Credit set-off, never cash: one Credit Note Journal Entry (like ERPNext's Payment Reconciliation) applies
  the credit to the returned invoice, today's sale and the selected previous invoices; the Payment Entry
  covers only the rest. Leftover credit stays on the customer ("credit available" on the customer card).
- Settlement: "Customer Returns Received" — the store keeper confirms received and damaged per item;
  damaged → Return Damage (to the damage warehouse), missing → Return Shortage; good returns stay in the
  customer return warehouse. Cancel reverses them. Mobile Settlement Sheet section.
- Guards: mobile credit notes only into the customer return warehouse; stock into it only from them
  (Stock Entry, Stock Reconciliation, Sales Invoice / Delivery Note returns, Purchase Receipt / Invoice);
  stock out of it stays normal.
- Phone app: vehicle and helper on Today; line / invoice discount; Returns step; credit applied and due;
  credit-note prints; History shows returns. Settlement screen is read-only outside Draft, and Submit for
  Verification first lists what will be recorded as missing and any cash short / over (Cancel focused).
- Mobile Sales Supervisor: read on the visit masters (Customer, Item, UOM, Price List, Item Price, Batch,
  Contact, Address, Territory, Customer Group) and select on Account, so supervisors can submit visits from
  Desk (Custom DocPerm copies, drift-checked).
- Tests: 106 (+ 35 SPA mount tests), incl. credit notes compared with ERPNext's make_sales_return.

## v0.5.0 — Phase 5: Mobile phone app

- Phone app at /mobile-sales (Vue 3 + frappe-ui, installable PWA) for Mobile Sales Agents: Today (trip,
  van stock, Start Trip / End Day), Route (planned customers in sequence, search, quick-entry new
  customer), Visit wizard (check-in GPS + photo, customer changes, shelf stock, outcome, cart from van
  stock with server pricing, collection of current and previous invoices, submit, print), History
  (today's visits, reprint) and Settlement (returned / damaged counts, cash denominations, submit for
  verification).
- Whitelisted API (spec §6.2): every method requires a Mobile Sales role, resolves the agent from the
  session and re-checks trip / visit ownership; totals are recomputed on the server. `submit_visit` is
  idempotent on `client_ref` (a repeated submit returns the same visit). `save_settlement` +
  `submit_settlement_for_verification` replace the planned single `submit_settlement`.
- Online only: the service worker caches the app shell only; an offline banner shows and every submit is
  blocked while offline; submit buttons are protected against double taps. Item master / route caching
  and the offline queue move to the later offline phase.
- The host page refuses users without a Mobile Sales role; guests are sent to the login page.
- Printing through the browser print view; the Android ESC/POS hand-off is deferred until after v1.0.0
  (`get_receipt_escpos` already returns the receipt lines).
- The app is called "Mobile Sales" everywhere (header, installed-app name and short name); service worker
  cache v3 so installed phones drop the old shell.
- Shop Closed needs no reason (the field is hidden and cleared); remarks are optional. No Sale still needs a
  reason.
- New customer from the phone: customer group and territory pickers (defaults from Settings) and an optional
  route; the customer is appended to the end of that route. Mobile Route gets Is Active (default on); only
  active routes are offered. No Customer / Route permission changes.
- Off-route visits: agents can search, visit and invoice any customer. Customer Visit.off_route (read only)
  marks visits to customers not on the trip's route; History shows an "Off route" tag. Patch fills it for
  existing visits.
- Mobile Trip load items and the Top-up dialog fill UOM = stock UOM (conversion factor 1) when an item is
  chosen; the server defaults them when empty.
- Reopen Trip (Settling → In Field) for the trip's agent or a supervisor, from the Desk trip form and the
  Today screen: allowed with no settlement or a workflow Draft settlement (deleted); refused from Pending
  Store on (a supervisor rejects it to Draft first).
- Tests: never commit (frappe.db.commit raises inside every test, after a host-page test committed test
  data to the live site); nested `as_user` blocks now return to the previous user, so no API flow runs
  as Administrator. All test runs moved to the dedicated test site mstest.local. 91 tests; SPA mount test
  (vitest) covers every route plus the Reopen, Off route and new-customer screens.

## v0.4.1 — fixes from the live pilot

- Fix: collection of previous invoices by agents. ERPNext re-reads each referenced invoice as the
  session user; the visit now opens exactly the invoices it validated, for that request only. Agents
  still cannot list, open or search other invoices. The Previous Outstanding picker lists only the
  visit customer's submitted, outstanding invoices of the same company.
- Fix: supervisor visit cancel. Mobile Sales Supervisor gets read + print on Sales Invoice and Payment
  Entry (same Custom DocPerm mechanism, integrity- and drift-checked; no other role changed).
- Agents may delete their own draft Customer Visits; submitted and cancelled visits never.
- Tests now run every business flow as the real role user (agent, store keeper, cashier, supervisor,
  standard office user); Administrator only prepares test data (CLAUDE.md rule 13). 72 tests.

## v0.4.0 — Phase 4: End-of-day Settlement

- Mobile Settlement (MSET-.YY.-.#####, one per trip, only when the trip is Settling) with stock lines,
  batch drill-down, LKR cash denominations and a cheques table (recorded only, not posted yet).
- Reconciliation from the ledgers: issued / sold from the van's Stock Ledger for the trip's own
  vouchers, expected cash = opening float + cash Payment Entries on the agent cash account (GL);
  recomputed on every save. Van Bin vs ledger mismatch and excess counts block submit.
- Workflow "Mobile Settlement Approval": Draft → Pending Store → Pending Cashier → Approved, or
  Pending Approval (Supervisor) when |cash variance| + stock variance value exceeds the tolerance;
  Reject back to Draft from every pending state (clears the verifications); Cancel by Supervisor.
  Each state allows only its own fields (stock counts at the store, cash at the cashier).
- Submit postings in one transaction: Return / Damage / Shortage Stock Entries (batches allocated
  oldest first, named damaged batch honoured), cash hand-over and variance Journal Entries, optional
  recovery from the agent's Employee record; van and agent cash must end at zero. Cancel reverses
  everything and returns the trip to Settling.
- Guards: settlement-only Return / Damage / Shortage entries; no visits once a settlement exists;
  End Day requires every visit submitted.
- Print format: Mobile Settlement Sheet (A4) with signature lines.
- Fix: v0.3.0 could not sell batch items as an agent (nor load them as a store keeper): ERPNext creates
  Serial and Batch Bundles as the submitting user. The four Mobile Sales roles now have the bundle
  rights ERPNext gives its own stock roles (14 DocTypes with Custom DocPerm copies, drift-checked).
- Fix: agents who also hold Accounts / Sales roles keep the standard invoice, payment and visit scope.
- Tests: 66.

## v0.3.0 — Phase 3: Customer Visit, invoicing, collection

- Customer Visit (CV-.YY.-.######) with outcomes Sale / No Sale / Collection Only / Shop Closed and
  child tables for items, shelf stock, previous-invoice collections and customer changes.
- Visit totals come from an unsaved ERPNext Sales Invoice (pricing rules, taxes, rounding); the same
  builder creates the real invoice on submit. Manual line discount capped by the agent's limit.
- Submit: van stock re-checked under row lock, Sales Invoice (update_stock from the van, agent sales
  team, MB-SINV series, optional default tax template, FIFO batches) and one Payment Entry to the agent
  cash account covering the new invoice and selected previous invoices; batches shown per line.
- Credit rules: cash only, or up to the agent's per-invoice credit limit when credit sales are allowed.
- Customer updates (name, tax ID, contact, mobile, email, address) captured with old values; applied
  directly or approved / rejected by a supervisor.
- Cancel (supervisor, trip not settled): Payment Entry, then Sales Invoice; trip summary recomputed.
- Guards: mobile Sales Invoices and Payment Entries only from app code; payments only to the trip
  agent's cash account. Invoices and payments post at submit time.
- Sales Invoice naming series option MB-SINV-.YY.-.##### added without changing the default.
- Agent access: read on 10 masters, read + print own Sales Invoices / Payment Entries, select on
  Account, own Customer Visits only. Existing roles' permissions unchanged (Custom DocPerm copies);
  migrate warns if ERPNext's standard permissions later drift from those copies.
- Print formats: Mobile Invoice 4in, Mobile Collection Receipt (not default).
- Tests: 49.

## v0.2.0 — Phase 2: Mobile Trip and stock issue

- Mobile Trip (MTRIP-.YY.-.#####): load items with UOM conversion and source availability, one open
  trip per agent, empty-van check, issue Stock Entry on submit (batches auto-picked FIFO), optional
  opening cash float Journal Entry (agent cash Dr / main cash Cr), status list indicators.
- Child DocTypes Mobile Trip Load Item and Mobile Trip Stock Entry.
- Status actions: Start Trip, End Day (agent or supervisor), Top-up Load (supervisor / store keeper).
- Cancel only from Loaded with no submitted visits; reverses the float JE and all trip Stock Entries.
- Guards: mobile Stock Entries and Journal Entries must come from app code; Stock Entry purpose must
  match trip status and use only the trip van; mobile Sales Invoices only in In Field on the trip van
  and not cancellable once Settled; mobile Payment / Journal Entries blocked on Settled trips.
- Settings reject a root van group, a van group containing source/return/damage warehouses, or one
  holding stocked non-agent warehouses.
- Agents read only their own Mobile Trips (list, form and API).
- API: get_context, get_van_stock (with batch-wise qty); Van Stock view on the trip form.
- Customer Visit stub gets mobile_trip.
- Tests: 31 (foundation + trip).

## v0.1.0 — Phase 1: foundation

- DocTypes: Mobile Sales Settings (Single), Mobile Sales Agent, Mobile Route + Mobile Route Customer,
  Visit No Sale Reason.
- Minimal submittable stubs for Mobile Trip, Customer Visit and Mobile Settlement (agent link only);
  extended in Phases 2–4.
- Roles (fixtures): Mobile Sales Agent, Store Keeper, Cashier, Supervisor.
- Custom fields (fixtures) on Sales Invoice, Payment Entry, Stock Entry and Journal Entry in a collapsed
  "Mobile Sales" section shown only when `mobile_trip` is set.
- Agent setup action "Create Van Warehouse & Cash Account": van warehouse, numbered cash ledger,
  Mode of Payment, Sales Person, User Permissions and role. Idempotent.
- Agents can read only their own Mobile Sales Agent record.
- Guard hooks: van warehouses and agent cash accounts are rejected on Sales Invoice, Delivery Note,
  Stock Reconciliation, Stock Entry, Payment Entry and Journal Entry without a Mobile Trip.
- Default Visit No Sale Reasons created on install and migrate.
- Foundation tests (11).

## v0.0.1 — scaffold
