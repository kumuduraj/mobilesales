"""Scripted permissions (hooks permission_query_conditions / has_permission).

Only users whose sole Mobile Sales role is Agent are restricted; everyone else falls through
to standard role permissions. In v16 a has_permission hook returning a falsy value denies,
so the unrestricted path must return True explicitly."""

import frappe

AGENT_ROLE = "Mobile Sales Agent"
UNRESTRICTED_ROLES = {
	"System Manager",
	"Mobile Sales Supervisor",
	"Mobile Sales Store Keeper",
	"Mobile Sales Cashier",
}
# Sales Invoice / Payment Entry / Customer Visit scope: an agent who also works in accounts or sales
# keeps the standard view of these documents.
VOUCHER_UNRESTRICTED_ROLES = UNRESTRICTED_ROLES | {
	"Accounts Manager",
	"Accounts User",
	"Sales Manager",
	"Sales User",
}


COLLECTABLE_FLAG = "mobilesales_collectable_invoices"


def collectable_invoices() -> frozenset:
	"""Invoices the current request may read while a Customer Visit posts its Payment Entry.
	Set only by services.visit for the invoices that visit already validated; never by user input."""
	return frappe.flags.get(COLLECTABLE_FLAG) or frozenset()


def is_restricted_agent(user: str | None = None, unrestricted_roles=UNRESTRICTED_ROLES) -> bool:
	user = user or frappe.session.user
	if user == "Administrator":
		return False
	roles = set(frappe.get_roles(user))
	return AGENT_ROLE in roles and not roles & unrestricted_roles


def agent_query_conditions(user: str | None = None) -> str:
	user = user or frappe.session.user
	if not is_restricted_agent(user):
		return ""
	return f"`tabMobile Sales Agent`.`user` = {frappe.db.escape(user)}"


def agent_has_permission(doc, ptype: str | None = None, user: str | None = None) -> bool:
	user = user or frappe.session.user
	if not is_restricted_agent(user):
		return True
	return doc.user == user


def _own_agents_sql(user: str) -> str:
	return f"(select `name` from `tabMobile Sales Agent` where `user` = {frappe.db.escape(user)})"


def _own_trips_sql(user: str) -> str:
	return f"(select `name` from `tabMobile Trip` where `agent` in {_own_agents_sql(user)})"


def _agent_user(agent: str | None) -> str | None:
	return agent and frappe.db.get_value("Mobile Sales Agent", agent, "user")


def trip_query_conditions(user: str | None = None) -> str:
	user = user or frappe.session.user
	if not is_restricted_agent(user):
		return ""
	return f"`tabMobile Trip`.`agent` in {_own_agents_sql(user)}"


def trip_has_permission(doc, ptype: str | None = None, user: str | None = None) -> bool:
	user = user or frappe.session.user
	if not is_restricted_agent(user):
		return True
	return bool(doc.agent) and _agent_user(doc.agent) == user


def visit_query_conditions(user: str | None = None) -> str:
	user = user or frappe.session.user
	if not is_restricted_agent(user, VOUCHER_UNRESTRICTED_ROLES):
		return ""
	return f"`tabCustomer Visit`.`agent` in {_own_agents_sql(user)}"


def visit_has_permission(doc, ptype: str | None = None, user: str | None = None) -> bool:
	user = user or frappe.session.user
	if not is_restricted_agent(user, VOUCHER_UNRESTRICTED_ROLES):
		return True
	agent = doc.get("agent") or (
		doc.get("mobile_trip") and frappe.db.get_value("Mobile Trip", doc.mobile_trip, "agent")
	)
	if not agent:
		# A new visit without a trip yet: validate() enforces the trip's agent on save.
		return doc.is_new()
	return _agent_user(agent) == user


def sales_invoice_query_conditions(user: str | None = None) -> str:
	return _mobile_voucher_conditions("Sales Invoice", user)


def payment_entry_query_conditions(user: str | None = None) -> str:
	return _mobile_voucher_conditions("Payment Entry", user)


def _mobile_voucher_conditions(doctype: str, user: str | None) -> str:
	"""Restricted agents see only invoices / payments of their own trips; everyone else: no change."""
	user = user or frappe.session.user
	if not is_restricted_agent(user, VOUCHER_UNRESTRICTED_ROLES):
		return ""
	return f"`tab{doctype}`.`mobile_trip` in {_own_trips_sql(user)}"


def mobile_voucher_has_permission(doc, ptype: str | None = None, user: str | None = None) -> bool:
	user = user or frappe.session.user
	if not is_restricted_agent(user, VOUCHER_UNRESTRICTED_ROLES):
		return True
	if ptype in (None, "read", "select") and doc.get("name") in collectable_invoices():
		return True
	trip = doc.get("mobile_trip")
	return bool(trip) and _agent_user(frappe.db.get_value("Mobile Trip", trip, "agent")) == user


def settlement_query_conditions(user: str | None = None) -> str:
	user = user or frappe.session.user
	if not is_restricted_agent(user):
		return ""
	return f"`tabMobile Settlement`.`agent` in {_own_agents_sql(user)}"


def settlement_has_permission(doc, ptype: str | None = None, user: str | None = None) -> bool:
	user = user or frappe.session.user
	if not is_restricted_agent(user):
		return True
	agent = doc.get("agent") or (
		doc.get("mobile_trip") and frappe.db.get_value("Mobile Trip", doc.mobile_trip, "agent")
	)
	if not agent:
		return doc.is_new()
	return _agent_user(agent) == user
