"""Trip reconciliation for Mobile Settlement (spec §5.3, §5.6). Ledgers are the source of truth:
issued / sold come from Stock Ledger Entries on the van for the trip's own vouchers, cash from GL
Entries on the agent cash account. Everything here is recomputed on every save."""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt

from mobilesales.services import settings as ms_settings

ISSUE_PURPOSES = ("Issue", "Top-up")
NO_SALE_OUTCOMES = ("No Sale", "Shop Closed")
DENOMINATIONS = (5000, 2000, 1000, 500, 100, 50, 20, 10, 5, 2, 1)
QTY_PRECISION = 6


def get_trip(name) -> frappe._dict:
	return frappe.db.get_value(
		"Mobile Trip",
		name,
		[
			"name",
			"agent",
			"company",
			"status",
			"docstatus",
			"van_warehouse",
			"opening_cash_float",
			"opening_float_journal",
		],
		as_dict=True,
	)


def trip_vouchers(trip_name) -> tuple[list[str], list[str]]:
	issues = frappe.get_all(
		"Stock Entry",
		filters={"mobile_trip": trip_name, "docstatus": 1, "mobile_purpose": ["in", ISSUE_PURPOSES]},
		pluck="name",
	)
	invoices = frappe.get_all("Sales Invoice", filters={"mobile_trip": trip_name, "docstatus": 1}, pluck="name")
	return issues, invoices


def stock_movement(trip_name, van) -> tuple[dict, dict]:
	"""{item: {issued, sold}} and {(item, batch): {issued, sold}} from the van's Stock Ledger."""
	items = defaultdict(lambda: {"issued": 0.0, "sold": 0.0})
	batches = defaultdict(lambda: {"issued": 0.0, "sold": 0.0})
	issues, invoices = trip_vouchers(trip_name)
	if not issues + invoices:
		return items, batches

	entries = frappe.get_all(
		"Stock Ledger Entry",
		filters={"warehouse": van, "is_cancelled": 0, "voucher_no": ["in", issues + invoices]},
		fields=["item_code", "voucher_type", "voucher_no", "actual_qty", "serial_and_batch_bundle"],
	)
	for sle in entries:
		kind = "issued" if sle.voucher_type == "Stock Entry" and sle.voucher_no in issues else "sold"
		qty = flt(sle.actual_qty)
		items[sle.item_code][kind] += qty if kind == "issued" else -qty
		if sle.serial_and_batch_bundle:
			for entry in frappe.get_all(
				"Serial and Batch Entry",
				filters={"parent": sle.serial_and_batch_bundle},
				fields=["batch_no", "qty"],
			):
				if entry.batch_no:
					batches[(sle.item_code, entry.batch_no)][kind] += abs(flt(entry.qty))
	return items, batches


def allocate_batches(expected: dict, returned: float, damaged: float, damaged_batch=None) -> dict:
	"""Split returned / damaged / missing over the batches left in the van (spec §5.6): a named
	damaged batch first, then returns oldest first, then remaining damage, the rest is missing."""
	creation = dict(
		frappe.get_all("Batch", filters={"name": ["in", list(expected) or [""]]}, fields=["name", "creation"], as_list=True)
	)
	remaining = {b: flt(q, QTY_PRECISION) for b, q in sorted(expected.items(), key=lambda kv: (creation.get(kv[0]), kv[0])) if flt(q) > 0}
	plan = {"returned": defaultdict(float), "damaged": defaultdict(float), "missing": defaultdict(float)}

	def take(kind, qty, only=None):
		for batch in [only] if only else list(remaining):
			if qty <= 0:
				break
			portion = min(qty, remaining.get(batch, 0))
			if portion > 0:
				plan[kind][batch] += portion
				remaining[batch] = flt(remaining[batch] - portion, QTY_PRECISION)
				qty = flt(qty - portion, QTY_PRECISION)
		return qty

	if damaged_batch and flt(damaged) > 0:
		left = take("damaged", flt(damaged), only=damaged_batch)
		if left > 0:
			frappe.throw(
				_("Damaged batch {0} has only {1} left in the van, {2} entered as damaged.").format(
					frappe.bold(damaged_batch), flt(damaged) - left, flt(damaged)
				)
			)
	take("returned", flt(returned))
	if not damaged_batch:
		take("damaged", flt(damaged))
	for batch, qty in remaining.items():
		if qty > 0:
			plan["missing"][batch] += qty
	return plan


def refresh_settlement(doc):
	"""Recompute every derived field of a settlement; keeps the entered returned / damaged /
	damaged batch per item and the denomination counts."""
	trip = get_trip(doc.mobile_trip)
	settings = ms_settings.get_settings()
	agent = frappe.db.get_value("Mobile Sales Agent", trip.agent, ["cash_account", "employee"], as_dict=True)

	refresh_stock(doc, trip)
	refresh_sales_and_collections(doc, trip)
	refresh_cash(doc, trip, agent)

	recover = bool(settings.recover_shortage_from_agent and agent.employee)
	doc.variance_action = "Recover from Agent" if recover else "Write Off"
	doc.needs_approval = int(
		flt(abs(flt(doc.cash_variance)) + flt(doc.stock_variance_value), 2)
		> flt(settings.shortage_tolerance_value, 2)
	)


