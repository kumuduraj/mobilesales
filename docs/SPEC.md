# Mobile Sales — ERPNext v16 Custom App Spec

Nov 1, 2026 · @Raj

> App name in the repo is `mobilesales`. Wherever this spec says `mobile_sales`, read `mobilesales`.

## 1. Scope and constraints

Build a new Frappe app `mobile_sales` (module **Mobile Sales**) on ERPNext v16 that runs van/route selling end to end: stock issue → customer visits → invoice + collection → end-of-day settlement → performance reporting. Every financial and stock movement is a standard ERPNext document (Stock Entry, Sales Invoice, Payment Entry, Journal Entry); the app only adds orchestration DocTypes, custom fields, hooks, a mobile UI and reports.

**Hard rules**

- Zero edits to `frappe` / `erpnext` source. Extension only via `hooks.py` (`doc_events`, `permission_query_conditions`, `has_permission`), fixtures (Custom Field, Role, Workflow) and whitelisted APIs. No `override_doctype_class`.
- Standard sales flow untouched: every hook on a standard DocType exits immediately when `doc.mobile_trip` is empty.
- Separation is enforced, not assumed: van warehouses and agent cash accounts are blocked from use by non-mobile documents (see §5.2).
- Ledgers are the source of truth. Reconciliation reads Stock Ledger Entry and GL Entry, never denormalised counters.
- One open Mobile Trip per agent at a time.

**Out of scope (phase 2 candidates):** full offline sync, customer sales returns from the van, GPS route tracking between visits, multi-currency.

## 2. Architecture

Each agent gets a dedicated van warehouse and a dedicated cash-in-hand ledger; mobile stock and cash can only move through documents tagged with a Mobile Trip, so the main store, main cash and standard sales never mix with field activity.

Flow: Mobile Trip (Stock Entry store → van) → Customer Visit (GPS, details, shelf qty) → Sale? yes → Sales Invoice (update_stock from van) → Payment Entry (into agent cash ledger) → next customer; no → No-sale visit (reason, no invoice) → next customer. End of day: Mobile Trip → Mobile Settlement (reconcile stock + cash) → on approval → Ledger postings (Stock Entries for returns, Journal Entries for cash).

A trip loads the van, every stop is a Customer Visit (sale or no sale), and the settlement reconciles the ledgers and empties the van and agent cash back to zero.

| Need | Standard ERPNext object used | App adds |
| --- | --- | --- |
| Stock issue to salesperson | Stock Entry (Material Transfer) store → van warehouse | Mobile Trip orchestration |
| Billing | Sales Invoice, `update_stock=1`, warehouse = van | Created from Customer Visit |
| Pricing, schemes, taxes, credit limit | Price List, Pricing Rule, Tax Template, Customer credit limit | Nothing — reused as-is |
| Payment collection | Payment Entry (Receive) to agent cash account | Created from Customer Visit |
| Customer master changes | Customer, Contact, Address | Change capture + optional approval |
| Customer shelf stock | — (not company stock) | Child table on visit, no ledger impact |
| Returns / damage / shortage | Stock Entry (Transfer / Issue) | Created by Mobile Settlement |
| Cash hand-over / variance | Journal Entry | Created by Mobile Settlement |
| Commission | Sales Team on invoice | Filled from agent's Sales Person |

## 3. Masters and setup

Five small masters plus a per-agent warehouse and cash ledger. All created once per agent by a setup action on **Mobile Sales Agent**.

### 3.1 Mobile Sales Settings (Single)

