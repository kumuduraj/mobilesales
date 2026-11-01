import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter
from frappe.model.naming import NamingSeries

from mobilesales.setup.permissions import ensure_agent_permissions

MOBILE_SINV_SERIES = "MB-SINV-.YY.-.#####"

# (reason, category, requires_remark)
DEFAULT_NO_SALE_REASONS = (
	("Stock Sufficient", "Stock Sufficient", 0),
	("Price Too High", "Price", 0),
	("Credit Issue", "Credit Issue", 0),
	("Shop Closed", "Shop Closed", 0),
	("Competitor Product", "Competitor", 0),
	("Owner Absent", "Owner Absent", 0),
	("Other", "Other", 1),
)


def after_install():
	"""Run once after `install-app mobilesales`.

	Idempotent setup only (check-exists before insert), so running it again never
	duplicates or overwrites site data. No accounts or warehouses are created here.
	"""
	create_default_no_sale_reasons()
	add_mobile_invoice_series()
	ensure_agent_permissions()


def after_migrate():
	"""Run after every `bench migrate`.

	Idempotent and never removes or reorders anything owned by other apps
	(frappe, erpnext, slmfc, deliveryplan, ...).
	"""
	create_default_no_sale_reasons()
	add_mobile_invoice_series()
	ensure_agent_permissions()


def add_mobile_invoice_series():
	"""Append the mobile series to Sales Invoice naming_series options, the way Document Naming
	Settings does (Property Setter on 'options'). Existing options keep their order, so the first
	option (the standard default) stays the default; the 'default' property is never touched."""
	options = frappe.get_meta("Sales Invoice").get_naming_series_options()
	if MOBILE_SINV_SERIES in options:
		return
	NamingSeries(MOBILE_SINV_SERIES).validate()
	make_property_setter(
		"Sales Invoice", "naming_series", "options", "\n".join([*options, MOBILE_SINV_SERIES]), "Text"
	)
	frappe.clear_cache(doctype="Sales Invoice")


def create_default_no_sale_reasons():
	for reason, category, requires_remark in DEFAULT_NO_SALE_REASONS:
		if frappe.db.exists("Visit No Sale Reason", reason):
			continue
		frappe.get_doc(
			{
				"doctype": "Visit No Sale Reason",
				"reason": reason,
				"category": category,
				"requires_remark": requires_remark,
			}
		).insert(ignore_permissions=True)