def refresh_stock(doc, trip):
	items, batches = stock_movement(trip.name, trip.van_warehouse)
	bins = {
		b.item_code: b
		for b in frappe.get_all(
			"Bin",
			filters={"warehouse": trip.van_warehouse},
			fields=["item_code", "actual_qty", "valuation_rate"],
		)
	}
	entered = {row.item_code: row for row in doc.stock_lines}
	item_codes = sorted(set(items) | {code for code, b in bins.items() if flt(b.actual_qty)})

	doc.set("stock_lines", [])
	doc.set("batch_lines", [])
	variance = 0.0
	for item_code in item_codes:
		item = frappe.get_cached_value("Item", item_code, ["item_name", "stock_uom", "has_batch_no"], as_dict=True)
		prev = entered.get(item_code) or frappe._dict()
		issued = flt(items[item_code]["issued"], QTY_PRECISION)
		sold = flt(items[item_code]["sold"], QTY_PRECISION)
		expected = flt(issued - sold, QTY_PRECISION)
		returned, damaged = flt(prev.returned_qty), flt(prev.damaged_qty)
		difference = flt(expected - returned - damaged, QTY_PRECISION)
		valuation_rate = flt((bins.get(item_code) or {}).get("valuation_rate"))
		missing = max(difference, 0)
		row = doc.append(
			"stock_lines",
			{
				"item_code": item_code,
				"item_name": item.item_name,
				"uom": item.stock_uom,
				"has_batch_no": item.has_batch_no,
				"issued_qty": issued,
				"sold_qty": sold,
				"expected_balance": expected,
				"bin_qty": flt((bins.get(item_code) or {}).get("actual_qty"), QTY_PRECISION),
				"returned_qty": returned,
				"damaged_qty": damaged,
				"damaged_batch_no": prev.damaged_batch_no if item.has_batch_no else None,
				"missing_qty": missing,
				"excess_qty": max(-difference, 0),
				"valuation_rate": valuation_rate,
				"missing_value": flt(missing * valuation_rate, 2),
			},
		)
		variance += row.missing_value

		if item.has_batch_no:
			expected_by_batch = {
				batch: batches[(code, batch)]["issued"] - batches[(code, batch)]["sold"]
				for (code, batch) in list(batches)
				if code == item_code
			}
			plan = allocate_batches(expected_by_batch, returned, damaged, row.damaged_batch_no)
			for (code, batch), moved in batches.items():
				if code != item_code:
					continue
				doc.append(
					"batch_lines",
					{
						"item_code": code,
						"batch_no": batch,
						"issued": moved["issued"],
						"sold": moved["sold"],
						"expected": flt(moved["issued"] - moved["sold"], QTY_PRECISION),
						"returned": plan["returned"].get(batch, 0),
						"damaged": plan["damaged"].get(batch, 0),
						"missing": plan["missing"].get(batch, 0),
					},
				)
	doc.stock_variance_value = flt(variance, 2)


def refresh_sales_and_collections(doc, trip):
	visits = frappe.get_all(
		"Customer Visit",
		filters={"mobile_trip": trip.name, "docstatus": 1},
		fields=["outcome", "collect_amount", "rounded_total"],
	)
	doc.total_visits = len(visits)
	doc.sales_visits = sum(1 for v in visits if v.outcome == "Sale")
	doc.no_sale_visits = sum(1 for v in visits if v.outcome in NO_SALE_OUTCOMES)
	doc.collection_only_visits = sum(1 for v in visits if v.outcome == "Collection Only")
	sales = [v for v in visits if v.outcome == "Sale"]
	doc.cash_sales_amount = sum(flt(v.collect_amount) for v in sales)
	doc.credit_sales_amount = sum(flt(v.rounded_total) - flt(v.collect_amount) for v in sales)

	invoices = frappe.get_all(
		"Sales Invoice", filters={"mobile_trip": trip.name, "docstatus": 1}, fields=["name", "grand_total"]
	)
	doc.invoice_count = len(invoices)
	doc.invoiced_amount = sum(flt(i.grand_total) for i in invoices)

	trip_invoices = {i.name for i in invoices}
	payments = frappe.get_all("Payment Entry", filters={"mobile_trip": trip.name, "docstatus": 1}, pluck="name")
	current = previous = 0.0
	if payments:
		for ref in frappe.get_all(
			"Payment Entry Reference",
			filters={"parent": ["in", payments], "parenttype": "Payment Entry"},
			fields=["reference_name", "allocated_amount"],
		):
			if ref.reference_name in trip_invoices:
				current += flt(ref.allocated_amount)
			else:
				previous += flt(ref.allocated_amount)
	doc.collected_current = current
	doc.collected_previous = previous
	doc.total_collected = current + previous


def refresh_cash(doc, trip, agent):
	opening = 0.0
	if trip.opening_float_journal and frappe.db.get_value("Journal Entry", trip.opening_float_journal, "docstatus") == 1:
		opening = flt(trip.opening_cash_float)
	doc.opening_cash_float = opening

	payments = frappe.get_all("Payment Entry", filters={"mobile_trip": trip.name, "docstatus": 1}, pluck="name")
	collected = 0.0
	if payments:
		collected = flt(
			frappe.db.sql(
				"""select sum(debit - credit) from `tabGL Entry`
				where account = %s and voucher_type = 'Payment Entry' and voucher_no in %s and is_cancelled = 0""",
				(agent.cash_account, tuple(payments)),
			)[0][0]
		)
	doc.expected_cash = flt(opening + collected, 2)

	if not doc.denominations:
		for value in DENOMINATIONS:
			doc.append("denominations", {"denomination": value, "count": 0})
	counted = False
	for row in doc.denominations:
		row.count = max(int(row.count or 0), 0)
		row.amount = flt(row.denomination) * row.count
		counted = counted or row.count > 0
	if counted:
		doc.cash_handed_over = sum(flt(row.amount) for row in doc.denominations)
	doc.cash_variance = flt(flt(doc.cash_handed_over) - doc.expected_cash, 2)


def get_agent_cash_balance(account) -> float:
	return flt(
		frappe.db.sql(
			"select sum(debit - credit) from `tabGL Entry` where account = %s and is_cancelled = 0", account
		)[0][0],
		2,
	)