| Field | Type | Purpose |
| --- | --- | --- |
| company | Link Company | Default company |
| source_warehouse | Link Warehouse | Main FG store stock is issued from |
| van_warehouse_group | Link Warehouse (is_group) | Parent of all van warehouses, e.g. `Mobile Vans - XX` |
| return_warehouse | Link Warehouse | Where unsold stock lands at settlement (default = source) |
| damage_warehouse | Link Warehouse | Quarantine for damaged returns |
| stock_shortage_account | Link Account (Expense) | Write-off for missing stock |
| cash_shortage_account | Link Account (Expense) | Cash variance write-off |
| main_cash_account | Link Account (Cash) | Company cashier ledger receiving hand-over |
| recover_shortage_from_agent | Check | If set, shortages post to Employee receivable instead of expense |
| shortage_tolerance_value | Currency | Variance below this auto-writes-off; above needs Supervisor |
| apply_customer_updates_directly | Check | Off = changes go to supervisor approval |
| require_geolocation | Check | Block visit save without lat/long |
| allow_credit_sales | Check | Allow invoice with outstanding > 0 |
| sinv_naming_series | Data | e.g. `MB-SINV-.YY.-.#####` |
| default_tax_template | Link Sales Taxes and Charges Template | Applied on mobile invoices |
| agent_cash_parent_account | Link Account (group, Cash) | Parent for auto-created agent cash ledgers |
| sales_person_parent | Link Sales Person (group) | Parent for auto-created Sales Persons |

### 3.2 Mobile Sales Agent

One record per field salesperson. Autoname `MSA-.####`.

| Field | Type | Notes |
| --- | --- | --- |
| user | Link User (unique) | Login used on the device |
| employee | Link Employee | For shortage recovery |
| sales_person | Link Sales Person | Written into `sales_team` for commission |
| van_warehouse | Link Warehouse (read only) | Auto-created under van group |
| cash_account | Link Account (read only) | Auto-created `Cash in Hand - <agent>` under Cash In Hand |
| mode_of_payment | Link Mode of Payment | Agent-specific MoP whose company account = cash_account |
| selling_price_list | Link Price List | |
| default_route | Link Mobile Route | |
| max_discount_pct | Percent | Line discount ceiling |
| credit_limit_per_invoice | Currency | 0 = cash only |
| is_active | Check | |

**Setup button** `Create Van Warehouse & Cash Account`: creates Warehouse, Account, Mode of Payment row, and a User Permission (user → own Mobile Sales Agent, apply to all doctypes = off, applicable_for Mobile Trip / Customer Visit / Mobile Settlement).

### 3.3 Mobile Route

`route_name`, `territory`, child **Mobile Route Customer** (`customer`, `sequence`, `visit_frequency` Select Daily/Weekly/Fortnightly, `visit_day` Select Mon–Sun). Drives planned visits and route coverage.

### 3.4 Visit No Sale Reason

Simple master: `reason` (Data, unique), `category` Select (Stock Sufficient / Price / Credit Issue / Shop Closed / Competitor / Owner Absent / Other), `requires_remark` Check.

### 3.5 Accounts and warehouses to seed

- Warehouse group `Mobile Vans - XX`; one leaf per agent.
- Warehouse `Damaged Returns - XX`.
- Accounts: `Cash in Hand - <agent>` (Cash, per agent), `Mobile Stock Shortage` (Expense), `Mobile Cash Shortage / Excess` (Expense).
- Stock Settings: `allow_negative_stock` must stay off; the app also validates van stock itself.

## 4. Core DocTypes

Three submittable DocTypes carry the process: **Mobile Trip** (one agent-day), **Customer Visit** (one stop), **Mobile Settlement** (closes the trip). Plus custom fields on four standard DocTypes.

**One app, one module.** Mobile Trip, Customer Visit and Mobile Settlement are DocTypes inside the single `mobile_sales` app, not separate apps. Customer Visit is the agent's working screen during the day; it creates the Sales Invoice and Payment Entry itself.

### 4.1 Mobile Trip (submittable, `MTRIP-.YY.-.#####`)

| Field | Type | Notes |
| --- | --- | --- |
| agent | Link Mobile Sales Agent | reqd |
| trip_date | Date | reqd, default Today |
| company | Link Company | from Settings |
| route | Link Mobile Route | default from agent |
| van_warehouse | Link Warehouse | fetch from agent, read only |
| source_warehouse | Link Warehouse | default from Settings |
| opening_cash_float | Currency | Change given to agent; posted by JE main cash → agent cash |
| status | Select | Draft / Loaded / In Field / Settling / Settled / Cancelled (read only, set by code) |
| load_items | Table **Mobile Trip Load Item** | item_code, uom, conversion_factor, qty, stock_qty, batch_no, available_at_source (read only) |
| stock_entries | Table **Mobile Trip Stock Entry** (read only) | stock_entry, purpose (Issue / Top-up / Return / Damage / Shortage), posting_datetime |
| settlement | Link Mobile Settlement | read only |
| summary section (read only, refreshed on demand) | Int/Currency | visits, sales_visits, no_sale_visits, invoices, invoiced_amount, collected_amount |

