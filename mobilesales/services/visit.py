"""Customer Visit rules and submit/cancel chain (spec §5.1). Everything runs in the visit's own
transaction: any failure rolls back the visit together with any half-made invoice or payment."""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt, get_datetime, getdate

from mobilesales.overrides.permissions import COLLECTABLE_FLAG
from mobilesales.services import customer_update, invoicing, returns, stock, vouchers
from mobilesales.services import settings as ms_settings
from mobilesales.services import trip as trip_service

SUPERVISOR_ROLES = ("Mobile Sales Supervisor", "System Manager")
NO_SALE_OUTCOMES = ("No Sale", "Shop Closed")
# Set by on_submit only (db_set): never from the client, a REST save or an amendment.
VOUCHER_LINKS = ("sales_invoice", "payment_entry", "credit_journal", "credit_notes")


# Document events


def validate_visit(visit):
	trip, agent = invoicing.get_visit_context(visit)
	settings = ms_settings.get_settings()
	for fieldname in VOUCHER_LINKS:  # validate runs before submit only, so these are never ours yet
		visit.set(fieldname, None)
	visit.client_ref = (visit.client_ref or "").strip() or None  # unique: empty must be NULL
	visit.agent = trip.agent
	visit.company = trip.company
	visit.off_route = int(not is_route_customer(trip.route, visit.customer))

	if trip.docstatus != 1 or trip.status != "In Field":
		frappe.throw(
			_("Mobile Trip {0} is {1}; visits are only possible while it is In Field.").format(
				frappe.bold(trip.name), _(trip.status)
			),
			title=_("Trip not in field"),
		)
	settlement = frappe.db.get_value("Mobile Settlement", {"mobile_trip": trip.name, "docstatus": ["<", 2]}, "name")
	if settlement:
		frappe.throw(
			_("Mobile Trip {0} already has settlement {1}; no more visits.").format(
				frappe.bold(trip.name), frappe.bold(settlement)
			)
		)
	require_agent_or_supervisor(agent)
	if getdate(visit.visit_datetime) != getdate(trip.trip_date):
		frappe.throw(_("Visit date must be the trip date {0}.").format(frappe.format(trip.trip_date, "Date")))
	if settings.require_geolocation and not (flt(visit.latitude) and flt(visit.longitude)):
		frappe.throw(_("Location (latitude / longitude) is required for every visit."))

	validate_outcome(visit)
	validate_collections(visit)
	payable = 0.0
	if visit.outcome == "Sale":
		payable = validate_sale(visit, trip, agent, settings)
	else:
		for fieldname in ("net_total", "total_taxes", "grand_total", "rounded_total", "collect_amount", "discount_amount", "additional_discount_percentage"):
			visit.set(fieldname, 0)
	notes = returns.validate_returns(visit, agent, settings)
	validate_money(visit, agent, settings, payable, returns.plan_set_off(visit, notes, payable))
	visit.total_collected = flt(visit.collect_amount) + sum(flt(r.allocated) for r in visit.collect_previous)
	customer_update.capture_changes(visit)


def validate_outcome(visit):
	if visit.outcome in NO_SALE_OUTCOMES:
		if visit.outcome == "Shop Closed":
			visit.no_sale_reason = None  # no reason for a closed shop; remarks stay optional
		elif not visit.no_sale_reason:
			frappe.throw(_("No Sale Reason is required for outcome {0}.").format(_(visit.outcome)))
		elif frappe.db.get_value("Visit No Sale Reason", visit.no_sale_reason, "requires_remark") and not (
			visit.remarks or ""
		).strip():
			frappe.throw(_("Remarks are required for reason {0}.").format(frappe.bold(visit.no_sale_reason)))
		if visit.sale_items:
			frappe.throw(_("Remove the sale items: outcome {0} cannot have a sale.").format(_(visit.outcome)))
		if visit.get("return_items"):
			frappe.throw(_("Remove the return lines: outcome {0} cannot take returns.").format(_(visit.outcome)))
		if flt(visit.collect_amount) or any(flt(r.allocated) for r in visit.collect_previous):
			frappe.throw(
				_("Outcome {0} cannot collect money. Use Collection Only or Sale.").format(_(visit.outcome))
			)
	elif visit.outcome in ("Collection Only", "Return Only"):
		if visit.sale_items:
			frappe.throw(_("Remove the sale items: outcome {0} has no sale.").format(_(visit.outcome)))
	elif visit.outcome == "Sale":
		if not visit.sale_items:
			frappe.throw(_("Add at least one item for a Sale."))
	else:
		frappe.throw(_("Select the visit outcome."))


