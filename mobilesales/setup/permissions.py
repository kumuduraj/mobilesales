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


def check_standard_permission_drift() -> list[str]:
	"""After an ERPNext upgrade the standard DocPerms may change, but the Custom DocPerm copies made by
	add_permission keep the old rules. Report (never fix) every DocType whose copy no longer matches the
	standard rules for any role other than the Agent. Returns the drifted DocTypes."""
	rights = ["permlevel", *(df.fieldname for df in frappe.get_meta("DocPerm").fields if df.fieldtype == "Check")]

	def rules(doctype, source):
		rows = frappe.get_all(source, filters={"parent": doctype, "role": ["!=", AGENT_ROLE]}, fields=["role", *rights])
		return {(row.role, row.permlevel, row.if_owner): {r: row.get(r) or 0 for r in rights} for row in rows}

	drifted = []
	for doctype in AGENT_PERMISSIONS:
		if not frappe.db.exists("Custom DocPerm", {"parent": doctype}):
			continue
		standard, custom = rules(doctype, "DocPerm"), rules(doctype, "Custom DocPerm")
		differences = []
		for key in sorted(set(standard) | set(custom)):
			if standard.get(key) != custom.get(key):
				role, level, if_owner = key
				owner = ", if owner" if if_owner else ""
				differences.append(
					f"{role} (level {level}{owner}): standard {standard.get(key)} / custom {custom.get(key)}"
				)
		if not differences:
			continue
		drifted.append(doctype)
		title = f"mobilesales: standard permissions changed for {doctype}, review Custom DocPerm"
		print(title)
		frappe.log_error(
			title=title,
			message=title
			+ "\n\nThe Custom DocPerm copy no longer matches the standard DocPerm (Mobile Sales Agent ignored). "
			"mobilesales did not change anything. Review in Role Permission Manager:\n"
			+ "\n".join(differences),
			reference_doctype="DocType",
			reference_name=doctype,
		)
	return drifted


def ensure_agent_permissions():
	for doctype, rights in AGENT_PERMISSIONS.items():
		rule = {"parent": doctype, "role": AGENT_ROLE, "permlevel": 0, "if_owner": 0}
		if not frappe.db.exists("Custom DocPerm", rule):
			add_permission(doctype, AGENT_ROLE, 0, next(iter(rights)))
		for right in MANAGED_RIGHTS:
			wanted = rights.get(right, 0)
			if (frappe.db.get_value("Custom DocPerm", rule, right) or 0) != wanted:
				update_permission_property(doctype, AGENT_ROLE, 0, right, wanted)
