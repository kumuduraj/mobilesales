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
