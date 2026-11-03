"""Customer returns from the van (spec §4.5): credit notes into the customer return warehouse and one
credit set-off Journal Entry per visit. Agents never refund cash: credit is set off against the
returned goods' own invoice, today's sale and the selected previous invoices; the rest stays on the
customer account.

Credit notes are built field by field (not with ERPNext's make_sales_return mapper, which checks
Sales Invoice create permission for the session user); ERPNext's own return validation still runs on
insert (return_against + sales_invoice_item)."""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt

from erpnext.accounts.party import get_party_account

from mobilesales.overrides.guards import INTERNAL_FLAG
from mobilesales.services import invoicing

RETURN_OUTCOMES = ("Sale", "Collection Only", "Return Only")
SUPERVISOR_ROLES = ("Mobile Sales Supervisor", "System Manager")
SALE = "__sale__"  # set-off target: today's invoice (not saved yet while validating)


# Validation


def validate_returns(visit, agent, settings) -> list:
	"""Resolve every return line (original invoice line, batches, rate), price the credit notes
	through ERPNext and apply the per-visit limit. Returns the unsaved credit notes."""
	rows = visit.get("return_items") or []
	if not rows:
		if visit.outcome == "Return Only":
			frappe.throw(_("Add at least one return line for Return Only."))
		visit.return_total = 0
		return []
	if visit.outcome not in RETURN_OUTCOMES:
		frappe.throw(_("Outcome {0} cannot take returns.").format(_(visit.outcome)))
	if not settings.returns_enabled or not settings.customer_return_warehouse:
		frappe.throw(_("Customer returns are not enabled in Mobile Sales Settings."))

	used = defaultdict(float)  # (original line, batch) -> stock qty already taken by earlier rows
	for row in rows:
		_resolve_row(visit, row, used)

	notes = build_credit_notes(visit, agent, settings)
	visit.return_total = flt(sum(invoicing.payable_amount(note) * -1 for note in notes), visit.precision("return_total"))

	limit = flt(agent.max_return_value_per_visit)
	if visit.return_total > limit and not set(SUPERVISOR_ROLES) & set(frappe.get_roles()):
		frappe.throw(
			_("Returns of {0} are above your limit of {1} per visit: this visit needs a supervisor.").format(
				visit.return_total, limit
			),
			title=_("Return limit"),
		)
	return notes


