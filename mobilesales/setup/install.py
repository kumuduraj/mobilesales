import frappe

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


def after_migrate():
	"""Run after every `bench migrate`.

	Idempotent and never touches documents owned by other apps
	(frappe, erpnext, slmfc, deliveryplan, ...).
	"""
	create_default_no_sale_reasons()


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
