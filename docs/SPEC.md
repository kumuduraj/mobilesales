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

**Out of scope (phase 2 candidates):** full offline sync, GPS route tracking between visits, multi-currency. (Customer returns moved into Phase 5b, §4.5.)

## 2. Architecture

Each vehicle gets a dedicated van warehouse (§3.6) and each agent a dedicated cash-in-hand ledger; mobile stock and cash can only move through documents tagged with a Mobile Trip, so the main store, main cash and standard sales never mix with field activity.

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
| returns_enabled | Check | Customer returns from the van (§4.5) on/off |
| customer_return_warehouse | Link Warehouse (leaf, not under the van group) | Where customer returns land (credit notes, `update_stock`); e.g. `Customer Returns - XX`. Required when returns_enabled |
| sret_naming_series | Data | Credit note series, e.g. `MB-SRET-.YY.-.#####` (added as a Sales Invoice series option, default unchanged) |

### 3.2 Mobile Sales Agent

One record per field salesperson. Autoname `MSA-.####`.

| Field | Type | Notes |
| --- | --- | --- |
| user | Link User (unique) | Login used on the device |
| employee | Link Employee | For shortage recovery |
| sales_person | Link Sales Person | Written into `sales_team` for commission |
| van_warehouse | Link Warehouse (read only) | **Legacy** (Phase 5b): kept for history; the van belongs to the vehicle (§3.6) |
| default_vehicle | Link Mobile Vehicle | Default for new trips |
| cash_account | Link Account (read only) | Auto-created `Cash in Hand - <agent>` under Cash In Hand |
| mode_of_payment | Link Mode of Payment | Agent-specific MoP whose company account = cash_account |
| selling_price_list | Link Price List | |
| default_route | Link Mobile Route | |
| max_discount_pct | Percent | Ceiling of the agent's total manual discount (lines + invoice) vs the price-list value, §5.1 |
| max_return_value_per_visit | Currency | Credit notes of one visit above this need a Supervisor; 0 = agent cannot take returns |
| credit_limit_per_invoice | Currency | 0 = cash only |
| is_active | Check | |

**Setup button** `Create Cash Account` (was `Create Van Warehouse & Cash Account`; the van warehouse moved to the vehicle): creates Account, Mode of Payment row, and a User Permission (user → own Mobile Sales Agent, apply to all doctypes = off, applicable_for Mobile Trip / Customer Visit / Mobile Settlement).

### 3.3 Mobile Route

`route_name`, `territory`, `is_active` (Check, default on; only active routes are offered in the app), child **Mobile Route Customer** (`customer`, `sequence`, `visit_frequency` Select Daily/Weekly/Fortnightly, `visit_day` Select Mon–Sun). Drives planned visits and route coverage.

### 3.4 Visit No Sale Reason

Simple master: `reason` (Data, unique), `category` Select (Stock Sufficient / Price / Credit Issue / Shop Closed / Competitor / Owner Absent / Other), `requires_remark` Check.

### 3.5 Accounts and warehouses to seed

- Warehouse group `Mobile Vans - XX`; one leaf per vehicle.
- Warehouse `Damaged Returns - XX`.
- Warehouse `Customer Returns - XX` (leaf, outside the van group) when returns are enabled.
- Accounts: `Cash in Hand - <agent>` (Cash, per agent), `Mobile Stock Shortage` (Expense), `Mobile Cash Shortage / Excess` (Expense).
- Stock Settings: `allow_negative_stock` must stay off; the app also validates van stock itself.

### 3.6 Mobile Vehicle (Phase 5b)

One record per van. Autoname `field:vehicle_no`.

| Field | Type | Notes |
| --- | --- | --- |
| vehicle_no | Data (unique) | Registration / fleet number, e.g. `VAN-01` |
| description | Data | |
| van_warehouse | Link Warehouse (read only) | Auto-created `<vehicle_no> Van - XX` under van_warehouse_group by the setup button |
| default_driver | Data | Optional, informational |
| is_active | Check | Inactive vehicles cannot start trips |

**Setup button** `Create Van Warehouse` (Supervisor / System Manager): creates the warehouse, idempotent.