def validate_collections(visit):
	seen = set()
	for row in visit.collect_previous:
		invoice = frappe.db.get_value(
			"Sales Invoice",
			row.sales_invoice,
			["customer", "company", "docstatus", "outstanding_amount"],
			as_dict=True,
		)
		if not invoice or invoice.docstatus != 1:
			frappe.throw(_("Row {0}: {1} is not a submitted Sales Invoice.").format(row.idx, row.sales_invoice))
		if invoice.customer != visit.customer or invoice.company != visit.company:
			frappe.throw(
				_("Row {0}: Sales Invoice {1} does not belong to customer {2}.").format(
					row.idx, frappe.bold(row.sales_invoice), frappe.bold(visit.customer)
				)
			)
		if row.sales_invoice in seen:
			frappe.throw(_("Row {0}: Sales Invoice {1} is listed twice.").format(row.idx, row.sales_invoice))
		seen.add(row.sales_invoice)

		row.outstanding = flt(invoice.outstanding_amount)
		if flt(row.allocated) < 0:
			frappe.throw(_("Row {0}: Allocated amount cannot be negative.").format(row.idx))
		if flt(row.allocated, row.precision("allocated")) > flt(row.outstanding, row.precision("allocated")):
			frappe.throw(
				_("Row {0}: Allocated {1} is more than the outstanding {2} of {3}.").format(
					row.idx, flt(row.allocated), flt(row.outstanding), frappe.bold(row.sales_invoice)
				),
				title=_("Over allocation"),
			)


def validate_sale(visit, trip, agent, settings):
	for row in visit.sale_items:
		if flt(row.qty) <= 0:
			frappe.throw(_("Row {0}: Qty must be greater than 0.").format(row.idx))
		if flt(row.discount_percentage) < 0 or flt(row.get("discount_amount")) < 0:
			frappe.throw(_("Row {0}: a discount cannot be negative.").format(row.idx))
	if flt(visit.get("discount_amount")) < 0 or not 0 <= flt(visit.get("additional_discount_percentage")) <= 100:
		frappe.throw(_("The invoice discount is not valid."))

	si = invoicing.build_invoice(visit, save=False)
	invoicing.check_discount_cap(si, agent.max_discount_pct)
	invoicing.copy_invoice_to_visit(visit, si)

	needed = _needed_stock(visit)
	available = stock.get_bin_qty_map(trip.van_warehouse, list(needed))
	for row in visit.sale_items:
		row.available_in_van = flt(available.get(row.item_code))
	_check_van_stock(trip.van_warehouse, needed, available)
	return flt(visit.rounded_total)


def validate_money(visit, agent, settings, payable, plan):
	"""Cash rules after the return credit (spec §4.5): credit is set off first, cash covers the rest."""
	credit = returns.credit_by_target(plan)
	visit.credit_applied = flt(sum(credit.values()), visit.precision("credit_applied"))
	precision = visit.precision("collect_amount")
	due_on_sale = flt(payable - credit.get(returns.SALE, 0), precision)
	cash_due = due_on_sale
	for row in visit.collect_previous:
		after_credit = flt(flt(row.outstanding) - credit.get(row.sales_invoice, 0), precision)
		cash_due += after_credit
		if flt(row.allocated, precision) > after_credit:
			frappe.throw(
				_("Row {0}: Allocated {1} is more than the {2} still due on {3} after the return credit.").format(
					row.idx, flt(row.allocated), after_credit, frappe.bold(row.sales_invoice)
				),
				title=_("Over allocation"),
			)
	visit.cash_due = flt(cash_due, precision)

	if visit.outcome == "Collection Only" and not (
		any(flt(r.allocated) > 0 for r in visit.collect_previous) or visit.credit_applied
	):
		frappe.throw(_("Collection Only needs at least one previous invoice with an allocated amount."))
	if visit.outcome != "Sale":
		return
	collect = flt(visit.collect_amount)
	if collect < 0 or flt(collect, precision) > due_on_sale:
		frappe.throw(_("Collect Now must be between 0 and the {0} still due on the invoice.").format(due_on_sale))
	if not settings.allow_credit_sales:
		if flt(collect, precision) != due_on_sale:
			frappe.throw(
				_("Credit sales are not allowed: collect the full {0} due on the invoice.").format(due_on_sale),
				title=_("Cash sale only"),
			)
	elif flt(due_on_sale - collect, precision) > flt(agent.credit_limit_per_invoice, precision):
		frappe.throw(
			_("Credit of {0} is above your per-invoice credit limit of {1}.").format(
				flt(due_on_sale - collect, precision), flt(agent.credit_limit_per_invoice)
			),
			title=_("Credit limit"),
		)


