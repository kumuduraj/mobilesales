"""Mobile Trip lifecycle (spec §4.1, §5.5): validation, submit/cancel postings and status actions.

Draft -> (submit) Loaded -> (start_trip) In Field -> (end_day) Settling -> (settlement) Settled.
Cancel only from Loaded with no submitted visits."""

import frappe
from frappe import _
from frappe.utils import flt, nowdate

from mobilesales.overrides import guards
from mobilesales.services import settings as ms_settings
from mobilesales.services import stock

CLOSED_STATUSES = ("Settled", "Cancelled")
SUPERVISOR_ROLES = ("Mobile Sales Supervisor", "System Manager")
TOP_UP_ROLES = ("Mobile Sales Supervisor", "Mobile Sales Store Keeper", "System Manager")


# Document events


def validate_trip(trip):
	settings = ms_settings.get_settings()
	if not settings.company:
		frappe.throw(_("Set Company in Mobile Sales Settings first."))

	agent = frappe.db.get_value(
		"Mobile Sales Agent",
		trip.agent,
		["is_active", "van_warehouse", "cash_account", "default_route"],
		as_dict=True,
	)
	if not agent.is_active:
		frappe.throw(_("Mobile Sales Agent {0} is not active.").format(frappe.bold(trip.agent)))
	if not (agent.van_warehouse and agent.cash_account):
		frappe.throw(
			_(
				"Mobile Sales Agent {0} is not set up yet. Use 'Create Van Warehouse & Cash Account' "
				"on the agent first."
			).format(frappe.bold(trip.agent))
		)

	if trip.docstatus == 0:
		trip.status = "Draft"
	trip.company = settings.company
	trip.van_warehouse = agent.van_warehouse
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
	other = frappe.db.get_value(
		"Mobile Trip",
		{
			"agent": trip.agent,
			"name": ["!=", trip.name],
			"docstatus": ["<", 2],
			"status": ["not in", CLOSED_STATUSES],
		},
		"name",
	)
	if other:
		frappe.throw(
			_("Agent {0} already has an open trip {1}. Settle or cancel it first.").format(
				frappe.bold(trip.agent), frappe.bold(other)
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
	if trip.opening_float_journal:
		_cancel_if_submitted("Journal Entry", trip.opening_float_journal)
	for row in reversed(trip.stock_entries):
		_cancel_if_submitted("Stock Entry", row.stock_entry)
	trip.db_set("status", "Cancelled")


def _cancel_if_submitted(doctype, name):
	doc = frappe.get_doc(doctype, name)
	if doc.docstatus == 1:
		doc.flags.ignore_permissions = True
		doc.cancel()


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
	doc.db_set("status", "Settling")
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
