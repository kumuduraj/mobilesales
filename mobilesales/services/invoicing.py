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
			{
				"item_code": row.item_code,
				"qty": row.qty,
				"uom": row.uom,
				"warehouse": trip.van_warehouse,
				"discount_percentage": flt(row.discount_percentage),
			},
		)

	si.set_missing_values()
	if settings.default_tax_template:
		si.taxes_and_charges = settings.default_tax_template
		si.set("taxes", [])
		si.set_taxes()
	si.calculate_taxes_and_totals()

	if save:
		si.flags.ignore_permissions = True
		si.flags[INTERNAL_FLAG] = True
		si.insert()
		si.submit()
	return si


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
