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
