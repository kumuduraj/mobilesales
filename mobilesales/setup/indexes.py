"""Secondary indexes the app adds to two ERPNext tables (docs/PERFORMANCE.md). Without them these lookups scan the
whole table, and the table grows with every sale. ERPNext v16 (and its version-16 head) indexes neither field. The
index names carry the app's "ms_" prefix, so they never clash with ERPNext's own (Frappe's schema sync only manages
indexes named after a field); uninstall drops them again. Added only through the patch
mobilesales.patches.v1_0.add_core_lookup_indexes and after_install, never by hand."""

import frappe

CORE_INDEXES = (
	# rows already returned against an invoice row: every return line, van or office
	# (erpnext.controllers.sales_and_purchase_return.get_filters_for_packed_item)
	("Sales Invoice Item", "sales_invoice_item", "ms_sales_invoice_item"),
	# the bundles of a voucher: every batch line posted, returned or cancelled
	("Serial and Batch Bundle", "voucher_no", "ms_voucher_no"),
)


def add_core_indexes():
	for doctype, fieldname, index_name in CORE_INDEXES:
		table = f"tab{doctype}"
		# skip when any index already leads with the column: ERPNext may index it itself one day
		if not (frappe.db.get_column_index(table, fieldname) or frappe.db.get_column_index(table, fieldname, unique=True)):
			frappe.db.add_index(doctype, [fieldname], index_name=index_name)


def drop_core_indexes():
	for doctype, _fieldname, index_name in CORE_INDEXES:
		if frappe.db.has_index(f"tab{doctype}", index_name):
			frappe.db.sql_ddl(f"alter table `tab{doctype}` drop index `{index_name}`")
