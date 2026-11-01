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
INTERNAL_FLAG = "mobilesales_internal"
# Trip statuses in which app code may post each kind of mobile Stock Entry.
# Issue is posted from Mobile Trip.on_submit: trip already submitted, status still Draft.
PURPOSE_TRIP_STATUSES = {
	"Issue": ("Draft",),
	"Top-up": ("Loaded", "In Field"),
	"Return": ("Settling",),
	"Damage": ("Settling",),
	"Shortage": ("Settling",),
}


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


# Mobile Trip helpers


def _get_trip(doc) -> frappe._dict:
	trip = frappe.db.get_value(
		"Mobile Trip", doc.mobile_trip, ["name", "agent", "docstatus", "status", "van_warehouse"], as_dict=True
	)
	if not trip:
		frappe.throw(_("Mobile Trip {0} does not exist.").format(frappe.bold(doc.mobile_trip)))
	return trip


def _require_internal(doc, doctype_label):
	"""Mobile-tagged vouchers are only created by app code, never by hand via UI or API."""
	if not doc.flags.get(INTERNAL_FLAG):
		frappe.throw(
			_("{0} linked to a Mobile Trip can only be created by the Mobile Sales app.").format(
				_(doctype_label)
			),
			title=_("Mobile Sales"),
		)


def _require_trip_status(trip, allowed, doctype_label):
	if trip.docstatus != 1 or trip.status not in allowed:
		frappe.throw(
			_("{0} cannot be linked to Mobile Trip {1} while it is {2} (needs {3}).").format(
				_(doctype_label),
				frappe.bold(trip.name),
				_(trip.status),
				" / ".join(_(s) for s in allowed),
			),
			title=_("Mobile Sales: trip status"),
		)


def _require_trip_not_settled(trip, doctype_label):
	if trip.status == "Settled":
		frappe.throw(
			_("Mobile Trip {0} is Settled; {1} can no longer change.").format(
				frappe.bold(trip.name), _(doctype_label)
			),
			title=_("Mobile Sales: trip settled"),
		)


def _require_trip_van(trip, warehouses, doctype_label):
	other = set(warehouses) - {trip.van_warehouse}
	if other:
		frappe.throw(
			_("{0} for Mobile Trip {1} may only use van warehouse {2}, not {3}.").format(
				_(doctype_label),
				frappe.bold(trip.name),
				frappe.bold(trip.van_warehouse),
				", ".join(frappe.bold(w) for w in sorted(other)),
			),
			title=_("Mobile Sales: van warehouse"),
		)


# Handlers


def validate_sales_invoice(doc, method=None):
	ctx = _active_context()
	if not ctx:
		return
	used = _warehouses(doc, ("set_warehouse", "set_target_warehouse"), ("warehouse", "target_warehouse"))
	if not doc.get("mobile_trip"):
		vans = used & ctx["vans"]
		if vans:
			_throw_van("Sales Invoice", vans)
		return

	_require_internal(doc, "Sales Invoice")
	trip = _get_trip(doc)
	_require_trip_status(trip, ("In Field",), "Sales Invoice")
	_require_trip_van(trip, used, "Sales Invoice")


def before_cancel_sales_invoice(doc, method=None):
	if not doc.get("mobile_trip"):
		return
	_require_trip_not_settled(_get_trip(doc), "Sales Invoice")


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
	if not ctx:
		return
	vans = _warehouses(doc, ("from_warehouse", "to_warehouse"), ("s_warehouse", "t_warehouse")) & ctx["vans"]
	if not doc.get("mobile_trip"):
		if vans:
			_throw_van("Stock Entry", vans)
		return

	_require_internal(doc, "Stock Entry")
	trip = _get_trip(doc)
	allowed = PURPOSE_TRIP_STATUSES.get(doc.get("mobile_purpose"))
	if not allowed:
		frappe.throw(_("Mobile Purpose is required on a Stock Entry linked to a Mobile Trip."))
	_require_trip_status(trip, allowed, _("Stock Entry ({0})").format(_(doc.mobile_purpose)))
	_require_trip_van(trip, vans, "Stock Entry")


def validate_payment_entry(doc, method=None):
	ctx = _active_context()
	if not ctx:
		return
	if not doc.get("mobile_trip"):
		accounts = {doc.paid_to, doc.paid_from} & ctx["cash"]
		if accounts:
			_throw_cash("Payment Entry", accounts)
		return

	_require_internal(doc, "Payment Entry")
	trip = _get_trip(doc)
	_require_trip_not_settled(trip, "Payment Entry")
	agent_cash = frappe.db.get_value("Mobile Sales Agent", trip.agent, "cash_account")
	if doc.paid_to != agent_cash:
		frappe.throw(
			_("Payment Entry for Mobile Trip {0} must be paid to the agent cash account {1}.").format(
				frappe.bold(trip.name), frappe.bold(agent_cash)
			),
			title=_("Mobile Sales: agent cash account"),
		)


def validate_journal_entry(doc, method=None):
	ctx = _active_context()
	if not ctx:
		return
	if not doc.get("mobile_trip"):
		accounts = {row.account for row in doc.get("accounts") or []} & ctx["cash"]
		if accounts and SUPERVISOR_ROLE not in frappe.get_roles():
			_throw_cash("Journal Entry", accounts)
		return

	_require_internal(doc, "Journal Entry")
	_require_trip_not_settled(_get_trip(doc), "Journal Entry")
