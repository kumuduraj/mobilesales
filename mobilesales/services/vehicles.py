"""Mobile Vehicle setup (spec §3.6): each vehicle owns one van warehouse under the van group.
The agent keeps the cash account; the van belongs to the vehicle."""

import frappe
from frappe import _

from mobilesales.services import settings as ms_settings

SETUP_ROLES = ("Mobile Sales Supervisor", "System Manager")


@frappe.whitelist()
def setup_vehicle(vehicle: str) -> str:
	"""'Create Van Warehouse' on the vehicle. Idempotent."""
	frappe.only_for(SETUP_ROLES)
	doc = frappe.get_doc("Mobile Vehicle", vehicle)
	if doc.van_warehouse:
		return doc.van_warehouse
	settings = ms_settings.get_settings()
	if not (settings.company and settings.van_warehouse_group):
		frappe.throw(_("Set Company and Van Warehouse Group in Mobile Sales Settings first."))
	doc.van_warehouse = ensure_van_warehouse(f"{doc.vehicle_no} Van", settings)
	doc.flags.ignore_permissions = True
	doc.save()
	return doc.van_warehouse


def ensure_van_warehouse(warehouse_name, settings) -> str:
	abbr = frappe.get_cached_value("Company", settings.company, "abbr")
	name = f"{warehouse_name} - {abbr}"
	if frappe.db.exists("Warehouse", name):
		return name
	return (
		frappe.get_doc(
			{
				"doctype": "Warehouse",
				"warehouse_name": warehouse_name,
				"parent_warehouse": settings.van_warehouse_group,
				"company": settings.company,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def vehicle_vans() -> list[str]:
	"""Van warehouses linked to vehicles, plus legacy agent vans."""
	vans = set(frappe.get_all("Mobile Vehicle", filters={"van_warehouse": ["is", "set"]}, pluck="van_warehouse"))
	vans.update(frappe.get_all("Mobile Sales Agent", filters={"van_warehouse": ["is", "set"]}, pluck="van_warehouse"))
	return sorted(vans)