def on_submit(visit):
	trip, agent = invoicing.get_visit_context(visit)
	settings = ms_settings.get_settings()

	si = None
	if visit.outcome == "Sale":
		needed = _needed_stock(visit)
		_check_van_stock(trip.van_warehouse, needed, stock.lock_bin_qty(trip.van_warehouse, list(needed)))

	customer_update.on_visit_submit(
		visit, bool(settings.apply_customer_updates_directly), bool(settings.allow_direct_name_change)
	)

	if visit.outcome == "Sale":
		si = invoicing.build_invoice(visit, save=True)
		visit.db_set("sales_invoice", si.name)
		si.reload()
		for row, info in zip(visit.sale_items, invoicing.batch_info_by_row(si), strict=False):
			if info:
				row.db_set("batch_info", info, update_modified=False)

	# ERPNext re-reads every referenced invoice as the session user; an agent may not read standard or
	# other trips' invoices, so open exactly the ones this visit validated, for this request only.
	collectable = {row.sales_invoice for row in visit.collect_previous if row.sales_invoice}
	collectable.update(row.against_invoice for row in visit.return_items if row.against_invoice)
	if si:
		collectable.add(si.name)
	frappe.flags[COLLECTABLE_FLAG] = frozenset(collectable)
	try:
		notes = returns.build_credit_notes(visit, agent, settings, save=True) if visit.return_items else []
		if notes:
			frappe.flags[COLLECTABLE_FLAG] = frozenset(collectable | {n.name for n in notes})
			visit.db_set("credit_notes", ", ".join(n.name for n in notes))
			plan = returns.plan_set_off(visit, notes, invoicing.payable_amount(si) if si else 0, si and si.name)
			je = returns.make_set_off_journal(visit, notes, plan, si and si.name)
			if je:
				visit.db_set("credit_journal", je.name)
		pe = invoicing.make_payment_entry(visit, si)
	finally:
		frappe.flags[COLLECTABLE_FLAG] = None
	if pe:
		visit.db_set("payment_entry", pe.name)
	trip_service.update_trip_summary(trip.name)


def before_cancel(visit):
	if not set(SUPERVISOR_ROLES) & set(frappe.get_roles()):
		frappe.throw(_("Only a Mobile Sales Supervisor can cancel a visit."), frappe.PermissionError)
	if frappe.db.get_value("Mobile Trip", visit.mobile_trip, "status") == "Settled":
		frappe.throw(_("Mobile Trip {0} is Settled; its visits cannot be cancelled.").format(visit.mobile_trip))


def on_cancel(visit):
	"""Payment Entry, set-off Journal Entry, credit notes, then the Sales Invoice (stock returns to the van)."""
	credit_notes = [n.strip() for n in (visit.credit_notes or "").split(",") if n.strip()]
	own = {"mobile_trip": visit.mobile_trip, "customer_visit": visit.name}
	vouchers.cancel_linked("Payment Entry", visit.payment_entry, **own)
	vouchers.cancel_linked("Journal Entry", visit.credit_journal, mobile_trip=visit.mobile_trip)
	for name in [*credit_notes, visit.sales_invoice]:
		vouchers.cancel_linked("Sales Invoice", name, **own)
	trip_service.update_trip_summary(visit.mobile_trip)


# Helpers


def is_route_customer(route, customer) -> bool:
	"""Agents may visit any customer; a visit to one not on the trip's route is flagged off route."""
	return bool(
		route
		and frappe.db.exists("Mobile Route Customer", {"parent": route, "parenttype": "Mobile Route", "customer": customer})
	)


def require_agent_or_supervisor(agent):
	if frappe.session.user == agent.user or set(SUPERVISOR_ROLES) & set(frappe.get_roles()):
		return
	frappe.throw(_("Only the trip's agent can record visits on this trip."), frappe.PermissionError)


def _needed_stock(visit) -> dict:
	needed = defaultdict(float)
	for row in visit.sale_items:
		needed[row.item_code] += flt(row.stock_qty) or flt(row.qty) * flt(row.conversion_factor or 1)
	return needed


def _check_van_stock(van, needed, available):
	for item_code, qty in needed.items():
		have = flt(available.get(item_code))
		if flt(qty, 6) > flt(have, 6):
			frappe.throw(
				_("Not enough {0} in van {1}: need {2}, available {3}.").format(
					frappe.bold(item_code), frappe.bold(van), flt(qty), have
				),
				title=_("Insufficient van stock"),
			)
