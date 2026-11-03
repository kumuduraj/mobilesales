"""Mobile Trip lifecycle (spec §4.1, §5.5): validation, submit/cancel postings and status actions.

Draft -> (submit) Loaded -> (start_trip) In Field -> (end_day) Settling -> (settlement) Settled.
Settling -> (reopen_trip, no settlement past workflow Draft) In Field.
Cancel only from Loaded with no submitted visits."""

import frappe
from frappe import _
from frappe.utils import flt, nowdate

from mobilesales.overrides import guards
from mobilesales.services import settings as ms_settings
from mobilesales.services import stock, vouchers

CLOSED_STATUSES = ("Settled", "Cancelled")
SUPERVISOR_ROLES = ("Mobile Sales Supervisor", "System Manager")
TOP_UP_ROLES = ("Mobile Sales Supervisor", "Mobile Sales Store Keeper", "System Manager")


# Document events


# Set by the app only (db_set, link_stock_entry, update_trip_summary): kept as stored on update after submit.
SYSTEM_FIELDS = (
	"status", "opening_float_journal", "stock_entries", "visits", "sales_visits", "no_sale_visits", "invoices",
	"invoiced_amount", "collected_amount", "settlement",
)  # fmt: skip


def validate_trip(trip):
	settings = ms_settings.get_settings()
	# validate runs before submit only: postings are made on submit, never typed in or kept by an amendment
	trip.set("stock_entries", [])
	trip.opening_float_journal = None
	trip.settlement = None
	if not settings.company:
		frappe.throw(_("Set Company in Mobile Sales Settings first."))

	agent = frappe.db.get_value(
		"Mobile Sales Agent",
		trip.agent,
		["is_active", "cash_account", "default_route", "default_vehicle"],
		as_dict=True,
	)
	if not agent.is_active:
		frappe.throw(_("Mobile Sales Agent {0} is not active.").format(frappe.bold(trip.agent)))
	if not agent.cash_account:
		frappe.throw(
			_("Mobile Sales Agent {0} is not set up yet. Use 'Create Cash Account' on the agent first.").format(
				frappe.bold(trip.agent)
			)
		)
	trip.vehicle = trip.vehicle or agent.default_vehicle
	if not trip.vehicle:
		frappe.throw(_("Select the Vehicle for this trip (or set a Default Vehicle on the agent)."))
	vehicle = frappe.db.get_value("Mobile Vehicle", trip.vehicle, ["is_active", "van_warehouse"], as_dict=True)
	if not vehicle:
		frappe.throw(_("Mobile Vehicle {0} not found.").format(frappe.bold(trip.vehicle)))
	if trip.docstatus == 0 and not vehicle.is_active:
		frappe.throw(_("Mobile Vehicle {0} is not active.").format(frappe.bold(trip.vehicle)))
	if not vehicle.van_warehouse:
		frappe.throw(
			_("Mobile Vehicle {0} has no van warehouse yet. Use 'Create Van Warehouse' on the vehicle first.").format(
				frappe.bold(trip.vehicle)
			)
		)

	if trip.docstatus == 0:
		trip.status = "Draft"
	trip.company = settings.company
	trip.van_warehouse = vehicle.van_warehouse
	trip.source_warehouse = trip.source_warehouse or settings.source_warehouse
	trip.route = trip.route or agent.default_route
	if not trip.source_warehouse:
		frappe.throw(_("Set Source Warehouse on the trip or in Mobile Sales Settings."))
	if trip.source_warehouse in guards.get_guard_context()["vans"]:
		frappe.throw(
			_("Source Warehouse {0} is a van warehouse.").format(frappe.bold(trip.source_warehouse))
		)

	validate_single_open_trip(trip)
	stock.prepare_load_rows(trip.load_items, trip.source_warehouse)


