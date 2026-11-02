"""Sales Invoice and Payment Entry builders for Customer Visits (spec §5.1 steps 6 and 8).

build_invoice() is used twice: unsaved on every visit save (totals come from ERPNext's own pricing
and tax code) and saved + submitted on visit submit, so visit and invoice totals always agree."""

import frappe
from frappe import _
from frappe.utils import cint, flt, get_datetime, getdate, nowtime, today

from erpnext.accounts.party import get_party_account

from mobilesales.overrides.guards import INTERNAL_FLAG
from mobilesales.services import settings as ms_settings


def get_visit_context(visit) -> tuple[frappe._dict, frappe._dict]:
	trip = frappe.db.get_value(
		"Mobile Trip",
		visit.mobile_trip,
		["name", "agent", "company", "van_warehouse", "route", "trip_date", "status", "docstatus"],
		as_dict=True,
	)
	if not trip:
		frappe.throw(_("Mobile Trip {0} does not exist.").format(frappe.bold(visit.mobile_trip)))
	agent = frappe.db.get_value(
		"Mobile Sales Agent",
		trip.agent,
		[
			"name",
			"user",
			"sales_person",
			"selling_price_list",
			"cash_account",
			"mode_of_payment",
			"max_discount_pct",
			"credit_limit_per_invoice",
			"max_return_value_per_visit",
		],
		as_dict=True,
	)
	return trip, agent


def build_invoice(visit, save=False):
	trip, agent = get_visit_context(visit)
	settings = ms_settings.get_settings()
	posting_date, posting_time = posting_datetime(visit)

	si = frappe.new_doc("Sales Invoice")
	si.update(
		{
			"company": trip.company,
			"customer": visit.customer,
			"set_posting_time": 1,
			"posting_date": posting_date,
			"posting_time": posting_time,
			"update_stock": 1,
			"set_warehouse": trip.van_warehouse,
			"selling_price_list": agent.selling_price_list or settings.selling_price_list,
			"mobile_trip": trip.name,
			"customer_visit": visit.name,
			"is_mobile_sale": 1,
		}
	)
	if settings.sinv_naming_series:
		si.naming_series = settings.sinv_naming_series
	if agent.sales_person:
		si.append("sales_team", {"sales_person": agent.sales_person, "allocated_percentage": 100})
	for row in visit.sale_items:
		si.append(
			"items",
			{"item_code": row.item_code, "qty": row.qty, "uom": row.uom, "warehouse": trip.van_warehouse},
		)

	si.set_missing_values()
	if settings.default_tax_template:
		si.taxes_and_charges = settings.default_tax_template
		si.set("taxes", [])
		si.set_taxes()
	si.calculate_taxes_and_totals()  # pricing rules only: the base for the agent's manual discount
	apply_manual_discounts(visit, si)

	if save:
		si.flags.ignore_permissions = True
		si.flags[INTERNAL_FLAG] = True
		si.insert()
		si.submit()
	return si


def apply_manual_discounts(visit, si):
	"""The agent's line discount (% or amount per unit) applies on top of the pricing-rule rate; the
	invoice discount on Net Total. Records si.flags.manual_discount for the cap (spec §5.1)."""
	price_list_value = manual = 0.0
	freeze = False
	for row, item in zip(visit.sale_items, si.items, strict=False):
		pricing_rule_rate = flt(item.rate)
		final = pricing_rule_rate
		if flt(row.get("discount_amount")):
			final = pricing_rule_rate - flt(row.discount_amount)
		elif flt(row.discount_percentage):
			final = pricing_rule_rate * (1 - flt(row.discount_percentage) / 100)
		final = flt(final, item.precision("rate"))
		if final < 0:
			frappe.throw(_("Row {0}: the discount is more than the rate {1}.").format(row.idx, pricing_rule_rate))
		if final != pricing_rule_rate:
			_set_rate(item, final)
			freeze = freeze or bool(item.pricing_rules)
		row.pricing_rule_rate = pricing_rule_rate
		price_list_value += flt(item.qty) * (flt(item.price_list_rate) or pricing_rule_rate)
		manual += flt(item.qty) * (pricing_rule_rate - final)

	if freeze and any(item.is_free_item for item in si.items):
		frappe.throw(
			_(
				"A free-item offer applies to this invoice, so a manual discount on a line with a pricing rule "
				"is not possible (the free item would be lost). Remove that line discount."
			),
			title=_("Discount not possible"),
		)
	if freeze:
		# ERPNext re-applies pricing rules on save, which would drop the manual discount on those lines:
		# keep every computed rate and save the invoice with ignore_pricing_rule (the visit keeps
		# pricing_rule_rate per line).
		si.ignore_pricing_rule = 1
		for item in si.items:
			_set_rate(item, flt(item.rate))
			item.pricing_rules = ""

	if flt(visit.get("discount_amount")) or flt(visit.get("additional_discount_percentage")):
		si.apply_discount_on = "Net Total"
		if flt(visit.get("discount_amount")):
			si.discount_amount = flt(visit.discount_amount)
			si.additional_discount_percentage = 0
		else:
			si.additional_discount_percentage = flt(visit.additional_discount_percentage)
	si.calculate_taxes_and_totals()
	manual += flt(si.discount_amount)
	si.flags.manual_discount = frappe._dict(
		amount=flt(manual, 2),
		price_list_value=flt(price_list_value, 2),
		percentage=flt(manual / price_list_value * 100, 3) if price_list_value else 0,
	)