Rules: a vehicle's van must be empty before a trip loads it; one open trip per vehicle and one per agent. The agent keeps the cash account (cash is personal, the van is not). Guards keep treating **every leaf under van_warehouse_group as a van**, whether linked to a vehicle, a legacy agent or nothing.

**Legacy patch** (refuses to run, with a clear message, while any Mobile Trip is not Settled or Cancelled): for each agent with a van_warehouse, create Mobile Vehicle `VAN-01`, `VAN-02`, … (agent order) whose van_warehouse is that existing warehouse (no stock or warehouse moved), set agent.default_vehicle, and set `vehicle` on that agent's historic trips. Agent.van_warehouse stays as data. Idempotent (a warehouse already linked to a vehicle is skipped). The vehicle is active only if the agent is (old test agents stay inactive).

Agents read Mobile Vehicle (the trip and Today screen show it); Supervisor full; Store Keeper read.

### 3.7 Mobile Return Reason (Phase 5b)

`reason` (Data, unique), `requires_remark` Check. Seeded on install / migrate: Damaged, Expired, Unsold / Slow-moving, Wrong Item, Other (requires remark).

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
| vehicle | Link Mobile Vehicle | reqd (Phase 5b), default agent.default_vehicle, active only |
| helper | Data | optional second person on the van |
| van_warehouse | Link Warehouse | = vehicle.van_warehouse, read only |
| source_warehouse | Link Warehouse | default from Settings |
| opening_cash_float | Currency | Change given to agent; posted by JE main cash → agent cash |
| status | Select | Draft / Loaded / In Field / Settling / Settled / Cancelled (read only, set by code) |
| load_items | Table **Mobile Trip Load Item** | item_code, uom, conversion_factor, qty, stock_qty, batch_no, available_at_source (read only). uom defaults to the item's stock UOM (conversion_factor 1) in the form, the Top-up dialog and on the server when left empty |
| stock_entries | Table **Mobile Trip Stock Entry** (read only) | stock_entry, purpose (Issue / Top-up / Return / Damage / Shortage), posting_datetime |
| settlement | Link Mobile Settlement | read only |
| summary section (read only, refreshed on demand) | Int/Currency | visits, sales_visits, no_sale_visits, invoices, invoiced_amount, collected_amount |

On **submit**: creates Stock Entry (Material Transfer, source → van) from `load_items`, `mobile_trip` set, submitted; status → Loaded. Agent taps **Start Trip** → In Field. Button **Top-up Load** (Supervisor) opens a dialog of items/qty and creates another Material Transfer. Validation: van warehouse must hold zero stock before first issue (previous trip fully settled); one open trip per agent and per vehicle (§3.6).

### 4.2 Customer Visit (submittable, `CV-.YY.-.######`)

