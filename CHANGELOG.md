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