def _set_rate(item, rate):
	base = flt(item.rate_with_margin) or flt(item.price_list_rate)
	item.discount_percentage = 0
	item.discount_amount = flt(base - rate, item.precision("discount_amount"))
	item.rate = rate


def check_discount_cap(si, max_discount_pct):
	info = si.flags.manual_discount
	if info and info.amount > 0 and info.percentage > flt(max_discount_pct) + 0.0005:
		frappe.throw(
			_("Your discounts ({0}% of the price-list value) are above your limit of {1}%.").format(
				flt(info.percentage, 2), flt(max_discount_pct)
			),
			title=_("Discount limit"),
		)



def posting_datetime(visit) -> tuple:
	"""Today's visits post at the moment of submit, never at the (earlier) time the visit form was
	opened: stock topped up in between would otherwise be backdated away. Back-dated trips post at
	the visit time."""
	visit_dt = get_datetime(visit.visit_datetime)
	if getdate(visit_dt) == getdate(today()):
		return getdate(today()), nowtime()
	return visit_dt.date(), visit_dt.strftime("%H:%M:%S")


def payable_amount(si) -> float:
	if cint(si.disable_rounded_total) or not flt(si.rounded_total):
		return flt(si.grand_total)
	return flt(si.rounded_total)


def copy_invoice_to_visit(visit, si):
	"""Copy ERPNext's computed prices back. The agent's entered discount is kept as entered."""
	for row, item in zip(visit.sale_items, si.items, strict=False):
		row.uom = item.uom
		row.conversion_factor = item.conversion_factor
		row.stock_qty = item.stock_qty
		row.price_list_rate = item.price_list_rate
		row.rate = item.rate
		row.amount = item.amount
		# enter one, the other is computed (both relative to the pricing-rule rate)
		discount = flt(row.pricing_rule_rate) - flt(item.rate)
		row.discount_amount = flt(discount, item.precision("discount_amount")) if discount > 0 else 0
		row.discount_percentage = (
			flt(discount / flt(row.pricing_rule_rate) * 100, 3) if discount > 0 and flt(row.pricing_rule_rate) else 0
		)
	if si.apply_discount_on == "Net Total" and flt(si.discount_amount):
		visit.discount_amount = si.discount_amount
		visit.additional_discount_percentage = si.additional_discount_percentage
	else:
		visit.discount_amount = visit.additional_discount_percentage = 0
	visit.net_total = si.net_total
	visit.total_taxes = si.total_taxes_and_charges
	visit.grand_total = si.grand_total
	visit.rounded_total = payable_amount(si)


def make_payment_entry(visit, si=None):
	"""One Payment Entry per visit: collect_amount against the new invoice plus every
	collect_previous allocation. Returns None when nothing is collected."""
	references = []
	if si and flt(visit.collect_amount) > 0:
		references.append((si.name, flt(visit.collect_amount)))
	references += [(row.sales_invoice, flt(row.allocated)) for row in visit.collect_previous if flt(row.allocated) > 0]
	total = sum(amount for _name, amount in references)
	if total <= 0:
		return None

	trip, agent = get_visit_context(visit)
	posting_date = posting_datetime(visit)[0]
	pe = frappe.new_doc("Payment Entry")
	pe.update(
		{
			"payment_type": "Receive",
			"company": trip.company,
			"posting_date": posting_date,
			"mode_of_payment": agent.mode_of_payment,
			"party_type": "Customer",
			"party": visit.customer,
			"paid_from": get_party_account("Customer", visit.customer, trip.company),
			"paid_to": agent.cash_account,
			"paid_amount": total,
			"received_amount": total,
			"source_exchange_rate": 1,
			"target_exchange_rate": 1,
			"reference_no": visit.name,
			"reference_date": posting_date,
			"mobile_trip": trip.name,
			"customer_visit": visit.name,
		}
	)
	for name, amount in references:
		pe.append(
			"references",
			{"reference_doctype": "Sales Invoice", "reference_name": name, "allocated_amount": amount},
		)
	pe.flags.ignore_permissions = True
	pe.flags[INTERNAL_FLAG] = True
	pe.insert()
	pe.submit()
	return pe


def batch_info_by_row(si) -> list[str]:
	"""Batches actually picked for each invoice line, e.g. 'B-001: 5, B-002: 2'."""
	info = []
	for item in si.items:
		text = ""
		if item.serial_and_batch_bundle:
			entries = frappe.get_all(
				"Serial and Batch Entry",
				filters={"parent": item.serial_and_batch_bundle},
				fields=["batch_no", "qty"],
				order_by="idx",
			)
			text = ", ".join(f"{e.batch_no}: {abs(flt(e.qty))}" for e in entries if e.batch_no)
		info.append(text)
	return info