def _resolve_row(visit, row, used):
	if flt(row.qty) <= 0:
		frappe.throw(_("Return row {0}: Qty must be greater than 0.").format(row.idx))
	reason = frappe.db.get_value("Mobile Return Reason", row.return_reason, "requires_remark")
	if reason is None:
		frappe.throw(_("Return row {0}: choose a return reason.").format(row.idx))
	if reason and not (row.remarks or "").strip():
		frappe.throw(_("Return row {0}: remarks are required for reason {1}.").format(row.idx, frappe.bold(row.return_reason)))
	item = frappe.get_cached_value("Item", row.item_code, ["is_stock_item", "has_batch_no", "stock_uom", "disabled"], as_dict=True)
	if not item or not item.is_stock_item or item.disabled:
		frappe.throw(_("Return row {0}: {1} is not an active stock item.").format(row.idx, frappe.bold(row.item_code)))

	row.pieces = []
	if not row.against_invoice:
		if item.has_batch_no:
			frappe.throw(
				_("Return row {0}: {1} is batch-tracked; choose the invoice it was sold on.").format(
					row.idx, frappe.bold(row.item_code)
				)
			)
		row.uom = row.uom or item.stock_uom
		row.conversion_factor = flt(
			frappe.db.get_value("UOM Conversion Detail", {"parent": row.item_code, "uom": row.uom}, "conversion_factor")
		) or (1 if row.uom == item.stock_uom else 0)
		if not row.conversion_factor:
			frappe.throw(_("Return row {0}: UOM {1} has no conversion factor on {2}.").format(row.idx, row.uom, row.item_code))
		row.sales_invoice_item = None
		row.pieces.append(frappe._dict(qty=flt(row.qty), batch_no=None, line=None))
		return

	invoice = frappe.db.get_value(
		"Sales Invoice", row.against_invoice, ["customer", "company", "docstatus", "is_return", "update_stock"], as_dict=True
	)
	if not invoice or invoice.docstatus != 1 or invoice.is_return:
		frappe.throw(_("Return row {0}: {1} is not a submitted Sales Invoice.").format(row.idx, row.against_invoice))
	if not invoice.update_stock:
		# ERPNext takes such returns through the Delivery Note, not a stock credit note
		frappe.throw(
			_("Return row {0}: Sales Invoice {1} was delivered with a Delivery Note; return these goods at the office.").format(
				row.idx, frappe.bold(row.against_invoice)
			)
		)
	if invoice.customer != visit.customer or invoice.company != visit.company:
		frappe.throw(
			_("Return row {0}: Sales Invoice {1} does not belong to customer {2}.").format(
				row.idx, frappe.bold(row.against_invoice), frappe.bold(visit.customer)
			)
		)

	lines = [
		line
		for line in returnable_lines(row.against_invoice)
		if line.item_code == row.item_code and (not row.sales_invoice_item or line.name == row.sales_invoice_item)
	]
	if not lines:
		frappe.throw(
			_("Return row {0}: {1} was not sold on {2}.").format(row.idx, frappe.bold(row.item_code), row.against_invoice)
		)
	needed = flt(row.qty)
	for line in lines:  # first line with enough left
		left = flt(line.returnable_qty) - used[(line.name, None)] / flt(line.conversion_factor or 1)
		if flt(left, 6) >= flt(needed, 6):
			break
	else:
		frappe.throw(
			_("Return row {0}: only {1} {2} of {3} can still be returned against {4}.").format(
				row.idx, flt(max(flt(l.returnable_qty) for l in lines)), lines[0].uom, row.item_code, row.against_invoice
			),
			title=_("Return quantity"),
		)
	row.sales_invoice_item = line.name
	row.uom = line.uom
	row.conversion_factor = flt(line.conversion_factor) or 1
	used[(line.name, None)] += needed * row.conversion_factor

	if not item.has_batch_no:
		row.pieces.append(frappe._dict(qty=needed, batch_no=None, line=line))
		return
	# Batch items: only batches sold on that line, less what was already returned, in sale order.
	stock_needed = needed * row.conversion_factor
	for batch_no, left in line.batches.items():
		left -= used[(line.name, batch_no)]
		take = min(left, stock_needed)
		if flt(take, 6) <= 0:
			continue
		used[(line.name, batch_no)] += take
		row.pieces.append(frappe._dict(qty=take / row.conversion_factor, batch_no=batch_no, line=line))
		stock_needed -= take
		if flt(stock_needed, 6) <= 0:
			break
	if flt(stock_needed, 6) > 0:
		frappe.throw(_("Return row {0}: the batches sold on {1} cannot cover this quantity.").format(row.idx, row.against_invoice))


def returnable_lines(invoice) -> list:
	"""The invoice's lines with qty still returnable (and per-batch stock qty for batch items)."""
	lines = frappe.get_all(
		"Sales Invoice Item",
		filters={"parent": invoice, "parenttype": "Sales Invoice"},
		fields=["name", "item_code", "item_name", "uom", "conversion_factor", "qty", "stock_qty", "net_rate", "serial_and_batch_bundle", "batch_no"],
		order_by="idx asc",
	)
	returns = frappe.get_all(
		"Sales Invoice Item",
		filters={"sales_invoice_item": ["in", [line.name for line in lines] or [""]], "docstatus": 1},
		fields=["name", "sales_invoice_item", "qty", "stock_qty", "serial_and_batch_bundle", "batch_no"],
	)
	returned_qty = defaultdict(float)
	returned_batches = defaultdict(float)
	for ret in returns:
		returned_qty[ret.sales_invoice_item] += abs(flt(ret.qty))
		for batch_no, qty in _bundle_batches(ret).items():
			returned_batches[(ret.sales_invoice_item, batch_no)] += abs(qty)
	for line in lines:
		line.returnable_qty = flt(line.qty) - returned_qty[line.name]
		line.batches = {
			batch_no: abs(qty) - returned_batches[(line.name, batch_no)]
			for batch_no, qty in _bundle_batches(line).items()
		}
	return [line for line in lines if flt(line.returnable_qty, 6) > 0]