def validate_single_open_trip(trip):
	"""One open trip per agent and one per vehicle (spec §3.6)."""
	for fieldname, label in (("agent", _("Agent")), ("vehicle", _("Vehicle"))):
		other = frappe.db.get_value(
			"Mobile Trip",
			{
				fieldname: trip.get(fieldname),
				"name": ["!=", trip.name],
				"docstatus": ["<", 2],
				"status": ["not in", CLOSED_STATUSES],
			},
			"name",
		)
		if other:
			frappe.throw(
				_("{0} {1} already has an open trip {2}. Settle or cancel it first.").format(
					label, frappe.bold(trip.get(fieldname)), frappe.bold(other)
				),
				title=_("Open trip exists"),
			)


def before_submit(trip):
	if stock.warehouse_has_stock(trip.van_warehouse):
		frappe.throw(
			_("Previous trip not settled: van {0} still holds stock.").format(frappe.bold(trip.van_warehouse)),
			title=_("Van not empty"),
		)


def on_submit(trip):
	se = stock.make_transfer(
		trip, trip.load_items, "Issue", trip.source_warehouse, trip.van_warehouse, posting_date=trip.trip_date
	)
	stock.link_stock_entry(trip, se, "Issue")
	if flt(trip.opening_cash_float) > 0:
		trip.db_set("opening_float_journal", make_opening_float_journal(trip).name)
	trip.db_set("status", "Loaded")


def make_opening_float_journal(trip):
	settings = ms_settings.get_settings()
	if not settings.main_cash_account:
		frappe.throw(_("Set Main Cash Account in Mobile Sales Settings to post an opening cash float."))
	agent_cash = frappe.db.get_value("Mobile Sales Agent", trip.agent, "cash_account")
	amount = flt(trip.opening_cash_float, trip.precision("opening_cash_float"))

	je = frappe.new_doc("Journal Entry")
	je.voucher_type = "Journal Entry"
	je.company = trip.company
	je.posting_date = trip.trip_date
	je.mobile_trip = trip.name
	je.user_remark = _("Opening cash float for Mobile Trip {0}").format(trip.name)
	je.append("accounts", {"account": agent_cash, "debit_in_account_currency": amount})
	je.append("accounts", {"account": settings.main_cash_account, "credit_in_account_currency": amount})
	je.flags.ignore_permissions = True
	je.flags[stock.INTERNAL_FLAG] = True
	je.insert()
	je.submit()
	return je


def before_cancel(trip):
	if trip.status != "Loaded":
		frappe.throw(
			_("Only a Loaded trip can be cancelled; {0} is {1}.").format(trip.name, _(trip.status)),
			title=_("Cannot cancel"),
		)
	if frappe.db.exists("Customer Visit", {"mobile_trip": trip.name, "docstatus": 1}):
		frappe.throw(_("Trip {0} has submitted Customer Visits and cannot be cancelled.").format(trip.name))


def on_cancel(trip):
	"""Runs after the trip row is cancelled and before Frappe's back-link check."""
	vouchers.cancel_linked("Journal Entry", trip.opening_float_journal, mobile_trip=trip.name)
	for row in reversed(trip.stock_entries):
		vouchers.cancel_linked("Stock Entry", row.stock_entry, mobile_trip=trip.name)
	trip.db_set("status", "Cancelled")


def update_trip_summary(trip_name):
	"""Recompute the trip summary from submitted documents (never incremented)."""
	outcomes = frappe.get_all(
		"Customer Visit", filters={"mobile_trip": trip_name, "docstatus": 1}, pluck="outcome"
	)
	invoiced = frappe.get_all(
		"Sales Invoice", filters={"mobile_trip": trip_name, "docstatus": 1, "is_return": 0}, pluck="grand_total"
	)
	collected = frappe.get_all(
		"Payment Entry", filters={"mobile_trip": trip_name, "docstatus": 1}, pluck="paid_amount"
	)
	frappe.db.set_value(
		"Mobile Trip",
		trip_name,
		{
			"visits": len(outcomes),
			"sales_visits": outcomes.count("Sale"),
			"no_sale_visits": sum(1 for o in outcomes if o in ("No Sale", "Shop Closed")),
			"invoices": len(invoiced),
			"invoiced_amount": sum(flt(v) for v in invoiced),
			"collected_amount": sum(flt(v) for v in collected),
		},
		update_modified=False,
	)