On **submit**: creates Stock Entry (Material Transfer, source → van) from `load_items`, `mobile_trip` set, submitted; status → Loaded. Agent taps **Start Trip** → In Field. Button **Top-up Load** (Supervisor) opens a dialog of items/qty and creates another Material Transfer. Validation: van warehouse must hold zero stock before first issue (previous trip fully settled).

### 4.2 Customer Visit (submittable, `CV-.YY.-.######`)

| Field | Type | Notes |
| --- | --- | --- |
| mobile_trip | Link Mobile Trip | reqd, filter status = In Field, agent = session agent |
| agent | Link Mobile Sales Agent | fetch |
| customer | Link Customer | reqd |
| visit_datetime | Datetime | default now |
| latitude / longitude | Float | captured by device |
| check_in_photo | Attach Image | optional |
| outcome | Select | Sale / No Sale / Collection Only / Shop Closed |
| no_sale_reason | Link Visit No Sale Reason | mandatory_depends_on outcome in (No Sale, Shop Closed) |
| remarks | Small Text | mandatory if reason.requires_remark |
| **Customer update** section | | `update_customer` Check; `new_customer_name`, `new_mobile_no`, `new_email`, `new_address_line1`, `new_city`, `new_contact_person`, `new_tax_id` |
| customer_update_status | Select | Not Requested / Applied / Pending Approval / Rejected |
| shelf_stock | Table **Customer Visit Shelf Stock** | item_code, qty_on_shelf, uom, expiry_date, competitor_item (Data), remarks |
| sale_items | Table **Customer Visit Item** | item_code, uom, qty, price_list_rate, discount_percentage, rate, amount, available_in_van (read only) |
| net_total / taxes / grand_total | Currency | computed client + server via a draft Sales Invoice `run_method('calculate_taxes_and_totals')`, so pricing rules and schemes match ERPNext exactly |
| collect_amount | Currency | collected now against this invoice |
| collect_previous | Table **Customer Visit Collection** | sales_invoice (outstanding of this customer), outstanding, allocated |
| total_collected | Currency | computed |
| sales_invoice / payment_entry | Link | read only, set on submit |
| customer_signature | Signature | optional |

**Customer Visit Change** (child table, filled on save when `update_customer` is ticked): `field_label`, `old_value`, `new_value`, `status` (Applied / Pending Approval / Rejected). Old values are read from Customer / Contact / Address before writing, so the day report can show before → after.

### 4.3 Mobile Settlement (submittable, `MSET-.YY.-.#####`, one per trip)

| Field | Type | Notes |
| --- | --- | --- |
| mobile_trip | Link Mobile Trip (unique) | reqd |
| agent, trip_date, van_warehouse | fetch | |
| total_visits, sales_visits, no_sale_visits, collection_only_visits | Int | computed |
| invoice_count, invoiced_amount, cash_sales_amount, credit_sales_amount | Int / Currency | computed |
| collected_current, collected_previous, total_collected | Currency | computed from Payment Entries |
| stock_lines | Table **Mobile Settlement Item** | see below |
| expected_cash | Currency | opening_cash_float + cash collections |
| denominations | Table **Mobile Cash Denomination** | denomination, count, amount (optional; drives cash_handed_over) |
| cash_handed_over | Currency | reqd |
| cheques_handed_over | Table | payment_entry, cheque_no, amount (for non-cash MoP) |
| cash_variance | Currency | handed − expected (negative = short) |
| stock_variance_value | Currency | Σ missing_qty × valuation_rate |
| variance_action | Select | Write Off / Recover from Agent (default from Settings) |
| verified_by_store, verified_by_cashier | Link User | set by workflow |
| return_entry, damage_entry, shortage_entry, cash_journal, variance_journal | Link | read only, created on submit |

**Mobile Settlement Item** (one row per item ever loaded on the trip):

