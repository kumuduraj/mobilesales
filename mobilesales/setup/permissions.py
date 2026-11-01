"""Access for Mobile Sales Agents on standard DocTypes (spec §6.4).

Never shipped as Custom DocPerm fixtures: once any Custom DocPerm exists for a DocType, Frappe ignores
its standard DocPerms. frappe.permissions.add_permission first copies the standard rules into Custom
DocPerm (setup_custom_perms -> copy_perms) and then adds the Agent rule, so every existing role keeps
exactly its rights. Idempotent: the Agent rule is created once and its rights are re-asserted."""

import frappe
from frappe.permissions import add_permission, update_permission_property

AGENT_ROLE = "Mobile Sales Agent"
MANAGED_RIGHTS = ("select", "read", "print", "export", "report", "share", "email")

READ = {"read": 1}
# DocType -> rights of the Agent rule (every other right in MANAGED_RIGHTS is forced to 0)
AGENT_PERMISSIONS = {
	"Customer": READ,
	"Item": READ,
	"UOM": READ,
	"Price List": READ,
	"Item Price": READ,
	"Batch": READ,
	"Contact": READ,
	"Address": READ,
	"Territory": READ,
	"Customer Group": READ,
	"Sales Invoice": {"read": 1, "print": 1},
	"Payment Entry": {"read": 1, "print": 1},
	# ERPNext's get_party_account() checks the session user's select/read on the receivable account
	# while an agent's visit builds its invoice and payment; select only: no reading Account records.
	"Account": {"select": 1},
}
AGENT_READ_DOCTYPES = tuple(AGENT_PERMISSIONS)


def ensure_agent_permissions():
	for doctype, rights in AGENT_PERMISSIONS.items():
		rule = {"parent": doctype, "role": AGENT_ROLE, "permlevel": 0, "if_owner": 0}
		if not frappe.db.exists("Custom DocPerm", rule):
			add_permission(doctype, AGENT_ROLE, 0, next(iter(rights)))
		for right in MANAGED_RIGHTS:
			wanted = rights.get(right, 0)
			if (frappe.db.get_value("Custom DocPerm", rule, right) or 0) != wanted:
				update_permission_property(doctype, AGENT_ROLE, 0, right, wanted)
