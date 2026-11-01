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


def is_restricted_agent(user: str | None = None) -> bool:
	user = user or frappe.session.user
	if user == "Administrator":
		return False
	roles = set(frappe.get_roles(user))
	return AGENT_ROLE in roles and not roles & UNRESTRICTED_ROLES


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


def trip_query_conditions(user: str | None = None) -> str:
	user = user or frappe.session.user
	if not is_restricted_agent(user):
		return ""
	return (
		"`tabMobile Trip`.`agent` in "
		f"(select `name` from `tabMobile Sales Agent` where `user` = {frappe.db.escape(user)})"
	)


def trip_has_permission(doc, ptype: str | None = None, user: str | None = None) -> bool:
	user = user or frappe.session.user
	if not is_restricted_agent(user):
		return True
	return bool(doc.agent) and frappe.db.get_value("Mobile Sales Agent", doc.agent, "user") == user