| Column | Source |
| --- | --- |
| item_code, uom | trip ledger |
| issued_qty | Σ SLE in van from trip Stock Entries (Issue + Top-up) |
| sold_qty | Σ −SLE in van from submitted mobile Sales Invoices of trip |
| expected_balance | issued − sold (= actual van Bin qty, cross-checked) |
| returned_qty | entered (store counts physically) |
| damaged_qty | entered |
| missing_qty | expected_balance − returned − damaged (read only) |
| excess_qty | if negative missing, shown separately; blocks submit |
| valuation_rate, missing_value | from Bin |

### 4.4 Custom fields on standard DocTypes (fixtures)

| DocType | Fields |
| --- | --- |
| Sales Invoice | `mobile_trip` (Link, read only, no_copy), `customer_visit` (Link, read only, no_copy), `is_mobile_sale` (Check, read only) |
| Payment Entry | `mobile_trip`, `customer_visit` (Link, read only, no_copy) |
| Stock Entry | `mobile_trip` (Link, read only, no_copy), `mobile_purpose` (Select) |
| Journal Entry | `mobile_trip`, `mobile_settlement` (Link, read only, no_copy) |

All inserted after an existing field via `insert_after`, in a collapsed section, `depends_on: eval:doc.mobile_trip` so normal users never see them.

## 5. Business logic

All document creation runs server-side in one DB transaction per user action; a failure rolls back the visit and any half-made invoice or payment.

### 5.1 Customer Visit submit

1. Validate: trip status = In Field; `frappe.session.user` = trip.agent.user (Supervisor bypass); visit_datetime within trip_date; geolocation present if Settings require it.
2. Outcome **No Sale / Shop Closed**: require reason; reject non-empty `sale_items`.
3. Outcome **Sale**: `sale_items` mandatory. For each line, check `qty × conversion_factor ≤ actual_qty` in van Bin (reads `tabBin` with `for update` to stop two parallel visits overselling).
4. Apply customer updates: if `apply_customer_updates_directly` → update Customer (`customer_name`, `mobile_no`, `email_id`, `tax_id`), the primary Contact and primary Billing Address (create if missing) → status Applied. Else status Pending Approval; Supervisor action `Approve Customer Update` applies it later. Frappe Version log keeps history.
5. Shelf stock rows saved as-is (no stock ledger impact; customer stock is not company stock).
6. Create Sales Invoice: `customer`, `company`, `posting_date` = visit date, `set_posting_time=1`, `update_stock=1`, `set_warehouse` = van, `selling_price_list` = agent's, `naming_series` from Settings, `taxes_and_charges` default, `sales_team` = [agent.sales_person 100%], `mobile_trip`, `customer_visit`, `is_mobile_sale=1`; items from `sale_items` with `warehouse` = van. Run `set_missing_values()` → `calculate_taxes_and_totals()` → `insert()` → `submit()`. Standard credit-limit and pricing-rule checks run untouched.
7. If `allow_credit_sales` off → require `collect_amount = grand_total`. Else enforce `grand_total − collect_amount ≤ agent.credit_limit_per_invoice`.
8. Collections: one Payment Entry (Receive, party Customer, `mode_of_payment` = agent MoP, `paid_to` = agent cash account, `reference_no` = visit name) allocating `collect_amount` to the new invoice plus each `collect_previous` row to its invoice. Use `erpnext.accounts.doctype.payment_entry.payment_entry.get_payment_entry` per invoice for the first allocation, then append references. Submit.
9. Write back `sales_invoice`, `payment_entry` to the visit (`db_set`).

**Visit cancel** (Supervisor only, trip not Settled): cancel Payment Entry, then Sales Invoice (stock returns to van automatically), then the visit.

### 5.2 Guard hooks on standard DocTypes (`doc_events`)

| DocType.event | Rule |
| --- | --- |
| Sales Invoice.validate | If no `mobile_trip` and any item warehouse is a child of the van group → throw. If `mobile_trip` set → warehouse must equal trip van; trip must not be Settled. |
| Sales Invoice.before_cancel | If `mobile_trip` and trip Settled → throw (reverse via settlement amendment only). |
| Delivery Note / Stock Entry / Stock Reconciliation.validate | Van warehouse allowed only when `mobile_trip` set (Stock Entry) or never (DN, Stock Reco). |
| Payment Entry.validate | `paid_to` = any agent cash account and no `mobile_trip` → throw. |
| Journal Entry.validate | Agent cash account line without `mobile_trip` → throw unless user has Mobile Sales Supervisor. |

