"""Guard hooks on standard DocTypes (spec §5.2).

Van warehouses and agent cash accounts may only be used by documents tagged with a Mobile Trip.
Every handler first reads one cached context and returns at once when the app is not configured
or the document touches nothing mobile, so the standard sales path costs one cache lookup."""

import frappe
from frappe import _

from mobilesales.services import settings as ms_settings

CACHE_KEY = "mobilesales:guard_context"
SUPERVISOR_ROLE = "Mobile Sales Supervisor"
EMPTY_CONTEXT = {"van_group": None, "vans": frozenset(), "cash": frozenset()}


# Cached context


def get_guard_context() -> dict:
	return frappe.cache.get_value(CACHE_KEY, generator=build_guard_context)


def build_guard_context() -> dict:
	settings = ms_settings.get_settings()
	if not settings.van_warehouse_group:
		return EMPTY_CONTEXT

	vans = frozenset()
	bounds = frappe.db.get_value("Warehouse", settings.van_warehouse_group, ["lft", "rgt"])
	if bounds:
		lft, rgt = bounds
		vans = frozenset(
			frappe.get_all("Warehouse", filters={"lft": [">", lft], "rgt": ["<", rgt]}, pluck="name")
		)
	cash = frozenset(
		frappe.get_all("Mobile Sales Agent", filters={"cash_account": ["is", "set"]}, pluck="cash_account")
	)
	return {"van_group": settings.van_warehouse_group, "vans": vans, "cash": cash}


def clear_guard_cache(*args, **kwargs):
	frappe.cache.delete_value(CACHE_KEY)


def _active_context() -> dict | None:
	ctx = get_guard_context()
	if not ctx or not (ctx["vans"] or ctx["cash"]):
		return None
	return ctx


def on_warehouse_change(doc, method=None, *args):
	"""Invalidate when a warehouse enters, leaves or sits under the van group."""
	ctx = get_guard_context()
	if not ctx or not ctx["van_group"]:
		return
	before = doc.get_doc_before_save()
	parents = {doc.parent_warehouse, before.parent_warehouse if before else None}
	if (
		method == "after_rename"
		or doc.name in ctx["vans"]
		or ctx["van_group"] in parents
		or parents & ctx["vans"]
	):
		clear_guard_cache()


# Helpers


def _warehouses(doc, header_fields, row_fields, table="items") -> set:
	found = {doc.get(f) for f in header_fields}
	for row in doc.get(table) or []:
		found.update(row.get(f) for f in row_fields)
	found.discard(None)
	found.discard("")
	return found


def _throw_van(doctype_label, warehouses):
	frappe.throw(
		_(
			"Van warehouse {0} can only be used through Mobile Sales documents (Mobile Trip). "
			"{1} cannot use it directly."
		).format(", ".join(frappe.bold(w) for w in sorted(warehouses)), _(doctype_label)),
		title=_("Mobile Sales: van warehouse"),
	)


def _throw_cash(doctype_label, accounts):
	frappe.throw(
		_(
			"Agent cash account {0} can only be used through Mobile Sales documents (Mobile Trip). "
			"{1} cannot use it directly."
		).format(", ".join(frappe.bold(a) for a in sorted(accounts)), _(doctype_label)),
		title=_("Mobile Sales: agent cash account"),
	)


# Handlers


def validate_sales_invoice(doc, method=None):
	ctx = _active_context()
	if not ctx:
		return
	used = _warehouses(doc, ("set_warehouse", "set_target_warehouse"), ("warehouse", "target_warehouse"))
	vans = used & ctx["vans"]
	if not doc.get("mobile_trip"):
		if vans:
			_throw_van("Sales Invoice", vans)
		return
	_validate_trip_warehouse(doc, used)


def _validate_trip_warehouse(doc, used):
	# TODO(Phase 2): Mobile Trip gets van_warehouse and status; until then this check is skipped.
	# Also add before_cancel (no cancel once the trip is Settled) in Phase 2.
	if not frappe.get_meta("Mobile Trip").has_field("van_warehouse"):
		return
	trip_van = frappe.db.get_value("Mobile Trip", doc.mobile_trip, "van_warehouse")
	other = used - {trip_van}
	if other:
		frappe.throw(
			_("Mobile Sales Invoice must use only the trip van warehouse {0}, not {1}.").format(
				frappe.bold(trip_van), ", ".join(frappe.bold(w) for w in sorted(other))
			),
			title=_("Mobile Sales: van warehouse"),
		)


def validate_delivery_note(doc, method=None):
	ctx = _active_context()
	if not ctx:
		return
	vans = (
		_warehouses(doc, ("set_warehouse", "set_target_warehouse"), ("warehouse", "target_warehouse"))
		& ctx["vans"]
	)
	if vans:
		_throw_van("Delivery Note", vans)


def validate_stock_reconciliation(doc, method=None):
	ctx = _active_context()
	if not ctx:
		return
	vans = _warehouses(doc, ("set_warehouse",), ("warehouse",)) & ctx["vans"]
	if vans:
		_throw_van("Stock Reconciliation", vans)


def validate_stock_entry(doc, method=None):
	ctx = _active_context()
	if not ctx or doc.get("mobile_trip"):
		return
	vans = _warehouses(doc, ("from_warehouse", "to_warehouse"), ("s_warehouse", "t_warehouse")) & ctx["vans"]
	if vans:
		_throw_van("Stock Entry", vans)


def validate_payment_entry(doc, method=None):
	ctx = _active_context()
	if not ctx or doc.get("mobile_trip"):
		return
	accounts = {doc.paid_to, doc.paid_from} & ctx["cash"]
	if accounts:
		_throw_cash("Payment Entry", accounts)


def validate_journal_entry(doc, method=None):
	ctx = _active_context()
	if not ctx or doc.get("mobile_trip"):
		return
	accounts = {row.account for row in doc.get("accounts") or []} & ctx["cash"]
	if accounts and SUPERVISOR_ROLE not in frappe.get_roles():
		_throw_cash("Journal Entry", accounts)
