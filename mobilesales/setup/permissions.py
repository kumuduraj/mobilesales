"""Access for Mobile Sales roles on standard DocTypes (spec §6.4).

Never shipped as Custom DocPerm fixtures: once any Custom DocPerm exists for a DocType, Frappe ignores
its standard DocPerms. frappe.permissions.add_permission first copies the standard rules into Custom
DocPerm (setup_custom_perms -> copy_perms) and then adds our rule, so every existing role keeps
exactly its rights. Idempotent: each rule is created once and its rights are re-asserted."""

import json

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
	# ERPNext v16.5x get_batch_qty checks Batch select as the session user: store keeper (trip load, top-up) and
	# cashier (settlement submit) too.
	"Batch": {**VISIT_MASTER_ROLES, STORE_KEEPER_ROLE: READ, CASHIER_ROLE: READ},
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
	baseline = load_baseline()
	missing = {doctype: standard_rules(doctype) for doctype in ROLE_PERMISSIONS if doctype not in baseline}
	if missing:
		save_baseline({**baseline, **missing})


# Drift: the standard DocPerms ERPNext ships, compared with the ones in force when the Custom DocPerm copies
# were made (the baseline, kept in DefaultValue; read without the defaults cache, so a rolled-back test never
# leaves a stale copy). Rules other apps or admins add as Custom DocPerm are not drift.
BASELINE_KEY = "mobilesales_standard_docperm_baseline"


def _rights() -> list:
	return ["permlevel", *(df.fieldname for df in frappe.get_meta("DocPerm").fields if df.fieldtype == "Check")]


def standard_rules(doctype) -> dict:
	"""{"role|permlevel|if_owner": {right: 0/1}} of the standard DocPerms, Mobile Sales roles left out."""
	rights = _rights()
	rows = frappe.get_all(
		"DocPerm", filters={"parent": doctype, "role": ["not in", list(ROLE_PERMISSIONS[doctype])]}, fields=["role", *rights]
	)
	return {f"{row.role}|{row.permlevel}|{row.if_owner}": {r: row.get(r) or 0 for r in rights} for row in rows}


def load_baseline() -> dict:
	value = frappe.db.get_value("DefaultValue", {"parent": "__default", "defkey": BASELINE_KEY}, "defvalue")
	return json.loads(value) if value else {}


def save_baseline(baseline: dict):
	frappe.db.set_default(BASELINE_KEY, json.dumps(baseline, sort_keys=True))


def check_standard_permission_drift() -> list[str]:
	"""After an ERPNext upgrade the standard DocPerms may change, but the Custom DocPerm copies made by
	add_permission keep the old rules. Report (never fix) every DocType whose standard rules changed since the
	copy, once: the baseline then moves on, the Error Log entry stays for review. Installs from before the
	baseline compare the copy with the standard rules once. Returns the drifted DocTypes."""
	baseline = load_baseline()
	drifted = []
	for doctype in ROLE_PERMISSIONS:
		if not frappe.db.exists("Custom DocPerm", {"parent": doctype}):
			continue
		now = standard_rules(doctype)
		then = baseline.get(doctype)
		if then is None:  # installed before v1.0.0: the copy is the only record of the old rules
			rights = _rights()
			then = {
				f"{row.role}|{row.permlevel}|{row.if_owner}": {r: row.get(r) or 0 for r in rights}
				for row in frappe.get_all(
					"Custom DocPerm",
					filters={"parent": doctype, "role": ["not in", list(ROLE_PERMISSIONS[doctype])]},
					fields=["role", *rights],
				)
			}
		baseline[doctype] = now
		differences = [
			f"{key.replace('|', ' / level ', 1).replace('|', ', if owner ')}: was {then.get(key)} / now {now.get(key)}"
			for key in sorted(set(then) | set(now))
			if then.get(key) != now.get(key)
		]
		if not differences:
			continue
		drifted.append(doctype)
		title = f"mobilesales: standard permissions changed for {doctype}, review Custom DocPerm"
		print(title)
		frappe.log_error(
			title=title,
			message=title
			+ "\n\nERPNext's standard DocPerm changed since mobilesales copied it into Custom DocPerm, so the copy still "
			"applies the old rules. mobilesales did not change anything. Review in Role Permission Manager:\n"
			+ "\n".join(differences),
			reference_doctype="DocType",
			reference_name=doctype,
		)
	save_baseline(baseline)
	return drifted


def _custom_rules(doctype) -> dict:
	rights = _rights()
	rows = frappe.get_all("Custom DocPerm", filters={"parent": doctype}, fields=["role", *rights])
	return {f"{row.role}|{row.permlevel}|{row.if_owner}": {r: row.get(r) or 0 for r in rights} for row in rows}


def remove_agent_permissions() -> list[str]:
	"""uninstall-app: delete the Mobile Sales role rules; where what is left is exactly ERPNext's standard rules (the
	copy made at install), delete the copy too, so the standard permissions apply again. A copy changed since (by an
	admin, another app or an ERPNext upgrade) is kept and named. Returns the DocTypes whose copy was kept."""
	kept = []
	for doctype, managed in ROLE_PERMISSIONS.items():
		frappe.db.delete("Custom DocPerm", {"parent": doctype, "role": ["in", list(managed)]})
		left = _custom_rules(doctype)
		if not left:
			continue
		if left == standard_rules(doctype):
			frappe.db.delete("Custom DocPerm", {"parent": doctype})
		else:
			kept.append(doctype)
			print(f"mobilesales: Custom DocPerm of {doctype} kept (changed since the install copy), review in Role Permission Manager")
	frappe.db.delete("DefaultValue", {"parent": "__default", "defkey": BASELINE_KEY})
	frappe.clear_cache()
	return kept