def _bundle_batches(row) -> dict:
	if row.serial_and_batch_bundle:
		batches = defaultdict(float)
		for entry in frappe.get_all(
			"Serial and Batch Entry",
			filters={"parent": row.serial_and_batch_bundle},
			fields=["batch_no", "qty"],
			order_by="idx asc",
		):
			if entry.batch_no:
				batches[entry.batch_no] += flt(entry.qty)
		return dict(batches)
	if row.batch_no:
		return {row.batch_no: flt(row.stock_qty)}
	return {}


# Credit notes


def build_credit_notes(visit, agent, settings, save=False) -> list:
	"""One credit note per against_invoice, plus one for lines without an invoice."""
	groups = {}
	for row in visit.return_items:
		groups.setdefault(row.against_invoice or None, []).append(row)
	notes = []
	for invoice, rows in groups.items():
		note = _credit_note(visit, agent, settings, invoice, rows)
		if save:
			note.flags.ignore_permissions = True
			note.flags[INTERNAL_FLAG] = True
			note.insert()
			note.submit()
			note.reload()
			for row in rows:
				row.db_set({"credit_note": note.name, "batch_info": _batch_info(note, row)}, update_modified=False)
		notes.append(note)
	return notes


def _credit_note(visit, agent, settings, invoice, rows):
	trip, trip_agent = invoicing.get_visit_context(visit)
	posting_date, posting_time = invoicing.posting_datetime(visit)
	warehouse = settings.customer_return_warehouse
	note = frappe.new_doc("Sales Invoice")
	note.update(
		{
			"is_return": 1,
			"return_against": invoice,
			"update_outstanding_for_self": 1,
			"company": trip.company,
			"customer": visit.customer,
			"set_posting_time": 1,
			"posting_date": posting_date,
			"posting_time": posting_time,
			"update_stock": 1,
			"set_warehouse": warehouse,
			"ignore_pricing_rule": 1,
			"selling_price_list": trip_agent.selling_price_list or settings.selling_price_list,
			"mobile_trip": trip.name,
			"customer_visit": visit.name,
			"is_mobile_sale": 1,
		}
	)
	if settings.sret_naming_series:
		note.naming_series = settings.sret_naming_series
	if trip_agent.sales_person:
		note.append("sales_team", {"sales_person": trip_agent.sales_person, "allocated_percentage": 100})
	for row in rows:
		for piece in row.pieces:
			note.append(
				"items",
				{
					"item_code": row.item_code,
					"qty": -flt(piece.qty),
					"uom": row.uom,
					"conversion_factor": row.conversion_factor,
					"warehouse": warehouse,
					"sales_invoice_item": piece.line.name if piece.line else None,
					"batch_no": piece.batch_no,
					"use_serial_batch_fields": 1 if piece.batch_no else 0,
				},
			)
	note.set_missing_values()
	taxes_template = (invoice and frappe.db.get_value("Sales Invoice", invoice, "taxes_and_charges")) or settings.default_tax_template
	if taxes_template:
		note.taxes_and_charges = taxes_template
		note.set("taxes", [])
		note.set_taxes()

	items = iter(note.items)
	for row in rows:
		for piece in row.pieces:
			item = next(items)
			rate = flt(piece.line.net_rate) if piece.line else flt(item.price_list_rate)
			if not rate:
				frappe.throw(_("Return row {0}: no price for {1}.").format(row.idx, frappe.bold(row.item_code)))
			item.update(
				{
					"conversion_factor": row.conversion_factor,
					"price_list_rate": rate,
					"rate": rate,
					"discount_percentage": 0,
					"discount_amount": 0,
					"margin_type": None,
					"margin_rate_or_amount": 0,
					"pricing_rules": None,
					"warehouse": warehouse,
				}
			)
			if not invoice:
				item.incoming_rate = standalone_cost(row, trip, settings)
	note.calculate_taxes_and_totals()

	items = iter(note.items)
	for row in rows:
		amount = stock_qty = 0.0
		for _piece in row.pieces:
			item = next(items)
			amount += abs(flt(item.amount))
			stock_qty += abs(flt(item.stock_qty))
			row.rate = item.rate
		row.amount = flt(amount, row.precision("amount"))
		row.stock_qty = stock_qty
	return note


