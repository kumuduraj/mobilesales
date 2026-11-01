"""Whitelisted API for the mobile app (spec §6.2). The agent is always resolved from the session user."""

import frappe
from frappe import _

from erpnext.stock.doctype.batch.batch import get_batch_qty

from mobilesales.services import settings as ms_settings
from mobilesales.services import trip as trip_service

VAN_STOCK_ROLES = ("Mobile Sales Supervisor", "Mobile Sales Store Keeper", "System Manager")
SETTINGS_FLAGS = (
	"company",
	"allow_credit_sales",
	"require_geolocation",
	"apply_customer_updates_directly",
	"selling_price_list",
)


@frappe.whitelist()
def get_context() -> dict:
	agent = frappe.db.get_value(
		"Mobile Sales Agent",
		{"user": frappe.session.user},
		[
			"name",
			"agent_name",
			"is_active",
			"van_warehouse",
			"mode_of_payment",
			"selling_price_list",
			"default_route",
			"max_discount_pct",
			"credit_limit_per_invoice",
		],
		as_dict=True,
	)
	trip = None
	if agent:
		trip = frappe.db.get_value(
			"Mobile Trip",
			{
				"agent": agent.name,
				"docstatus": ["<", 2],
				"status": ["not in", trip_service.CLOSED_STATUSES],
			},
			["name", "status", "trip_date", "route", "van_warehouse", "docstatus"],
			as_dict=True,
			order_by="creation desc",
		)

	settings = ms_settings.get_settings()
	flags = {f: settings.get(f) for f in SETTINGS_FLAGS}
	flags["currency"] = settings.company and frappe.get_cached_value(
		"Company", settings.company, "default_currency"
	)
	return {"agent": agent, "trip": trip, "settings": flags}


@frappe.whitelist()
def get_van_stock(trip: str) -> list[dict]:
	doc = frappe.get_doc("Mobile Trip", trip)
	if not (trip_service.is_trip_agent(doc) or set(VAN_STOCK_ROLES) & set(frappe.get_roles())):
		frappe.throw(_("You can only view the van stock of your own trip."), frappe.PermissionError)

	bin = frappe.qb.DocType("Bin")
	item = frappe.qb.DocType("Item")
	rows = (
		frappe.qb.from_(bin)
		.join(item)
		.on(bin.item_code == item.name)
		.select(
			bin.item_code,
			item.item_name,
			item.stock_uom,
			bin.actual_qty,
			bin.valuation_rate,
			item.image,
			item.has_batch_no,
		)
		.where((bin.warehouse == doc.van_warehouse) & (bin.actual_qty != 0))
		.orderby(bin.item_code)
		.run(as_dict=True)
	)
	for row in rows:
		row.batches = []
		if row.has_batch_no:
			row.batches = [
				{"batch_no": b.get("batch_no"), "qty": b.get("qty")}
				for b in get_batch_qty(warehouse=doc.van_warehouse, item_code=row.item_code)
				if b.get("qty")
			]
	return rows
