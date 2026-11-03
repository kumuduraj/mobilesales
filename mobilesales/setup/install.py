import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter
from frappe.model.naming import NamingSeries

from mobilesales.setup.permissions import check_standard_permission_drift, ensure_agent_permissions

MOBILE_SINV_SERIES = "MB-SINV-.YY.-.#####"
MOBILE_SRET_SERIES = "MB-SRET-.YY.-.#####"

# (reason, requires_remark)
DEFAULT_RETURN_REASONS = (
	("Damaged", 0),
	("Expired", 0),
	("Unsold / Slow-moving", 0),
	("Wrong Item", 0),
	("Other", 1),
)

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
	create_default_return_reasons()
	add_mobile_invoice_series()
	ensure_agent_permissions()


def after_migrate():
	"""Run after every `bench migrate`.

	Idempotent and never removes or reorders anything owned by other apps
	(frappe, erpnext, slmfc, deliveryplan, ...).
	"""
	create_default_no_sale_reasons()
	create_default_return_reasons()
	add_mobile_invoice_series()
	check_standard_permission_drift()  # first: compares with the rules in force before this migrate's copy
	ensure_agent_permissions()


def add_mobile_invoice_series():
	"""Append the mobile series to Sales Invoice naming_series options, the way Document Naming
	Settings does (Property Setter on 'options'). Existing options keep their order, so the first
	option (the standard default) stays the default; the 'default' property is never touched."""
	options = frappe.get_meta("Sales Invoice").get_naming_series_options()
	missing = [series for series in (MOBILE_SINV_SERIES, MOBILE_SRET_SERIES) if series not in options]
	if not missing:
		return
	for series in missing:
		NamingSeries(series).validate()
	make_property_setter("Sales Invoice", "naming_series", "options", "\n".join([*options, *missing]), "Text")
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


def create_default_return_reasons():
	for reason, requires_remark in DEFAULT_RETURN_REASONS:
		if frappe.db.exists("Mobile Return Reason", reason):
			continue
		frappe.get_doc(
			{"doctype": "Mobile Return Reason", "reason": reason, "requires_remark": requires_remark}
		).insert(ignore_permissions=True)