| Field | Type | Notes |
| --- | --- | --- |
| mobile_trip | Link Mobile Trip | reqd, filter status = In Field, agent = session agent |
| agent | Link Mobile Sales Agent | fetch |
| customer | Link Customer | reqd; any customer, not only the route's |
| off_route | Check | read only; set on save: customer is not on the trip's route (no route = off route). History shows an "Off route" tag |
| visit_datetime | Datetime | default now |
| latitude / longitude | Float | captured by device |
| check_in_photo | Attach Image | optional |
| outcome | Select | Sale / No Sale / Collection Only / Shop Closed / Return Only (Phase 5b) |
| no_sale_reason | Link Visit No Sale Reason | shown and mandatory for outcome No Sale only; hidden and cleared for Shop Closed |
| remarks | Small Text | mandatory if reason.requires_remark (No Sale); optional for Shop Closed |
| **Customer update** section | | `update_customer` Check; `new_customer_name`, `new_mobile_no`, `new_email`, `new_address_line1`, `new_city`, `new_contact_person`, `new_tax_id` |
| customer_update_status | Select | Not Requested / Applied / Pending Approval / Rejected |
| shelf_stock | Table **Customer Visit Shelf Stock** | item_code, qty_on_shelf, uom, expiry_date, competitor_item (Data), remarks |
| sale_items | Table **Customer Visit Item** | item_code, uom, qty, price_list_rate, discount_percentage, discount_amount (Phase 5b: enter one, the other is computed), rate, amount, available_in_van (read only) |
| additional_discount_percentage / discount_amount | Percent / Currency | Phase 5b: optional invoice-level discount on **Net Total** (enter one); copied to the Sales Invoice fields of the same name with `apply_discount_on = Net Total` |
| net_total / taxes / grand_total | Currency | computed client + server via a draft Sales Invoice `run_method('calculate_taxes_and_totals')`, so pricing rules and schemes match ERPNext exactly |
| collect_amount | Currency | collected now against this invoice |
| collect_previous | Table **Customer Visit Collection** | sales_invoice (outstanding of this customer), outstanding, allocated |
| total_collected | Currency | computed |
| **Returns** section (Phase 5b) | | outcomes Sale, Collection Only, Return Only |
| return_items | Table **Customer Visit Return Item** | §4.5 |
| return_total | Currency | Σ credit note grand totals (computed through ERPNext like the sale) |
| credit_applied | Currency | credit set off against invoices in this visit (§4.5) |
| sales_invoice / payment_entry | Link | read only, set on submit |
| credit_notes | Small Text (read only) | credit note names created on submit |
| credit_journal | Link Journal Entry (read only) | credit set-off entry, §4.5 |
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

Cheques: recorded only; posting deferred until a cheque MoP is enabled for agents.

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