Every handler opens with `if not doc.get("mobile_trip") and not _touches_mobile(doc): return` — a cached set of van warehouses and cash accounts makes the check O(1). This is the only code path that runs for standard sales.

### 5.3 Reconciliation formulas

```
expected_balance(i) = issued(i) - sold(i)
missing(i)          = expected_balance(i) - returned(i) - damaged(i)
expected_cash       = opening_float + sum(Payment Entries, cash MoP, trip)
cash_variance       = cash_handed_over - expected_cash
```

Issued and sold come from Stock Ledger Entry filtered by `warehouse = van` and `voucher_no` in the trip's Stock Entries / Sales Invoices. `expected_balance` must also equal the van Bin `actual_qty`; a mismatch means a document bypassed the guards and blocks submit. Collections come from GL Entry on the agent cash account with `voucher_type = Payment Entry` for the trip, so cash posted by any route is caught.

### 5.4 Settlement submit — ledger postings

| # | Document | Lines |
| --- | --- | --- |
| 1 | Stock Entry (Material Transfer, purpose Return) | van → return_warehouse, `returned_qty` |
| 2 | Stock Entry (Material Transfer, purpose Damage) | van → damage_warehouse, `damaged_qty` |
| 3 | Stock Entry (Material Issue, purpose Shortage) | from van, `missing_qty`, expense_account = stock_shortage_account (or Employee receivable via JE if recover) |
| 4 | Journal Entry (cash hand-over) | Dr main_cash_account / Cr agent cash = `cash_handed_over` |
| 5 | Journal Entry (variance), only if ≠ 0 | Short: Dr cash_shortage_account or Employee (party) / Cr agent cash. Excess: reverse. |
| 6 | Cheques | Optional Payment Entry Internal Transfer agent cash → bank-in-transit per cheque |

Post-conditions checked before commit: van Bin qty = 0 for all items; agent cash account balance = 0. Then trip status → Settled, settlement linked.

**Variance gate:** `|cash_variance| + stock_variance_value > shortage_tolerance_value` → workflow needs Supervisor approval before submit.

**Cancel settlement** (Supervisor): cancels 5 → 1 in reverse, trip back to Settling.

### 5.5 Trip status machine

Draft → (submit, stock issued) Loaded → (Start Trip) In Field → (End Day: no more visits) Settling → (settlement submit) Settled. Cancel allowed only from Loaded with no visits; it cancels the issue Stock Entry.

### 5.6 Batch-tracked items

Batches flow through standard ERPNext v16 Serial and Batch Bundles; the app never picks batches by hand except at settlement return.

- **Prerequisite (validated on Settings save):** Stock Settings `auto_create_serial_and_batch_bundle_for_outward` = 1 and `pick_serial_and_batch_based_on` = FIFO (or FEFO when expiry is used).
- **Issue / top-up:** Material Transfer store → van with bundles auto-created FIFO from the source warehouse.
- **Sale:** Sales Invoice items from the van get bundles auto-created FIFO from the van; the visit line shows the batch(es) picked after submit.
- **Settlement return:** returned qty is allocated to the batches actually left in the van (batch-wise balance from Stock Ledger), oldest first, with explicit bundles on the return Stock Entry.
- **Damaged:** optional `batch_no` per damaged line (store can identify the batch); if blank, allocated oldest first.
- **Missing:** always allocated oldest first.
- **Reconciliation:** item level as in §5.3, plus a batch drill-down (issued / sold / returned / damaged / missing per batch). Post-condition: zero batch balance in van.

## 6. Mobile UI, APIs, printing, permissions

Agents use a phone-first SPA at `/mobile-sales`; supervisors, store and cashier use normal Desk forms. Desk forms stay fully functional on phones as fallback.

### 6.1 Mobile SPA