# Whitelisted status actions


@frappe.whitelist()
def start_trip(trip: str) -> str:
	doc = _lock(trip)
	_require_agent_or_roles(doc, SUPERVISOR_ROLES)
	_require_status(doc, ("Loaded",))
	doc.db_set("status", "In Field")
	return doc.status


@frappe.whitelist()
def end_day(trip: str) -> str:
	doc = _lock(trip)
	_require_agent_or_roles(doc, SUPERVISOR_ROLES)
	_require_status(doc, ("In Field",))
	drafts = frappe.get_all("Customer Visit", filters={"mobile_trip": doc.name, "docstatus": 0}, pluck="name")
	if drafts:
		frappe.throw(
			_("Submit or delete the draft visits first: {0}").format(", ".join(drafts)),
			title=_("Draft visits open"),
		)
	doc.db_set("status", "Settling")
	return doc.status


@frappe.whitelist()
def reopen_trip(trip: str) -> str:
	"""Settling -> In Field (End Day pressed too early). Only while the settlement is not started or still a
	workflow Draft; that draft is deleted. From Pending Store on, a supervisor must Reject it to Draft first."""
	doc = _lock(trip)
	_require_agent_or_roles(doc, SUPERVISOR_ROLES)
	_require_status(doc, ("Settling",))
	drafts = []
	for row in frappe.get_all(
		"Mobile Settlement",
		filters={"mobile_trip": doc.name, "docstatus": ["<", 2]},
		fields=["name", "docstatus", "workflow_state"],
	):
		state = row.workflow_state or "Draft"
		if row.docstatus != 0 or state != "Draft":
			frappe.throw(
				_("Settlement {0} is {1}; a supervisor must reject it to Draft before the trip can be reopened.").format(
					frappe.bold(row.name), _(state)
				),
				title=_("Settlement in progress"),
			)
		drafts.append(row.name)
	for name in drafts:
		frappe.delete_doc("Mobile Settlement", name, ignore_permissions=True)
	doc.db_set("status", "In Field")
	doc.add_comment(
		"Info",
		_("Trip reopened by {0}").format(frappe.session.user)
		+ (_("; draft settlement {0} deleted").format(", ".join(drafts)) if drafts else ""),
	)
	return doc.status


@frappe.whitelist()
def top_up(trip: str, items: str | list) -> str:
	doc = _lock(trip)
	frappe.only_for(TOP_UP_ROLES)
	_require_status(doc, ("Loaded", "In Field"))

	rows = [frappe._dict(row) for row in frappe.parse_json(items) or []]
	stock.prepare_load_rows(rows, doc.source_warehouse)
	se = stock.make_transfer(doc, rows, "Top-up", doc.source_warehouse, doc.van_warehouse, posting_date=nowdate())
	stock.link_stock_entry(doc, se, "Top-up")
	return se.name


def _lock(name):
	return frappe.get_doc("Mobile Trip", name, for_update=True)


def is_trip_agent(trip, user=None) -> bool:
	user = user or frappe.session.user
	return frappe.db.get_value("Mobile Sales Agent", trip.agent, "user") == user


def _require_agent_or_roles(trip, roles):
	if is_trip_agent(trip) or set(roles) & set(frappe.get_roles()):
		return
	frappe.throw(_("Only the trip's agent or a supervisor can do this."), frappe.PermissionError)


def _require_status(trip, allowed):
	if trip.docstatus != 1 or trip.status not in allowed:
		frappe.throw(
			_("Trip {0} is {1}; this action needs status {2}.").format(
				trip.name, _(trip.status), " / ".join(_(s) for s in allowed)
			),
			title=_("Wrong trip status"),
		)
