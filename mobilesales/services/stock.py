"""Van stock: load-row checks, availability and Stock Entry builders for Mobile Trips (spec §4.1, §5.6)."""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt, get_datetime, nowdate, nowtime

from erpnext.stock.get_item_details import get_conversion_factor

from mobilesales.overrides.guards import INTERNAL_FLAG

AUTO_BUNDLE_FIELD = "auto_create_serial_and_batch_bundle_for_outward"


def prepare_load_rows(rows, source_warehouse):
	"""Fill uom, conversion_factor, stock_qty and available_at_source on load rows (child docs or
	frappe._dict) and check stock items, qty > 0 and availability at the source warehouse."""
	if not rows:
		frappe.throw(_("Add at least one item to load."))

	precision = frappe.get_precision("Mobile Trip Load Item", "stock_qty")
	needed = defaultdict(float)
	has_batch = False
	for idx, row in enumerate(rows, start=1):
		item = frappe.get_cached_value(
			"Item",
			row.item_code,
			["item_name", "is_stock_item", "stock_uom", "has_batch_no", "disabled"],
			as_dict=True,
		)
		if not item:
			frappe.throw(_("Row {0}: Item {1} does not exist.").format(idx, frappe.bold(row.item_code)))
		if item.disabled or not item.is_stock_item:
			frappe.throw(
				_("Row {0}: {1} is not an enabled stock item.").format(idx, frappe.bold(row.item_code))
			)
		if flt(row.qty) <= 0:
			frappe.throw(_("Row {0}: Qty must be greater than 0.").format(idx))

		row.item_name = item.item_name
		row.stock_uom = item.stock_uom
		row.has_batch_no = item.has_batch_no
		row.uom = row.uom or item.stock_uom
		if row.uom != item.stock_uom and not frappe.db.exists(
			"UOM Conversion Detail", {"parent": row.item_code, "uom": row.uom}
		):
			frappe.throw(
				_("Row {0}: UOM {1} has no conversion factor on Item {2}.").format(
					idx, frappe.bold(row.uom), frappe.bold(row.item_code)
				)
			)
		row.conversion_factor = flt(get_conversion_factor(row.item_code, row.uom)["conversion_factor"])
		row.stock_qty = flt(flt(row.qty) * row.conversion_factor, precision)
		needed[row.item_code] += row.stock_qty
		has_batch = has_batch or bool(item.has_batch_no)

	available = get_bin_qty_map(source_warehouse, list(needed))
	for row in rows:
		row.available_at_source = available.get(row.item_code, 0)
	for item_code, qty in needed.items():
		if flt(qty, precision) > flt(available.get(item_code, 0), precision):
			frappe.throw(
				_("Insufficient stock of {0} in {1}: need {2}, available {3}.").format(
					frappe.bold(item_code),
					frappe.bold(source_warehouse),
					flt(qty, precision),
					flt(available.get(item_code, 0), precision),
				),
				title=_("Insufficient stock"),
			)

	if has_batch:
		check_auto_batch_bundle()


def check_auto_batch_bundle():
	if not frappe.db.get_single_value("Stock Settings", AUTO_BUNDLE_FIELD):
		frappe.throw(
			_(
				"Batch-tracked items need Stock Settings > 'Auto Create Serial and Batch Bundle For Outward' "
				"to be enabled. Turn it on, then load the trip again."
			),
			title=_("Stock Settings"),
		)


def get_bin_qty_map(warehouse, item_codes) -> dict:
	if not item_codes:
		return {}
	return dict(
		frappe.get_all(
			"Bin",
			filters={"warehouse": warehouse, "item_code": ["in", item_codes]},
			fields=["item_code", "actual_qty"],
			as_list=True,
		)
	)


def warehouse_has_stock(warehouse) -> bool:
	return bool(frappe.db.exists("Bin", {"warehouse": warehouse, "actual_qty": ["!=", 0]}))


def make_transfer(trip, rows, purpose, source, target, posting_date=None):
	"""Submit a Material Transfer tagged with the trip. Batches are bundled automatically (FIFO)."""
	se = frappe.new_doc("Stock Entry")
	se.stock_entry_type = "Material Transfer"
	se.purpose = "Material Transfer"
	se.company = trip.company
	se.set_posting_time = 1
	se.posting_date = posting_date or nowdate()
	se.posting_time = nowtime()
	se.from_warehouse = source
	se.to_warehouse = target
	se.mobile_trip = trip.name
	se.mobile_purpose = purpose
	se.remarks = _("Mobile Trip {0}: {1}").format(trip.name, _(purpose))
	for row in rows:
		se.append(
			"items",
			{
				"item_code": row.item_code,
				"qty": row.qty,
				"uom": row.uom,
				"conversion_factor": row.conversion_factor,
				"s_warehouse": source,
				"t_warehouse": target,
			},
		)
	se.flags.ignore_permissions = True
	se.flags[INTERNAL_FLAG] = True
	se.insert()
	se.submit()
	return se


def link_stock_entry(trip, se, purpose):
	row = trip.append(
		"stock_entries",
		{
			"stock_entry": se.name,
			"purpose": purpose,
			"posting_datetime": get_datetime(f"{se.posting_date} {se.posting_time}"),
		},
	)
	row.db_insert()
	return row