Vue 3 + `frappe-ui` built into `mobile_sales/public/frontend`, served by `www/mobile-sales.py` (login required, role Mobile Sales Agent). Installable PWA (manifest + service worker caching app shell, item master and route customers).

| Screen | Content |
| --- | --- |
| Today | Current trip status, van stock list with live qty, KPIs (visits, sales, collected), Start Trip / End Day |
| Route | Planned customers for the day in sequence, visited ticks, search any customer, add new customer (quick-entry) |
| Visit | Step 1 check-in (GPS + photo) → Step 2 customer details edit → Step 3 shelf stock count → Step 4 outcome: No Sale (reason) or Sale (cart from van stock) → Step 5 collection (current + previous outstanding) → Submit → Print |
| History | Today's visits, reprint invoice/receipt |
| Settlement | Pre-filled reconciliation, agent enters returned/damaged counts and cash denominations, submits for verification |

**Offline (phase 2):** IndexedDB queue of draft visits keyed by a client UUID (`client_ref` unique field on Customer Visit) so replays are idempotent; stock re-validated server-side on sync.

### 6.2 Whitelisted API (`mobile_sales/api/mobile.py`)

| Method | Purpose |
| --- | --- |
| `get_context()` | Agent, open trip, settings flags, price list |
| `get_van_stock(trip)` | Item, uom, actual_qty, rate, image |
| `get_route_plan(trip)` | Route customers + visited flag + outstanding |
| `get_customer(customer)` | Details, primary contact/address, outstanding invoices, last shelf stock |
| `price_cart(trip, customer, items)` | Builds unsaved Sales Invoice, returns totals/taxes/pricing-rule results |
| `submit_visit(payload)` | Creates + submits Customer Visit (and SI/PE); idempotent on `client_ref` |
| `start_trip(trip)` / `end_day(trip)` | Status transitions |
| `get_settlement_draft(trip)` | Computed reconciliation |
| `submit_settlement(payload)` | Saves settlement, moves workflow to Pending Verification |

Every method resolves the agent from `frappe.session.user`; trip/customer arguments are re-checked against it.

### 6.3 Printing

Print Format **Mobile Invoice 4in** (Jinja, Sales Invoice, 4-inch thermal) and **Mobile Collection Receipt** (Payment Entry). The Visit screen hands the rendered invoice to the existing Evonet Android ESC/POS print service (`lk.evonet.escposprint`) for Bluetooth printing; browser print as fallback. Settlement Print Format **Mobile Settlement Sheet** (A4) with signature lines for agent, store keeper, cashier.

### 6.4 Roles and permissions

| Role | Mobile Trip | Customer Visit | Mobile Settlement | Notes |
| --- | --- | --- | --- | --- |
| Mobile Sales Agent | Read own | Create/Submit own | Create own, cannot submit | `permission_query_conditions` → own agent only |
| Mobile Sales Store Keeper | Read | Read | Write returned/damaged qty, verify | |
| Mobile Sales Cashier | Read | Read | Write cash fields, verify | |
| Mobile Sales Supervisor | Full, submit, cancel | Cancel, approve customer updates | Approve variance, submit, cancel | |

Agents get Read only (for reprint) on Sales Invoice / Payment Entry, scoped by `permission_query_conditions` to `mobile_trip` in own trips; creation happens under `ignore_permissions` inside the visit submit only, so agents cannot raise standalone invoices.

### 6.5 Settlement workflow (fixture)

| State | Doc status | Allowed by | Next |
| --- | --- | --- | --- |
| Draft | 0 | Agent | Submit for Verification → Pending Store |
| Pending Store | 0 | Store Keeper | Verify Stock → Pending Cashier; Reject → Draft |
| Pending Cashier | 0 | Cashier | Verify Cash → Pending Approval (variance over tolerance) or Approved |
| Pending Approval | 0 | Supervisor | Approve → Approved; Reject → Draft |
| Approved | 1 | Cashier / Supervisor | — (submit posts ledgers) |
| Cancelled | 2 | Supervisor | — |

## 7. Reports and dashboard

All Script Reports read Customer Visit, Mobile Settlement and the standard ledgers; filters company, date range, agent, route, territory unless noted.

