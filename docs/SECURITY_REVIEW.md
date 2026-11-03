# Security review — Phase 7 (v1.0.0)

Scope: every whitelisted method (`api/mobile.py`, `services/*`, dashboard chart sources), the two host pages
(`/mobile-sales`, `/mobile-sales-print`), the 12 Script Reports, print formats and Jinja helpers, link queries,
the permission hooks and the role rights on standard and own DocTypes. Question asked of each: can an agent reach
another agent's data or office data, can anyone change what the app alone may change, and is the input bounded?

Tests: `mobilesales/tests/test_security.py` (each finding below names its test). Every test was run against the
v0.7.0 code first and failed there (except the sweep, which guards protection that already existed).

## Findings and fixes

| # | Severity | Finding | Fix | Test |
|---|----------|---------|-----|------|
| S1 | High | Customer Visit: agents have create / write / submit, and `sales_invoice`, `payment_entry`, `credit_journal`, `credit_notes` could be sent in a REST save (draft, or update after submit). A supervisor cancelling that visit then cancelled the linked voucher with `ignore_permissions`, even an office invoice. | `validate` clears the four links (they are only ever set by `on_submit` with `db_set`); update after submit keeps the stored values; the cancel chain cancels a voucher only if it points back (`customer_visit` / `mobile_trip`), else refuses. | `test_forged_visit_links_are_cleared_and_never_cancelled` |
| S2 | High | Mobile Settlement: in Draft the agent (and in their states store keeper / cashier) could set the eight posting links and `verified_by_store` / `verified_by_cashier` by REST. Links not re-posted at submit (e.g. `recovery_journal`) survived, and the settlement cancel cancelled them. | `validate` clears the posting links and keeps the verifiers as stored (only a workflow transition sets them); update after submit keeps stored values; reversal checks `mobile_trip` (and `mobile_settlement` for journals). | `test_forged_settlement_links_and_verifiers_are_cleared` |
| S3 | Medium | Mobile Trip: `status`, `settlement`, `stock_entries`, `opening_float_journal` and the summary are allow-on-submit; a store keeper or supervisor saving the submitted trip could set status Settled or drop stock entries. Trip cancel followed the links unchecked. | Draft validate clears postings; update after submit keeps the stored values; cancel checks `mobile_trip` on each voucher. | `test_submitted_trip_keeps_system_fields`, `test_cancel_chain_refuses_foreign_vouchers` |
| S4 | Medium | Item Price: agents (read, needed while ERPNext prices the invoice as the agent) could list every price, buying price lists included. Standard Sales Users cannot read Item Price at all. | Restricted agents: selling prices only (query condition + has_permission). | `test_agent_sees_selling_prices_…` |
| S5 | Medium | Serial and Batch Bundle: agents could list, read and write every bundle (office receipts, other agents). | Restricted agents: only bundles they created (ERPNext creates the agent's sale / credit-note bundles as the agent). | same |
| S6 | Medium | Contact / Address: agents could read every contact and address (suppliers, employees, staff). | Restricted agents: only records linked to a Customer. | same |
| S7 | Low | Account: the select right (ERPNext checks it on the receivable account) let link searches list the whole chart of accounts. | Restricted agents' searches: receivable accounts and their own cash account. Document-level select is unchanged. | same |
| S8 | Low | `price_cart` read the outstanding of any invoice named in `collect_previous` (the submit path already refused other customers' invoices). | Refused unless the invoice is the customer's, in the trip's company. | `test_inputs_are_bounded` |
| S9 | Low | `upload_visit_photo` decoded before the size check, gave a 500 on bad base64, and kept every retake as another private file. | Size checked on the encoded text first; bad base64 → the "JPEG, PNG or WebP" message; a retake replaces the earlier check-in photo. | same |
| S10 | Low | No limit on the expensive calls. Frappe's `rate_limit` is per IP, and agents share mobile-carrier IPs. | Per-user throttle per minute: `price_cart` 120, `submit_visit` 30, `get_customer_invoices` 30, `get_settlement_draft` 30, `get_receipt_escpos` 30, `upload_visit_photo` 20 (`429 RateLimitExceededError`). Only real HTTP requests are counted. | `test_throttle_is_per_user` |
| S11 | Low | Search text was unbounded; the return picker loaded every invoice of the item company wide, and ignored the typed text once an item was chosen (bug). | Search text capped at 140 characters; picker query limited to the customer's invoices with the item, typed text kept. | `test_inputs_are_bounded`, `test_return_picker_…` |

## Checked, no change needed

- **Guest access:** no `allow_guest` anywhere. Both host pages send a guest to the login page; every API method calls
  `require_roles` first (`test_non_agent_refused_by_every_method_and_host_page`).
- **Ownership:** every trip / visit / settlement method resolves the agent from `frappe.session.user`
  (`own_trip`, `own_visit`); a `client_ref` of another agent's visit gives a PermissionError, not its data.
- **Lists, reports, prints, links:** permission query conditions and has_permission on Mobile Sales Agent, Mobile
  Trip, Customer Visit, Mobile Settlement, Sales Invoice and Payment Entry (mobile vouchers of the agent's own trips
  only). Reports and charts go through `reports.trip_rows`, which pins an agent to their own record; reports not
  meant for agents do not list the agent role. Print view, the Print All page and `get_receipt_escpos` check the
  same permissions. Day Report PDFs are private files. Sweep: `test_agent_b_reaches_nothing_of_agent_a_or_the_office`
  (has_permission read / print / write, get_list, link search, print view, three agent reports, the Day Report,
  a staff-only report, a chart and the Print All page).
- **SQL:** all `frappe.db.sql` is parameterised; the permission SQL uses `frappe.db.escape`.
- **Staff-only methods:** `setup_agent`, `setup_vehicle`, `top_up`, `approve/reject_customer_update` use
  `frappe.only_for`; `start_trip` / `end_day` / `reopen_trip` / `make_settlement` check the trip's agent or staff roles.
- **Customer updates:** the Change rows are rebuilt from the `new_*` fields on every save, so a forged row cannot
  reach `approve_customer_update`.

## Accepted (by design), for the record

- **Customers:** agents read every Customer and its card (outstanding, credit available, recent invoices, standard
  ones included). Agents may visit off-route customers, collect previous outstanding and take returns against
  standard invoices (Phase 5b decisions), so this is needed.
- **Item:** agents read the Item master, including `valuation_rate` and `last_purchase_rate`. ERPNext's
  `get_item_details` checks Item read as the session user, and standard Sales Users see the same fields.
- **Small masters:** UOM, Price List names, Territory, Customer Group and Batch are readable.
- **Reports:** Script Reports have no app-level throttle. They are role-gated, scoped to the agent's trips, and fall
  under Frappe's own report timeout. The timings are in `docs/PERFORMANCE.md`.
