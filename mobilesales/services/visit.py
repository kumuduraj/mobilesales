"""Customer Visit rules and submit/cancel chain (spec §5.1). Everything runs in the visit's own
transaction: any failure rolls back the visit together with any half-made invoice or payment."""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt, get_datetime, getdate

from mobilesales.services import customer_update, invoicing, stock
from mobilesales.services import settings as ms_settings
from mobilesales.services import trip as trip_service

SUPERVISOR_ROLES = ("Mobile Sales Supervisor", "System Manager")
NO_SALE_OUTCOMES = ("No Sale", "Shop Closed")


# Document events


def validate_visit(visit):
	trip, agent = invoicing.get_visit_context(visit)
	settings = ms_settings.get_settings()
	visit.agent = trip.agent
	visit.company = trip.company

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
	if visit.outcome == "Sale":
		validate_sale(visit, trip, agent, settings)
	else:
		for fieldname in ("net_total", "total_taxes", "grand_total", "rounded_total", "collect_amount"):
			visit.set(fieldname, 0)
	visit.total_collected = flt(visit.collect_amount) + sum(flt(r.allocated) for r in visit.collect_previous)
	customer_update.capture_changes(visit)


def validate_outcome(visit):
	if visit.outcome in NO_SALE_OUTCOMES:
		if not visit.no_sale_reason:
			frappe.throw(_("No Sale Reason is required for outcome {0}.").format(_(visit.outcome)))
		if frappe.db.get_value("Visit No Sale Reason", visit.no_sale_reason, "requires_remark") and not (
			visit.remarks or ""
		).strip():
			frappe.throw(_("Remarks are required for reason {0}.").format(frappe.bold(visit.no_sale_reason)))
		if visit.sale_items:
			frappe.throw(_("Remove the sale items: outcome {0} cannot have a sale.").format(_(visit.outcome)))
		if flt(visit.collect_amount) or any(flt(r.allocated) for r in visit.collect_previous):
			frappe.throw(
				_("Outcome {0} cannot collect money. Use Collection Only or Sale.").format(_(visit.outcome))
			)
	elif visit.outcome == "Collection Only":
		if visit.sale_items:
			frappe.throw(_("Remove the sale items: outcome Collection Only has no sale."))
		if not any(flt(r.allocated) > 0 for r in visit.collect_previous):
			frappe.throw(_("Collection Only needs at least one previous invoice with an allocated amount."))
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
	max_discount = flt(agent.max_discount_pct)
	for row in visit.sale_items:
		if flt(row.qty) <= 0:
			frappe.throw(_("Row {0}: Qty must be greater than 0.").format(row.idx))
		if flt(row.discount_percentage) > max_discount:
			frappe.throw(
				_("Row {0}: Discount {1}% is above your limit of {2}%.").format(
					row.idx, flt(row.discount_percentage), max_discount
				)
			)

	si = invoicing.build_invoice(visit, save=False)
	invoicing.copy_invoice_to_visit(visit, si)

	needed = _needed_stock(visit)
	available = stock.get_bin_qty_map(trip.van_warehouse, list(needed))
	for row in visit.sale_items:
		row.available_in_van = flt(available.get(row.item_code))
	_check_van_stock(trip.van_warehouse, needed, available)

	payable = flt(visit.rounded_total)
	collect = flt(visit.collect_amount)
	precision = visit.precision("collect_amount")
	if collect < 0 or flt(collect, precision) > flt(payable, precision):
		frappe.throw(_("Collect Now must be between 0 and the invoice total {0}.").format(payable))
	if not settings.allow_credit_sales:
		if flt(collect, precision) != flt(payable, precision):
			frappe.throw(
				_("Credit sales are not allowed: collect the full invoice total {0}.").format(payable),
				title=_("Cash sale only"),
			)
	elif flt(payable - collect, precision) > flt(agent.credit_limit_per_invoice, precision):
		frappe.throw(
			_("Credit of {0} is above your per-invoice credit limit of {1}.").format(
				flt(payable - collect, precision), flt(agent.credit_limit_per_invoice)
			),
			title=_("Credit limit"),
		)


def on_submit(visit):
	trip, _agent = invoicing.get_visit_context(visit)
	settings = ms_settings.get_settings()

	si = None
	if visit.outcome == "Sale":
		needed = _needed_stock(visit)
		_check_van_stock(trip.van_warehouse, needed, stock.lock_bin_qty(trip.van_warehouse, list(needed)))

	customer_update.on_visit_submit(visit, bool(settings.apply_customer_updates_directly))

	if visit.outcome == "Sale":
		si = invoicing.build_invoice(visit, save=True)
		visit.db_set("sales_invoice", si.name)
		si.reload()
		for row, info in zip(visit.sale_items, invoicing.batch_info_by_row(si), strict=False):
			if info:
				row.db_set("batch_info", info, update_modified=False)

	pe = invoicing.make_payment_entry(visit, si)
	if pe:
		visit.db_set("payment_entry", pe.name)
	trip_service.update_trip_summary(trip.name)


def before_cancel(visit):
	if not set(SUPERVISOR_ROLES) & set(frappe.get_roles()):
		frappe.throw(_("Only a Mobile Sales Supervisor can cancel a visit."), frappe.PermissionError)
	if frappe.db.get_value("Mobile Trip", visit.mobile_trip, "status") == "Settled":
		frappe.throw(_("Mobile Trip {0} is Settled; its visits cannot be cancelled.").format(visit.mobile_trip))


def on_cancel(visit):
	"""Payment Entry first, then the Sales Invoice (stock returns to the van)."""
	for doctype, name in (("Payment Entry", visit.payment_entry), ("Sales Invoice", visit.sales_invoice)):
		if not name:
			continue
		doc = frappe.get_doc(doctype, name)
		if doc.docstatus == 1:
			doc.flags.ignore_permissions = True
			doc.cancel()
	trip_service.update_trip_summary(visit.mobile_trip)


# Helpers


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