| Report | Grain | Key columns |
| --- | --- | --- |
| **Salesperson Performance** | Agent × period | trips, working days, visits, planned visits, route coverage %, sales visits, strike rate % (sales ÷ visits), invoices, net sales, avg invoice value, lines per invoice, collections, collection % of sales, credit sales, returns % of issued, damage %, stock shortage value, cash variance, sales per day |
| Daily Trip Summary | Trip | issued value, sold value, returned, damaged, missing, invoiced, collected, handed over, variance, settlement status |
| Customer Visit Register | Visit | datetime, agent, customer, outcome, reason, invoice, amount, collected, GPS link |
| No Sale Reason Analysis | Reason × agent/territory | count, % of visits; chart by category |
| Customer Stock Position | Customer × item | latest shelf qty, date counted, days since last visit, last purchase qty — feeds next-load planning |
| Route Coverage | Route × customer | planned vs visited by day, missed customers |
| Mobile Stock Variance | Agent × item | issued, sold, returned, damaged, missing qty and value over period |
| Mobile Cash Variance | Agent × trip | expected, handed, variance, action (write-off/recovered) |
| Outstanding by Agent | Agent × customer | credit invoices raised by agent still outstanding, ageing buckets |

**Workspace "Mobile Sales"**: shortcuts (Trip, Visit, Settlement, Agent, Route), Number Cards (Open Trips, Today's Visits, Today's Mobile Sales, Today's Collections, Pending Settlements, Today's Cash Variance), Dashboard Charts (Mobile sales by agent — bar, last 30 days; Strike rate trend — line; No-sale reasons — donut).

Standard reports keep working: filter Sales Register / Accounts Receivable by `is_mobile_sale` or `mobile_trip` to split mobile from standard sales.

### 7.1 End-of-Day Trip Report

One report per trip covering every visit, customer update, sale, collection and stock movement. Built as a Script Report **Mobile Trip Day Report** (filter: Mobile Trip) plus an A4 Print Format on Mobile Settlement with the same sections. Live during the day on the agent's Today screen; on settlement submit the PDF is rendered and attached to the settlement, so the signed version never changes.

| # | Section | Rows / columns | Source |
| --- | --- | --- | --- |
| 1 | Header | agent, date, route, trip, first and last visit time, settlement status | Mobile Trip |
| 2 | Day KPIs | planned visits, visited, missed, sales visits, no-sale visits, strike rate %, invoices, net sales, collected, credit given | Customer Visit, SI, PE |
| 3 | Visit log | time, customer, outcome, no-sale reason, remarks, invoice, amount, collected, GPS map link | Customer Visit |
| 4 | Missed customers | route customers planned today with no visit | Mobile Route vs Customer Visit |
| 5 | Customer updates | customer, field, old value → new value, status | Customer Visit Change |
| 6 | Customer shelf stock | customer × item qty on shelf, expiry, competitor item | Customer Visit Shelf Stock |
| 7 | Sales by invoice | invoice, customer, net, tax, grand total, paid, outstanding | Sales Invoice (mobile_trip) |
| 8 | Sales by item | item, qty, uom, amount, avg rate, discount | Sales Invoice Item |
| 9 | Collections | payment entry, customer, against today's / previous invoice, mode, amount | Payment Entry |
| 10 | Stock reconciliation | item, issued, top-up, sold, returned, damaged, missing, missing value | §5.3 query |
| 11 | Cash reconciliation | opening float, cash collected, expected, handed over, variance, denominations, cheques | Mobile Settlement |
| 12 | Sign-off | agent, store keeper, cashier, supervisor with date/time from workflow | Workflow log |

Exports: Excel from the Script Report; PDF from the print format. A scheduled email (daily 20:00) sends the day's reports for all settled trips to Mobile Sales Supervisors.

## 8. App structure, build phases, acceptance tests

### 8.1 Layout

