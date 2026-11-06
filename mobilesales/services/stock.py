"""Van stock: load-row checks, availability and Stock Entry builders for Mobile Trips (spec §4.1, §5.6)."""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt, get_datetime, getdate, nowdate, nowtime

from erpnext.stock.doctype.batch.batch import get_batch_qty
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
	check_chosen_batches(rows, source_warehouse, precision)
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


def batch_qty_map(warehouse, item_codes) -> dict:
	"""{(item, batch): qty} in the warehouse (submitted stock, every batch with stock)."""
	out = {}
	for item_code in set(item_codes):
		for b in get_batch_qty(warehouse=warehouse, item_code=item_code) or []:
			if flt(b.get("qty")):
				out[(item_code, b.get("batch_no"))] = flt(b.get("qty"))
	return out


def check_chosen_batches(rows, source_warehouse, precision):
	"""A batch chosen on a load / top-up row (batch items only; other items ignore the field): this item's,
	enabled, not expired, and holding at the source warehouse what every row choosing it needs. FIFO stays the
	default for rows without a batch (v1.0.2)."""
	needed = defaultdict(float)
	for idx, row in enumerate(rows, start=1):
		if not row.get("batch_no"):
			continue
		if not row.has_batch_no:
			row.batch_no = None
			continue
		batch = frappe.db.get_value("Batch", row.batch_no, ["item", "disabled", "expiry_date"], as_dict=True)
		if not batch or batch.item != row.item_code:
			frappe.throw(_("Row {0}: {1} is not a batch of {2}.").format(idx, frappe.bold(row.batch_no), frappe.bold(row.item_code)))
		if batch.disabled:
			frappe.throw(_("Row {0}: batch {1} is disabled.").format(idx, frappe.bold(row.batch_no)))
		if batch.expiry_date and getdate(batch.expiry_date) < getdate(nowdate()):
			frappe.throw(
				_("Row {0}: batch {1} expired on {2}.").format(idx, frappe.bold(row.batch_no), frappe.format(batch.expiry_date, "Date"))
			)
		needed[(row.item_code, row.batch_no)] += flt(row.stock_qty)
	if not needed:
		return
	available = batch_qty_map(source_warehouse, [item for item, _batch in needed])
	for row in rows:
		if row.get("batch_no"):
			row.available_at_source = available.get((row.item_code, row.batch_no), 0)
	for (item_code, batch_no), qty in needed.items():
		have = available.get((item_code, batch_no), 0)
		if flt(qty, precision) > flt(have, precision):
			frappe.throw(
				_("Batch {0} of {1}: {2} {3} available in {4}, the rows choosing it need {5}.").format(
					frappe.bold(batch_no),
					frappe.bold(item_code),
					flt(have, precision),
					frappe.get_cached_value("Item", item_code, "stock_uom"),
					frappe.bold(source_warehouse),
					flt(qty, precision),
				),
				title=_("Not enough in batch"),
			)


def batches_oldest_first(item_code, warehouse) -> list:
	"""[(batch, qty)] with stock in the warehouse, not expired, enabled, oldest first (manufacturing date, then
	creation): the load picker's order and the FIFO split below."""
	qty = {batch: q for (_item, batch), q in batch_qty_map(warehouse, [item_code]).items()}
	if not qty:
		return []
	today = getdate(nowdate())
	return [
		(b.name, qty[b.name], b)
		for b in frappe.get_all(
			"Batch",
			filters={"name": ["in", list(qty)], "disabled": 0},
			fields=["name", "expiry_date", "manufacturing_date", "creation"],
			order_by="manufacturing_date asc, creation asc, name asc",
		)
		if not b.expiry_date or getdate(b.expiry_date) >= today
	]


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def load_batch_query(doctype, txt, searchfield, start, page_len, filters):
	"""Batch picker of a load / top-up row: that item's enabled, unexpired batches with stock in the trip's
	source warehouse, oldest first: '<batch> · <qty> <uom> available · exp <date> · mfg <date>'."""
	filters = frappe._dict(filters or {})
	if not (filters.item_code and filters.warehouse) or not frappe.has_permission("Batch", "read"):
		return []
	uom = frappe.get_cached_value("Item", filters.item_code, "stock_uom")
	out = []
	for batch_no, qty, b in batches_oldest_first(filters.item_code, filters.warehouse):
		if txt and txt.lower() not in batch_no.lower():
			continue
		parts = [f"{flt(qty, 3):g} {uom} " + _("available")]
		if b.expiry_date:
			parts.append(_("exp {0}").format(frappe.format(b.expiry_date, "Date")))
		if b.manufacturing_date:
			parts.append(_("mfg {0}").format(frappe.format(b.manufacturing_date, "Date")))
		out.append((batch_no, " · ".join(parts)))
	return out[int(start or 0) : int(start or 0) + int(page_len or 20)]


def transfer_rows(rows, source):
	"""Stock Entry rows for a load / top-up. A chosen batch goes on its row (ERPNext bundles exactly that
	batch); other rows keep ERPNext's automatic FIFO bundle. When an item has both, the FIFO quantity is split
	here, oldest batch first, over what the chosen rows leave, so one entry never takes a batch twice."""
	chosen = defaultdict(float)
	for row in rows:
		if row.get("batch_no"):
			chosen[(row.item_code, row.batch_no)] += flt(row.stock_qty) or flt(row.qty) * flt(row.conversion_factor or 1)
	mixed = {item for item, _batch in chosen}
	left = {}
	out = []
	for row in rows:
		base = {"item_code": row.item_code, "uom": row.uom, "conversion_factor": flt(row.conversion_factor) or 1}
		if row.get("batch_no"):
			out.append({**base, "qty": flt(row.qty), "batch_no": row.batch_no, "use_serial_batch_fields": 1})
			continue
		if row.item_code not in mixed:
			out.append({**base, "qty": flt(row.qty)})
			continue
		if row.item_code not in left:
			left[row.item_code] = [
				[batch, qty - chosen.get((row.item_code, batch), 0)] for batch, qty, _b in batches_oldest_first(row.item_code, source)
			]
		need = flt(row.stock_qty) or flt(row.qty) * base["conversion_factor"]
		for pair in left[row.item_code]:
			if need <= 1e-9:
				break
			take = min(pair[1], need)
			if take <= 1e-9:
				continue
			pair[1] -= take
			need -= take
			out.append({**base, "qty": take / base["conversion_factor"], "batch_no": pair[0], "use_serial_batch_fields": 1})
		if need > 1e-6:
			frappe.throw(_("Not enough unexpired batches of {0} left in {1} for the rows without a batch.").format(
				frappe.bold(row.item_code), frappe.bold(source)))  # fmt: skip
	return out


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


def lock_bin_qty(warehouse, item_codes) -> dict:
	"""Bin actual_qty with row locks (SELECT ... FOR UPDATE) so two parallel visits cannot both
	sell the last units: the second waits, then sees the reduced quantity."""
	if not item_codes:
		return {}
	return dict(
		frappe.db.sql(
			"""select item_code, actual_qty from `tabBin`
			where warehouse = %s and item_code in %s for update""",
			(warehouse, tuple(item_codes)),
		)
	)


def warehouse_has_stock(warehouse) -> bool:
	return bool(frappe.db.exists("Bin", {"warehouse": warehouse, "actual_qty": ["!=", 0]}))


def make_transfer(trip, rows, purpose, source, target, posting_date=None):
	"""Submit a Material Transfer tagged with the trip. Batches: the row's chosen batch, else automatic FIFO."""
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
	for row in transfer_rows(rows, source):
		se.append("items", {**row, "s_warehouse": source, "t_warehouse": target})
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