def standalone_cost(row, trip, settings) -> float:
	"""Stock value per stock unit of a return without an invoice: the van's valuation, else the source store's, else
	the Item's. ERPNext v16.5x no longer guesses one for a stand-alone credit note into a warehouse with no history
	(the customer return warehouse) and refuses the note; such a return is never posted at 0."""
	for warehouse in (trip.van_warehouse, settings.source_warehouse):
		rate = warehouse and frappe.db.get_value("Bin", {"item_code": row.item_code, "warehouse": warehouse}, "valuation_rate")
		if flt(rate):
			return flt(rate)
	rate = flt(frappe.db.get_value("Item", row.item_code, "valuation_rate"))
	if not rate:
		frappe.throw(
			_("Return row {0}: {1} has no stock value yet; choose the invoice it was sold on.").format(row.idx, frappe.bold(row.item_code))
		)
	return rate


def _batch_info(note, row) -> str:
	parts = []
	for item in note.items:
		if item.item_code != row.item_code or (item.sales_invoice_item or None) != (row.sales_invoice_item or None):
			continue
		for batch_no, qty in _bundle_batches(item).items():
			parts.append(f"{batch_no}: {abs(flt(qty))}")
	return ", ".join(parts)


# Credit set-off


def plan_set_off(visit, notes, sale_payable=0.0, sale_invoice=None) -> list:
	"""[(credit note index, target invoice or SALE, amount)] in the spec order: the note's own invoice,
	today's sale, then the selected previous invoices. Credit left over stays on the customer."""
	outstanding = {}

	def left(target):
		if target not in outstanding:
			if target == SALE:
				outstanding[target] = flt(sale_payable)
			else:
				outstanding[target] = flt(frappe.db.get_value("Sales Invoice", target, "outstanding_amount"))
		return outstanding[target]

	previous = [row.sales_invoice for row in visit.collect_previous if row.sales_invoice]
	plan = []
	for index, note in enumerate(notes):
		credit = abs(flt(invoicing.payable_amount(note)))
		targets = [t for t in (note.return_against,) if t] + ([SALE] if sale_payable else []) + previous
		for target in dict.fromkeys(targets):
			amount = flt(min(credit, left(target)), 2)
			if amount <= 0:
				continue
			plan.append((index, target, amount))
			outstanding[target] -= amount
			credit -= amount
			if credit <= 0:
				break
	return plan


def credit_by_target(plan) -> dict:
	totals = defaultdict(float)
	for _index, target, amount in plan:
		totals[target] += amount
	return dict(totals)


def make_set_off_journal(visit, notes, plan, sale_invoice=None):
	"""Journal Entry 'Credit Note', exactly like ERPNext's Payment Reconciliation (reconcile_dr_cr_note):
	receivable lines only, Dr against the credit note, Cr against the invoice it settles."""
	if not plan:
		return None
	trip, _agent = invoicing.get_visit_context(visit)
	posting_date = invoicing.posting_datetime(visit)[0]
	receivable = get_party_account("Customer", visit.customer, trip.company)
	cost_center = frappe.get_cached_value("Company", trip.company, "cost_center")
	je = frappe.new_doc("Journal Entry")
	je.update(
		{
			"voucher_type": "Credit Note",
			"company": trip.company,
			"posting_date": posting_date,
			"mobile_trip": trip.name,
			"user_remark": _("Return credit set off in Customer Visit {0}").format(visit.name),
		}
	)
	for index, target, amount in plan:
		note = notes[index]
		invoice = sale_invoice if target == SALE else target
		common = {"account": receivable, "party_type": "Customer", "party": visit.customer, "cost_center": cost_center}
		je.append(
			"accounts",
			{**common, "debit_in_account_currency": amount, "reference_type": "Sales Invoice", "reference_name": note.name},
		)
		je.append(
			"accounts",
			{**common, "credit_in_account_currency": amount, "reference_type": "Sales Invoice", "reference_name": invoice},
		)
	je.flags.ignore_permissions = True
	je.flags[INTERNAL_FLAG] = True
	je.insert()
	je.submit()
	return je


def credit_available(customer, company) -> float:
	"""Open credit on the customer's credit notes (negative outstanding), for the customer card."""
	total = frappe.db.sql(
		"""select sum(outstanding_amount) from `tabSales Invoice`
		where docstatus = 1 and is_return = 1 and customer = %s and company = %s and outstanding_amount < 0""",
		(customer, company),
	)[0][0]
	return abs(flt(total))