```
mobile_sales/
├── hooks.py                      # doc_events, permission_query_conditions, fixtures, website_route_rules
├── fixtures/                     # custom_field.json, role.json, workflow*.json, print_format.json, workspace.json
├── mobile_sales/doctype/
│   ├── mobile_sales_settings/
│   ├── mobile_sales_agent/
│   ├── mobile_route/  mobile_route_customer/
│   ├── visit_no_sale_reason/
│   ├── mobile_trip/  mobile_trip_load_item/  mobile_trip_stock_entry/
│   ├── customer_visit/  customer_visit_item/  customer_visit_shelf_stock/  customer_visit_collection/  customer_visit_change/
│   └── mobile_settlement/  mobile_settlement_item/  mobile_cash_denomination/  mobile_settlement_cheque/
├── mobile_sales/report/          # 9 script reports + Mobile Trip Day Report (§7)
├── services/
│   ├── stock.py                  # van stock read/lock, stock entry builders
│   ├── invoicing.py              # SI + PE builders
│   ├── customer_update.py
│   ├── reconciliation.py         # §5.3 queries
│   └── settlement.py             # §5.4 postings
├── overrides/guards.py           # §5.2 handlers (functions, not class overrides)
├── api/mobile.py                 # §6.2
├── www/mobile-sales.py|html      # SPA host
├── public/frontend/              # built Vue 3 + frappe-ui output (source in /frontend)
├── setup/install.py              # after_install: default reasons
└── tests/
```

`hooks.py` essentials: `fixtures` filtered explicitly by name; `doc_events` for Sales Invoice, Payment Entry, Stock Entry, Journal Entry, Delivery Note, Stock Reconciliation (validate, before_cancel only); `permission_query_conditions` for the three core DocTypes + Sales Invoice + Payment Entry (agents only, returns `""` for every other role); `website_route_rules = [{"from_route": "/mobile-sales/<path:app_path>", "to_route": "mobile-sales"}]`.

### 8.2 Build phases

1. **Foundation** — app scaffold, Settings, Agent (+ setup button), Route, No Sale Reason, custom-field fixtures, roles, guard hooks with tests proving standard SI/PE paths unchanged.
2. **Trip + stock issue** — Mobile Trip, issue/top-up Stock Entries, status machine, van stock API.
3. **Customer Visit** — Desk form first: outcomes, customer update, shelf stock, SI + PE creation, cancel chain, 4-inch print formats.
4. **Settlement** — reconciliation service, settlement form, workflow, ledger postings, post-condition checks, settlement sheet.
5. **Mobile SPA** — screens in §6.1 on top of the API, PWA shell, ESC/POS print hand-off.
6. **Reports + workspace** — §7.
7. **Phase 2** — offline queue, customer sales returns (credit note into damage/return warehouse from a visit), GPS track.

### 8.3 Acceptance tests

- [ ] Standard Sales Invoice on main warehouse submits and cancels with no mobile hook side-effects.
- [ ] Standard Sales Invoice using a van warehouse is rejected.
- [ ] Trip submit moves exactly `load_items` qty to van; second open trip for same agent rejected.
- [ ] No Sale visit saves with reason, creates no SI/PE, updates Customer mobile_no when direct-update on.
- [ ] Sale visit: SI with `update_stock=1` from van, pricing rule applied, PE to agent cash, links written back.
- [ ] Overselling: two concurrent visits for the last 5 units — one fails.
- [ ] Credit sale blocked when `allow_credit_sales` off; allowed up to agent limit when on.
- [ ] Previous-outstanding collection allocates correctly across invoices.
- [ ] Settlement: issued 100, sold 70, returned 25, damaged 3 → missing 2; Return/Damage/Shortage entries post; van Bin = 0.
- [ ] Cash: float 2,000 + collections 48,500, handed 50,000 → variance −500 → JE to shortage (or Employee) and agent cash = 0.
- [ ] Variance above tolerance cannot pass without Supervisor.
- [ ] Visit cancel after settlement rejected; settlement cancel reverses all five postings.
- [ ] Agent A cannot read Agent B's trips, visits, invoices via list, report or API.
- [ ] Batch-tracked item: issue, sale, return and missing all allocate batches FIFO; van batch balance = 0 after settlement.

### 8.4 Open questions

- Batch-tracked items: resolved — present on agrosys, handled in §5.6.
- Customer sales returns needed in phase 1?
- Agent shortages: always recover from salary, or write off below tolerance?
- Is a vehicle/driver separate from the agent (one van, two people)?