**Customer returns received** (Phase 5b, table **Mobile Settlement Return**, one row per item from the trip's submitted credit notes): item_code, uom, credited_qty (read only, from the credit notes' Stock Ledger in customer_return_warehouse), credited_damaged_qty (read only, the agent's "Damaged" condition, for information), received_qty and damaged_qty (Store Keeper enters at Pending Store; defaults received = credited, damaged = credited_damaged), missing_qty = credited − received (read only), valuation_rate, missing_value. damaged > received or received > credited blocks submit. missing_value adds to stock_variance_value (same tolerance gate). On submit:
- damaged_qty → Stock Entry (Material Transfer, mobile_purpose **Return Damage**) customer_return_warehouse → damage_warehouse;
- missing_qty → Stock Entry (Material Issue, mobile_purpose **Return Shortage**) from customer_return_warehouse to stock_shortage_account (or recovery from the agent, same rule as van shortage);
- good returns (received − damaged) stay in customer_return_warehouse; the store moves them with normal Stock Entries.
Batches follow the credit notes' batches (oldest first). Settlement cancel reverses these entries with the others. The Mobile Settlement Sheet gets the same section.

### 4.4 Custom fields on standard DocTypes (fixtures)

| DocType | Fields |
| --- | --- |
| Sales Invoice | `mobile_trip` (Link, read only, no_copy), `customer_visit` (Link, read only, no_copy), `is_mobile_sale` (Check, read only) |
| Payment Entry | `mobile_trip`, `customer_visit` (Link, read only, no_copy) |
| Stock Entry | `mobile_trip` (Link, read only, no_copy), `mobile_purpose` (Select) |
| Journal Entry | `mobile_trip`, `mobile_settlement` (Link, read only, no_copy) |

All inserted after an existing field via `insert_after`, in a collapsed section, `depends_on: eval:doc.mobile_trip` so normal users never see them.

Phase 5b: no new custom fields. Credit notes are Sales Invoices with the same three fields; the set-off Journal Entry uses `mobile_trip`; Stock Entry `mobile_purpose` gets options `Return Damage` and `Return Shortage`.

### 4.5 Customer returns (Phase 5b)

**Customer Visit Return Item**: item_code, item_name, uom, conversion_factor, stock_qty, qty, rate, amount (read only), against_invoice (Link Sales Invoice), sales_invoice_item (hidden: the original line), return_reason (Link Mobile Return Reason), condition (Select Resaleable / Damaged), remarks, batch_info (read only), credit_note (read only).

- **against_invoice** picker (`return_invoice_query`): this customer's submitted, non-return Sales Invoices of the company containing the item (mobile or standard). Optional, except for **batch items, where it is required**. The batch comes from the original invoice's bundle (ERPNext return logic: only batches sold on that line, less what was already returned).
- **qty** ≤ sold on that line − already returned (ERPNext's own return validation). Without an invoice: any stock item of the price list.
- **rate**: the original line's net rate (after its invoice discount); without an invoice the price-list rate. Read only.
- Returns need `returns_enabled`; a reason with `requires_remark` needs remarks.
- **Limit**: return_total > agent.max_return_value_per_visit → rejected "needs a supervisor"; 0 means the agent cannot take returns at all. A Supervisor can submit the visit (Desk).
- **Return Only** outcome: return lines required, no sale; previous-invoice collections allowed. Return lines are also allowed with Sale and Collection Only; never with No Sale / Shop Closed.

**On visit submit**, after the sale invoice and before the Payment Entry:

1. One credit note per against_invoice, plus one without return_against for lines without an invoice: Sales Invoice `is_return=1`, `return_against`, `update_stock=1`, `set_warehouse = customer_return_warehouse`, series `sret_naming_series`, `mobile_trip`, `customer_visit`, `is_mobile_sale=1`, same price list, tax template and sales team as a sale. Built from ERPNext's `make_sales_return` mapper (per original invoice) trimmed to the returned lines, so batches, taxes and return validation are ERPNext's. `update_outstanding_for_self = 1` (v16 default): every credit note carries its own negative outstanding.
2. **Credit set-off — never cash.** One Journal Entry, voucher type **Credit Note**, built exactly like ERPNext's Payment Reconciliation (`reconcile_dr_cr_note`): only receivable-account lines, Dr against the credit note / Cr against the invoice it settles. Credit is applied in this order until used up: (a) the credit note's own against_invoice if still outstanding, (b) today's sale, (c) the previous invoices selected in collect_previous. The Payment Entry then covers only the cash still due. Credit left over stays on the customer account as the credit note's outstanding (visible in Accounts Receivable; the office applies it with Payment Reconciliation). It is **not** applied automatically at later visits; `get_customer` and the SPA customer card show it as **credit available**.
   - *Why this mechanism:* v16 offers three standard ways. (i) `update_outstanding_for_self = 0` only works against the return_against invoice and only while it has outstanding ≥ the credit (ERPNext flips it otherwise). (ii) Negative Payment Entry references fail when the credit is ≥ the money due ("Cannot receive from customer against negative outstanding") and would put zero-cash Payment Entries on the agent cash account. (iii) The Credit Note Journal Entry works for every case (old invoice, today's sale, zero cash, partial), never touches cash, and is what ERPNext's own reconciliation tool creates.
3. Credit rules use the net: `due = sale + selected previous − credit applied`; cash-only / per-invoice credit limit apply to what remains on today's sale.

**Cancel** (Supervisor, trip not Settled): Payment Entry → set-off Journal Entry → credit note(s) → Sales Invoice → visit.

**Guards** (§5.2): a credit note with mobile_trip needs the internal flag, trip In Field, and may only use customer_return_warehouse. customer_return_warehouse may **receive** stock only from mobile credit notes (Stock Entry with it as target, Sales Invoice / Delivery Note / Purchase Receipt into it and Stock Reconciliation on it are blocked for non-mobile documents). **Outward** standard Stock Entries (store moves good returns to FG or to Damaged Returns) stay allowed.

**Permissions**: credit notes and the set-off JE are created under ignore_permissions inside visit submit, as the agent (tests run them as the real agent; cancel as the real supervisor, CLAUDE.md rule 13). Where ERPNext re-reads referenced invoices as the session user, the same per-request exemption as the Payment Entry collection applies. Agents read + print their own credit notes through the existing Sales Invoice scope; returns against a standard invoice use the same per-request exemption as collections (the invoices this visit validated, this request only). Any Agent rule needed on a standard DocType uses the Custom DocPerm copy mechanism, integrity- and drift-checked.

## 5. Business logic

All document creation runs server-side in one DB transaction per user action; a failure rolls back the visit and any half-made invoice or payment.

### 5.1 Customer Visit submit

1. Validate: trip status = In Field; `frappe.session.user` = trip.agent.user (Supervisor bypass); visit_datetime within trip_date; geolocation present if Settings require it.
1a. **Discounts (Phase 5b).** Per line the agent enters discount_percentage **or** discount_amount (per unit; the other is computed); it applies on top of the pricing-rule rate. Optional invoice-level additional_discount_percentage **or** discount_amount, applied on **Net Total** (`apply_discount_on = "Net Total"`, taxes computed after the discount) through the Sales Invoice fields (set by code even though they are hidden in Desk on agrosys). **Cap:** manual discount = Σ qty × (pricing-rule rate − final rate) + invoice discount; manual ÷ price-list value (Σ qty × price_list_rate) × 100 ≤ agent.max_discount_pct. Pricing-rule discounts are not counted. Totals always come from `build_invoice` (ERPNext), never from the client.
2. Outcome **No Sale**: require reason (and remarks when the reason requires them). Outcome **Shop Closed**: no reason (cleared if sent), remarks optional. Both reject `sale_items` and any collection.
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
| Delivery Note / Stock Entry / Stock Reconciliation.validate | Van warehouse allowed only when `mobile_trip` set (Stock Entry) or never (DN, Stock Reco). Phase 5b: stock **into** customer_return_warehouse only from mobile credit notes / settlement entries. |
| Sales Invoice.validate (is_return, Phase 5b) | Mobile credit note: internal flag, trip In Field, warehouse = customer_return_warehouse only. |
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
| 7 | Stock Entry (Material Transfer, purpose Return Damage, Phase 5b) | customer_return_warehouse → damage_warehouse, `damaged_qty` of customer returns |
| 8 | Stock Entry (Material Issue, purpose Return Shortage, Phase 5b) | from customer_return_warehouse, `missing_qty` of customer returns, same accounts / recovery as #3 |

Post-conditions checked before commit: van Bin qty = 0 for all items; agent cash account balance = 0. Then trip status → Settled, settlement linked.

**Variance gate:** `|cash_variance| + stock_variance_value > shortage_tolerance_value` → workflow needs Supervisor approval before submit.

**Cancel settlement** (Supervisor): cancels every posting (8 → 1) in reverse, trip back to Settling.

### 5.5 Trip status machine

Draft → (submit, stock issued) Loaded → (Start Trip) In Field → (End Day: no more visits) Settling → (settlement submit) Settled. Cancel allowed only from Loaded with no visits; it cancels the issue Stock Entry.

**Reopen Trip** (Settling → In Field, `reopen_trip`): the trip's agent or a Supervisor / System Manager, from the Desk trip form or the app's Today screen (with a confirm). Allowed when the trip has no settlement, or its settlement is still workflow Draft (docstatus 0); that draft is deleted. Refused once the settlement is Pending Store or later: a Supervisor must Reject it to Draft first. A comment on the trip records who reopened it and which draft was deleted.

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

Vue 3 + `frappe-ui` built into `mobile_sales/public/frontend`, served by `www/mobile-sales.py` (login required, role Mobile Sales Agent). Installable PWA (manifest + service worker caching the **app shell only**; every API call goes to the network). While offline the app shows a "No connection" banner and blocks every submit; all submit buttons are guarded against double taps. Caching the item master and route customers moves to the later offline phase (§8.2 phase 7).

| Screen | Content |
| --- | --- |
| Today | Current trip status, vehicle + helper, van stock list with live qty, KPIs (visits, sales, collected), Start Trip / End Day / Reopen Trip |
| Route | Planned customers for the day in sequence, visited ticks, search and visit any customer (off-route visits allowed), add new customer (quick-entry: name, mobile, address, customer group and territory pickers defaulting from Settings, optional route of any active Mobile Route) |
| Visit | Step 1 check-in (GPS + photo) → Step 2 customer details edit → Step 3 shelf stock count → Step 4 outcome: No Sale (reason) or Sale (cart from van stock, line and invoice discount) → Step 4b returns (Sale / Collection Only / Return Only) → Step 5 collection (current + previous outstanding, credit applied, cash due) → Submit → Print (invoice, credit notes, receipt) |
| History | Today's visits, reprint invoice/receipt |
| Settlement | Pre-filled reconciliation, agent enters returned/damaged counts and cash denominations, submits for verification |

**Offline (later offline phase, §8.2 phase 7):** item master and route customer caching, IndexedDB queue of draft visits keyed by a client UUID (`client_ref` unique field on Customer Visit) so replays are idempotent; stock re-validated server-side on sync.

### 6.2 Whitelisted API (`mobile_sales/api/mobile.py`)

| Method | Purpose |
| --- | --- |
| `get_context()` | Agent, open trip, settings flags, price list |
| `get_van_stock(trip)` | Item, uom, actual_qty, rate, image |
| `get_route_plan(trip)` | Route customers + visited flag + outstanding |
| `get_customer(customer)` | Details, primary contact/address, outstanding invoices, last shelf stock, credit available (open credit notes, Phase 5b) |
| `price_cart(trip, customer, items, discount, returns)` | Builds unsaved Sales Invoice (and credit notes), returns totals/taxes/pricing-rule results, discount cap check, return total, credit applied, cash due |
| `return_invoice_query(...)` / `get_returnable_lines(invoice)` | Phase 5b: against_invoice picker; the invoice's lines with returnable qty and net rate |
| `search_customers(q)` / `create_customer(payload)` | Customer search (any customer); quick-entry new customer. Payload may carry `customer_group`, `territory` (leaf nodes; default from Settings) and `route` (active Mobile Route: the customer is appended with sequence = last + 1, under ignore_permissions; agents keep read only on routes) |
| `get_customer_form_options()` | Leaf customer groups and territories, active routes, Settings defaults for the new-customer form |
| `submit_visit(payload)` | Creates + submits Customer Visit (and SI/PE); idempotent on `client_ref` |
| `upload_visit_photo(filename, filedata, visit / client_ref)` | Check-in photo (jpeg/png/webp, ≤ 5 MB) on the agent's own visit |
| `get_visits(trip)` | The trip's visits (History screen) |
| `start_trip(trip)` / `end_day(trip)` / `reopen_trip(trip)` | Status transitions (§5.5) |
| `get_settlement_draft(trip)` | Computed reconciliation (creates nothing) |
| `save_settlement(trip, payload)` | Creates / updates the Draft settlement with the agent's fields only (returned / damaged qty and batch, cash denominations); recomputes the reconciliation |
| `submit_settlement_for_verification(settlement_name)` | Applies the workflow action from Draft to Pending Store (§6.5) |
| `get_receipt_escpos(doctype, name, width)` | Plain-text receipt lines for the agent's own mobile documents (for the later ESC/POS hand-off, §6.3) |
| `outstanding_invoice_query(...)` | Previous Outstanding picker on Customer Visit (one customer and company) |

`save_settlement` + `submit_settlement_for_verification` replace the earlier single `submit_settlement`.

Every method resolves the agent from `frappe.session.user`; trip/customer arguments are re-checked against it.

### 6.3 Printing

Print Format **Mobile Invoice 4in** (Jinja, Sales Invoice, 4-inch thermal) and **Mobile Collection Receipt** (Payment Entry). Up to v1.0.0 the Visit and History screens print through the browser print view. The hand-off to the Evonet Android ESC/POS print service (`lk.evonet.escposprint`) for Bluetooth printing is **deferred until after v1.0.0**; `get_receipt_escpos` already returns the plain-text lines it will use. Settlement Print Format **Mobile Settlement Sheet** (A4) with signature lines for agent, store keeper, cashier.

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
| Pending Cashier | 0 | Cashier | Verify Cash → Pending Approval (variance over tolerance) or Approved; Reject → Draft |
| Pending Approval | 0 | Supervisor | Approve → Approved; Reject → Draft |
| Approved | 1 | Cashier / Supervisor | — (submit posts ledgers) |
| Cancelled | 2 | Supervisor | — |

Every Reject returns the settlement to Draft and clears Verified by Store / Verified by Cashier. Supervisors may perform every Store Keeper and Cashier transition.

## 7. Reports and dashboard

All Script Reports read Customer Visit, Mobile Settlement and the standard ledgers; filters company, date range, agent, route, territory unless noted.

Implementation (v0.7.0): every figure comes from `mobilesales/services/reports.py` — the Script Reports, the Day Report (report and A4
print), the 20:00 email, the workspace charts and the phone's "My day" share it, so they cannot disagree. Filters also include vehicle.
Reports use ref_doctype Mobile Trip; roles Mobile Sales Supervisor / Store Keeper / Cashier, System Manager, Accounts Manager
(Accounts Manager has read / report on Mobile Trip, Customer Visit, Mobile Settlement). Agents may open Customer Visit Register,
Customer Stock Position, Outstanding by Agent and the Mobile Trip Day Report, always limited to their own trips (enforced in the
shared logic, whatever filters are sent). Planned visits: a route customer is due on a trip date when Daily, or on its visit day
(Weekly / Fortnightly; any day when no visit day is set — the fortnight's week is not recorded). "Credit given" / settlement
credit sales = what a sale left open after the cash and the return credit of the same visit (a later return paying it does not
change it).

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
| **Customer Returns Register** (v0.7.0) | Return line | date, agent, trip, visit, customer, item, qty, rate, credit amount, reason, condition, remarks, against invoice, credit note, credit applied to (per invoice), credit left; settlement received / damaged / missing on the trip × item's first row; plus every other movement of the customer return warehouse ("Moved out / in": settlement Return Damage / Shortage, manual Stock Entries) so the quantity column adds up to the Stock Ledger |
| **Discount Report** (v0.7.0) | Invoice | price-list value, pricing-rule effect (apart), line discounts, invoice discount (amount and %), manual discounts, manual % of the price-list value, agent cap %, within cap |

**Workspace "Mobile Sales"** (v0.7.0; with its Workspace Sidebar and Desktop Icon, roles Supervisor / Store Keeper / Cashier / Accounts Manager / System Manager): shortcuts (Trip, Visit, Settlement, Agent, Vehicle, Route, Mobile Visit Rejection — every visit the server refused, v0.6.1), Number Cards (Open Trips, Today's Visits, Today's Mobile Sales, Today's Collections, Today's Returns, Pending Settlements, Today's Cash Variance), Dashboard Charts from custom sources, last 30 days (Mobile sales by agent — bar; Strike rate trend — line; No-sale reasons — donut; Returns by reason — pie), links to every report.

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

Implementation (v0.7.0): the report adds a customer returns section (9b) and vehicle / helper in the header; section 10 splits issued and
top-up; section 12 reads the workflow log (the "Workflow" comments of each transition). When the settlement is submitted (Approved),
the PDF is rendered in the background after the commit and attached as a private file "<trip> Day Report.pdf" (once). The 20:00 job
(scheduler cron) sends one email with the PDFs of the settlements submitted that day to every enabled Mobile Sales Supervisor; it is
switched by Mobile Sales Settings → Daily Report Email (default off; on for agrosys) and skipped when nothing was settled. The phone's
Today screen shows "My day" (visits / planned, sales, cash collected, returns, credit given) from the same figures.

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
5. **Mobile SPA** — screens in §6.1 on top of the API, PWA shell (app shell cache only), browser printing. (ESC/POS hand-off deferred until after v1.0.0, §6.3.)
6. **Reports + workspace** — §7.
5b. **Vehicles, discounts, returns** — Mobile Vehicle + legacy patch (§3.6), line and invoice discounts with the agent cap (§5.1), customer returns with credit notes and set-off (§4.5), settlement return count (§4.3).
7. **Phase 2** — offline queue, GPS track.

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
- Customer sales returns: resolved — Phase 5b, §4.5.
- Agent shortages: always recover from salary, or write off below tolerance?
- Vehicle separate from the agent: resolved — Mobile Vehicle with optional helper, §3.6.
- Phase 5b decisions (Raj, 2026-11-02): return rate read only; leftover credit not auto-applied (customer card shows credit available); max_return_value_per_visit 0 = supervisor only; invoice discount on Net Total.
