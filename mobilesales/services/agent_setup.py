"""Per-agent setup (spec §3.2): cash ledger, mode of payment, sales person, user permissions and role.
The van warehouse belongs to the Mobile Vehicle (services/vehicles.py). Idempotent: every part is
skipped or reused when it already exists."""

import frappe
from frappe import _
from frappe.utils import cint

from mobilesales.services import settings as ms_settings

AGENT_ROLE = "Mobile Sales Agent"
SETUP_ROLES = ("Mobile Sales Supervisor", "System Manager")
SCOPED_DOCTYPES = ("Mobile Trip", "Customer Visit", "Mobile Settlement")
REQUIRED_SETTINGS = ("company", "agent_cash_parent_account", "sales_person_parent")


@frappe.whitelist()
def setup_agent(agent: str) -> dict:
	frappe.only_for(SETUP_ROLES)

	doc = frappe.get_doc("Mobile Sales Agent", agent)
	settings = ms_settings.get_settings()
	check_settings(settings)

	changed = False
	for fieldname, ensure in (
		("cash_account", ensure_cash_account),
		("mode_of_payment", ensure_mode_of_payment),
		("sales_person", ensure_sales_person),
	):
		if not doc.get(fieldname):
			doc.set(fieldname, ensure(doc, settings))
			changed = True
	ensure_user_permissions(doc)
	ensure_agent_role(doc.user)

	if changed:
		doc.save()

	return {
		"cash_account": doc.cash_account,
		"mode_of_payment": doc.mode_of_payment,
		"sales_person": doc.sales_person,
	}


def check_settings(settings):
	missing = [settings.meta.get_label(f) for f in REQUIRED_SETTINGS if not settings.get(f)]
	if missing:
		frappe.throw(
			_("Set {0} in Mobile Sales Settings first.").format(", ".join(_(m) for m in missing)),
			title=_("Mobile Sales Settings incomplete"),
		)


def ensure_cash_account(agent, settings) -> str:
	account_name = f"Cash in Hand - {agent.agent_name}"
	existing = frappe.db.get_value(
		"Account",
		{
			"account_name": account_name,
			"parent_account": settings.agent_cash_parent_account,
			"company": settings.company,
		},
	)
	if existing:
		return existing

	return (
		frappe.get_doc(
			{
				"doctype": "Account",
				"account_name": account_name,
				"account_number": next_account_number(settings.agent_cash_parent_account, settings.company),
				"parent_account": settings.agent_cash_parent_account,
				"company": settings.company,
				"account_type": "Cash",
				"is_group": 0,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def next_account_number(parent_account: str, company: str) -> str | None:
	"""Highest numeric account_number among the parent's children + 1, skipping numbers
	already used elsewhere in the company. None when no sibling is numbered."""
	numbers = frappe.get_all(
		"Account",
		filters={"parent_account": parent_account, "company": company},
		pluck="account_number",
	)
	numeric = [cint(n) for n in numbers if n and str(n).strip().isdigit()]
	if not numeric:
		return None

	candidate = max(numeric) + 1
	while frappe.db.exists("Account", {"account_number": str(candidate), "company": company}):
		candidate += 1
	return str(candidate)


def ensure_mode_of_payment(agent, settings) -> str:
	name = f"Mobile Cash - {agent.agent_name}"
	if frappe.db.exists("Mode of Payment", name):
		mop = frappe.get_doc("Mode of Payment", name)
	else:
		mop = frappe.get_doc({"doctype": "Mode of Payment", "mode_of_payment": name, "type": "Cash", "enabled": 1})

	if not any(row.company == settings.company for row in mop.accounts):
		mop.append("accounts", {"company": settings.company, "default_account": agent.cash_account})
		mop.save(ignore_permissions=True)
	return mop.name


def ensure_sales_person(agent, settings) -> str:
	if frappe.db.exists("Sales Person", agent.agent_name):
		return agent.agent_name

	return (
		frappe.get_doc(
			{
				"doctype": "Sales Person",
				"sales_person_name": agent.agent_name,
				"parent_sales_person": settings.sales_person_parent,
				"is_group": 0,
				"enabled": 1,
				"employee": agent.employee,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def ensure_user_permissions(agent):
	for doctype in SCOPED_DOCTYPES:
		values = {
			"user": agent.user,
			"allow": "Mobile Sales Agent",
			"for_value": agent.name,
			"applicable_for": doctype,
		}
		if not frappe.db.exists("User Permission", values):
			frappe.get_doc({"doctype": "User Permission", "apply_to_all_doctypes": 0, **values}).insert(
				ignore_permissions=True
			)


def ensure_agent_role(user: str):
	if user == "Administrator" or AGENT_ROLE in frappe.get_roles(user):
		return
	user_doc = frappe.get_doc("User", user)
	user_doc.flags.ignore_permissions = True
	user_doc.add_roles(AGENT_ROLE)
