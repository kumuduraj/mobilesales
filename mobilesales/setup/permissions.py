"""Access for Mobile Sales roles on standard DocTypes (spec §6.4).

Never shipped as Custom DocPerm fixtures: once any Custom DocPerm exists for a DocType, Frappe ignores
its standard DocPerms. frappe.permissions.add_permission first copies the standard rules into Custom
DocPerm (setup_custom_perms -> copy_perms) and then adds our rule, so every existing role keeps
exactly its rights. Idempotent: each rule is created once and its rights are re-asserted."""

import frappe
from frappe.permissions import add_permission, update_permission_property

AGENT_ROLE = "Mobile Sales Agent"
STORE_KEEPER_ROLE = "Mobile Sales Store Keeper"
CASHIER_ROLE = "Mobile Sales Cashier"
SUPERVISOR_ROLE = "Mobile Sales Supervisor"
MANAGED_RIGHTS = (
	"select", "read", "write", "create", "submit", "cancel", "delete", "amend",
	"print", "export", "report", "share", "email",
)  # fmt: skip

READ = {"read": 1}
POST_BUNDLES = {"read": 1, "write": 1, "create": 1, "submit": 1}
# DocType -> {role: rights}; every other right in MANAGED_RIGHTS is forced to 0 for that rule.
# Masters a visit reads while ERPNext builds its invoice / credit notes as the session user: the agent,
# or a supervisor recording or submitting a visit from Desk (e.g. returns above the agent's limit).
VISIT_MASTER_ROLES = {AGENT_ROLE: READ, SUPERVISOR_ROLE: READ}
ROLE_PERMISSIONS = {
	"Customer": VISIT_MASTER_ROLES,
	"Item": VISIT_MASTER_ROLES,
	"UOM": VISIT_MASTER_ROLES,
	"Price List": VISIT_MASTER_ROLES,
	"Item Price": VISIT_MASTER_ROLES,
	"Batch": VISIT_MASTER_ROLES,
	"Contact": VISIT_MASTER_ROLES,
	"Address": VISIT_MASTER_ROLES,
	"Territory": VISIT_MASTER_ROLES,
	"Customer Group": VISIT_MASTER_ROLES,
	# Agents: own trips only (permission hooks). Supervisors: visit cancel re-reads the invoices.
	"Sales Invoice": {AGENT_ROLE: {"read": 1, "print": 1}, SUPERVISOR_ROLE: {"read": 1, "print": 1}},
	"Payment Entry": {AGENT_ROLE: {"read": 1, "print": 1}, SUPERVISOR_ROLE: {"read": 1, "print": 1}},
	# ERPNext's get_party_account() checks the session user's select/read on the receivable account
	# while a visit builds its invoice, credit notes and payment (the agent, or a supervisor submitting a
	# visit from Desk); select only: no reading Account records.
	"Account": {AGENT_ROLE: {"select": 1}, SUPERVISOR_ROLE: {"select": 1}},
	# ERPNext creates Serial and Batch Bundles for batch items without ignore_permissions, as the user
	# who submits the stock document: agent (sale), store keeper (trip load), cashier / supervisor
	# (settlement). Standard ERPNext gives the same rights to every operational stock role.
	"Serial and Batch Bundle": {
		AGENT_ROLE: POST_BUNDLES,
		STORE_KEEPER_ROLE: POST_BUNDLES,
		CASHIER_ROLE: POST_BUNDLES,
		SUPERVISOR_ROLE: {**POST_BUNDLES, "cancel": 1},
	},
}
AGENT_PERMISSIONS = {doctype: roles[AGENT_ROLE] for doctype, roles in ROLE_PERMISSIONS.items() if AGENT_ROLE in roles}
AGENT_READ_DOCTYPES = tuple(ROLE_PERMISSIONS)


def ensure_agent_permissions():
	for doctype, roles in ROLE_PERMISSIONS.items():
		for role, rights in roles.items():
			rule = {"parent": doctype, "role": role, "permlevel": 0, "if_owner": 0}
			if not frappe.db.exists("Custom DocPerm", rule):
				add_permission(doctype, role, 0, next(iter(rights)))
			for right in MANAGED_RIGHTS:
				wanted = rights.get(right, 0)
				if (frappe.db.get_value("Custom DocPerm", rule, right) or 0) != wanted:
					update_permission_property(doctype, role, 0, right, wanted)


def check_standard_permission_drift() -> list[str]:
	"""After an ERPNext upgrade the standard DocPerms may change, but the Custom DocPerm copies made by
	add_permission keep the old rules. Report (never fix) every DocType whose copy no longer matches the
	standard rules for any role this app does not manage. Returns the drifted DocTypes."""
	rights = ["permlevel", *(df.fieldname for df in frappe.get_meta("DocPerm").fields if df.fieldtype == "Check")]

	drifted = []
	for doctype, managed in ROLE_PERMISSIONS.items():
		if not frappe.db.exists("Custom DocPerm", {"parent": doctype}):
			continue

		def rules(source):
			rows = frappe.get_all(source, filters={"parent": doctype, "role": ["not in", list(managed)]}, fields=["role", *rights])
			return {(row.role, row.permlevel, row.if_owner): {r: row.get(r) or 0 for r in rights} for row in rows}

		standard, custom = rules("DocPerm"), rules("Custom DocPerm")
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
			+ "\n\nThe Custom DocPerm copy no longer matches the standard DocPerm (Mobile Sales roles ignored). "
			"mobilesales did not change anything. Review in Role Permission Manager:\n"
			+ "\n".join(differences),
			reference_doctype="DocType",
			reference_name=doctype,
		)
	return drifted
