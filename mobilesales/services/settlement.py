"""Mobile Settlement (spec §4.3, §5.4, §6.5): creation, per-state edit rules, submit postings with
post-conditions, cancel reversal. Submit runs in one transaction: any failure rolls everything back."""

import frappe
from frappe import _
from frappe.utils import flt, nowdate, nowtime

from mobilesales.overrides.guards import INTERNAL_FLAG, SETTLEMENT_FLAG
from mobilesales.services import reconciliation
from mobilesales.services import settings as ms_settings
from mobilesales.services import stock, vouchers

AGENT, STORE_KEEPER, CASHIER = "Mobile Sales Agent", "Mobile Sales Store Keeper", "Mobile Sales Cashier"
SUPERVISOR, SYSTEM_MANAGER = "Mobile Sales Supervisor", "System Manager"
SUPERVISOR_ROLES = (SUPERVISOR, SYSTEM_MANAGER)
CREATE_ROLES = (STORE_KEEPER, SUPERVISOR, SYSTEM_MANAGER)
WORKFLOW_DRAFT, WORKFLOW_APPROVED = "Draft", "Approved"
# workflow state -> (editable field groups, roles that may edit them)
EDIT_RULES = {
	"Draft": ({"stock", "cash"}, {AGENT, SUPERVISOR, SYSTEM_MANAGER}),
	"Pending Store": ({"stock", "returns"}, {STORE_KEEPER, SUPERVISOR, SYSTEM_MANAGER}),
	"Pending Cashier": ({"cash"}, {CASHIER, SUPERVISOR, SYSTEM_MANAGER}),
}


# Creation


@frappe.whitelist()
def make_settlement(trip: str) -> str:
	"""'Create Settlement' on the trip: returns the open settlement or creates one. The trip row is locked
	first, so a double tap (or the app and Desk at once) cannot create two."""
	doc = frappe.get_doc("Mobile Trip", trip, for_update=True)
	agent_user = frappe.db.get_value("Mobile Sales Agent", doc.agent, "user")
	if frappe.session.user != agent_user and not set(CREATE_ROLES) & set(frappe.get_roles()):
		frappe.throw(_("Only the trip's agent, a store keeper or a supervisor can start the settlement."), frappe.PermissionError)
	existing = open_settlement(trip, for_update=True)
	if existing:
		return existing
	settlement = frappe.new_doc("Mobile Settlement")
	settlement.mobile_trip = trip
	settlement.insert()
	return settlement.name


def open_settlement(trip_name, exclude=None, for_update=False) -> str | None:
	filters = {"mobile_trip": trip_name, "docstatus": ["<", 2]}
	if exclude:
		filters["name"] = ["!=", exclude]
	# for_update: a locking read sees settlements committed after this transaction's snapshot (REPEATABLE READ)
	return frappe.db.get_value("Mobile Settlement", filters, "name", for_update=for_update)


# Document events


def validate(doc):
	trip = reconciliation.get_trip(doc.mobile_trip)
	if doc.docstatus == 0 and (trip.docstatus != 1 or trip.status != "Settling"):
		frappe.throw(
			_("Mobile Trip {0} is {1}; settle only after End Day (status Settling).").format(
				frappe.bold(trip.name), _(trip.status)
			),
			title=_("Trip not settling"),
		)
	other = open_settlement(trip.name, exclude=doc.name)
	if other:
		frappe.throw(_("Mobile Trip {0} already has settlement {1}.").format(frappe.bold(trip.name), frappe.bold(other)))

	before = None if doc.is_new() else doc.get_doc_before_save()
	for fieldname in POSTING_LINKS:  # validate runs before submit only, so these are never ours yet
		doc.set(fieldname, None)
	for fieldname in VERIFIERS:  # only set_verifiers changes them, on a workflow transition
		doc.set(fieldname, before.get(fieldname) if before else None)
	if before:
		validate_edit_rules(doc, before)
		set_verifiers(doc, before)
	for row in doc.stock_lines:
		if flt(row.returned_qty) < 0 or flt(row.damaged_qty) < 0:
			frappe.throw(_("Row {0}: returned and damaged quantities cannot be negative.").format(row.idx))
	reconciliation.refresh_settlement(doc)


# Set by post_settlement (db_set) and the workflow only: never from the client, a REST save or an amendment.
POSTING_LINKS = (
	"return_entry", "damage_entry", "shortage_entry", "return_damage_entry", "return_shortage_entry",
	"recovery_journal", "cash_journal", "variance_journal",
)  # fmt: skip
VERIFIERS = ("verified_by_store", "verified_by_cashier")

GROUP_LABELS = {"stock": "stock counts", "cash": "cash", "returns": "customer return counts"}


def _entered(doc) -> dict:
	stock_values = {r.item_code: (flt(r.returned_qty), flt(r.damaged_qty), r.damaged_batch_no or None) for r in doc.stock_lines}
	counts = {flt(r.denomination): int(r.count or 0) for r in doc.denominations}
	cash_values = (counts, None if any(counts.values()) else flt(doc.cash_handed_over))
	return_values = {r.item_code: (flt(r.received_qty), flt(r.damaged_qty)) for r in doc.get("return_lines") or []}
	return {"stock": stock_values, "cash": cash_values, "returns": return_values}


def validate_edit_rules(doc, before):
	now, then = _entered(doc), _entered(before)
	changed = {group for group in now if now[group] != then[group]}
	if not changed:
		return
	state = before.workflow_state or WORKFLOW_DRAFT
	allowed, editors = EDIT_RULES.get(state, (set(), set()))
	roles = set(frappe.get_roles())
	if changed - allowed or not (roles & editors or frappe.session.user == "Administrator"):
		frappe.throw(
			_("In state {0} you cannot change {1}.").format(
				frappe.bold(_(state)), ", ".join(_(GROUP_LABELS[g]) for g in sorted(changed))
			),
			frappe.PermissionError,
		)


def set_verifiers(doc, before):
	if before.workflow_state == doc.workflow_state:
		return
	if doc.workflow_state == WORKFLOW_DRAFT:
		# Any Reject sends the settlement back for recount: earlier verifications no longer hold.
		doc.verified_by_store = None
		doc.verified_by_cashier = None
		return
	if before.workflow_state == "Pending Store" and doc.workflow_state == "Pending Cashier":
		doc.verified_by_store = frappe.session.user
	if before.workflow_state == "Pending Cashier" and doc.workflow_state in ("Approved", "Pending Approval"):
		doc.verified_by_cashier = frappe.session.user


def before_submit(doc):
	before = doc.get_doc_before_save()
	previous_state = before.workflow_state if before else None
	if doc.workflow_state != WORKFLOW_APPROVED:
		frappe.throw(_("Submit the settlement through its workflow (Verify Cash / Approve)."))
	if doc.needs_approval and (
		previous_state != "Pending Approval" or not set(SUPERVISOR_ROLES) & set(frappe.get_roles())
	):
		frappe.throw(
			_("Variance is above the tolerance: a Mobile Sales Supervisor must approve this settlement."),
			title=_("Supervisor approval required"),
		)
	trip = reconciliation.get_trip(doc.mobile_trip)
	if trip.status != "Settling":
		frappe.throw(_("Mobile Trip {0} is {1}, not Settling.").format(trip.name, _(trip.status)))

	for row in doc.get("return_lines") or []:
		if flt(row.received_qty) < 0 or flt(row.damaged_qty) < 0 or flt(row.received_qty, 6) > flt(row.credited_qty, 6):
			frappe.throw(
				_("Customer returns {0}: received {1} must be between 0 and the credited {2}.").format(
					frappe.bold(row.item_code), flt(row.received_qty), flt(row.credited_qty)
				),
				title=_("Customer returns"),
			)
		if flt(row.damaged_qty, 6) > flt(row.received_qty, 6):
			frappe.throw(
				_("Customer returns {0}: damaged {1} is more than received {2}.").format(
					frappe.bold(row.item_code), flt(row.damaged_qty), flt(row.received_qty)
				),
				title=_("Customer returns"),
			)
	for row in doc.stock_lines:
		if flt(row.excess_qty) > 0:
			frappe.throw(
				_("{0}: returned + damaged ({1}) is more than expected ({2}). Recount before submitting.").format(
					frappe.bold(row.item_code), flt(row.returned_qty) + flt(row.damaged_qty), flt(row.expected_balance)
				),
				title=_("Excess stock"),
			)
		if flt(row.expected_balance, 6) != flt(row.bin_qty, 6):
			frappe.throw(
				_(
					"{0}: van stock is {1} but the trip ledger expects {2}. A document bypassed the mobile "
					"guards; investigate before settling."
				).format(frappe.bold(row.item_code), flt(row.bin_qty), flt(row.expected_balance)),
				title=_("Van stock mismatch"),
			)


def before_cancel(doc):
	if not set(SUPERVISOR_ROLES) & set(frappe.get_roles()):
		frappe.throw(_("Only a Mobile Sales Supervisor can cancel a settlement."), frappe.PermissionError)


# Postings (spec §5.4)


def post_settlement(doc):
	settings = ms_settings.get_settings()
	trip = reconciliation.get_trip(doc.mobile_trip)
	agent = frappe.db.get_value("Mobile Sales Agent", trip.agent, ["cash_account", "employee"], as_dict=True)
	recover = doc.variance_action == "Recover from Agent" and agent.employee

	rows = {"Return": [], "Damage": [], "Shortage": [], **_customer_return_rows(doc, trip, settings)}
	_items, batches = reconciliation.stock_movement(trip.name, trip.van_warehouse)
	for line in doc.stock_lines:
		if line.has_batch_no:
			expected = {b: q["issued"] - q["sold"] for (code, b), q in batches.items() if code == line.item_code}
			plan = reconciliation.allocate_batches(expected, line.returned_qty, line.damaged_qty, line.damaged_batch_no)
			for purpose, kind in (("Return", "returned"), ("Damage", "damaged"), ("Shortage", "missing")):
				rows[purpose] += [(line.item_code, qty, batch) for batch, qty in plan[kind].items() if qty > 0]
		else:
			for purpose, qty in (("Return", line.returned_qty), ("Damage", line.damaged_qty), ("Shortage", line.missing_qty)):
				if flt(qty) > 0:
					rows[purpose].append((line.item_code, flt(qty), None))

	_require(settings, rows["Return"] and "return_warehouse", (rows["Damage"] or rows["Return Damage"]) and "damage_warehouse",
		rows["Return Shortage"] and "stock_shortage_account",
		rows["Shortage"] and "stock_shortage_account", "main_cash_account",
		flt(doc.cash_variance) and "cash_shortage_account", recover and "employee_recovery_account")  # fmt: skip

	links = {}
	links["return_entry"] = _stock_entry(doc, trip, "Return", "Material Transfer", rows["Return"], settings.return_warehouse)
	links["damage_entry"] = _stock_entry(doc, trip, "Damage", "Material Transfer", rows["Damage"], settings.damage_warehouse)
	links["shortage_entry"] = _stock_entry(doc, trip, "Shortage", "Material Issue", rows["Shortage"], None, settings.stock_shortage_account)
	returns_wh = settings.customer_return_warehouse
	links["return_damage_entry"] = _stock_entry(doc, trip, "Return Damage", "Material Transfer", rows["Return Damage"], settings.damage_warehouse, source=returns_wh)
	links["return_shortage_entry"] = _stock_entry(doc, trip, "Return Shortage", "Material Issue", rows["Return Shortage"], None, settings.stock_shortage_account, source=returns_wh)

	shortages = [links[f] for f in ("shortage_entry", "return_shortage_entry") if links[f]]
	if shortages and recover:
		value = flt(sum(flt(frappe.db.get_value("Stock Entry", name, "total_outgoing_value")) for name in shortages), 2)
		links["recovery_journal"] = _journal(doc, trip, _("Stock shortage recovered from agent"), [
			(settings.employee_recovery_account, value, 0, agent.employee),
			(settings.stock_shortage_account, 0, value, None),
		])  # fmt: skip

	handed = flt(doc.cash_handed_over, 2)
	if handed > 0:
		links["cash_journal"] = _journal(doc, trip, _("Cash handed over"), [
			(settings.main_cash_account, handed, 0, None),
			(agent.cash_account, 0, handed, None),
		])  # fmt: skip

	variance = flt(doc.cash_variance, 2)
	if variance < 0:
		short_account, party = (settings.employee_recovery_account, agent.employee) if recover else (settings.cash_shortage_account, None)
		links["variance_journal"] = _journal(doc, trip, _("Cash shortage"), [
			(short_account, -variance, 0, party),
			(agent.cash_account, 0, -variance, None),
		])  # fmt: skip
	elif variance > 0:
		links["variance_journal"] = _journal(doc, trip, _("Cash excess"), [
			(agent.cash_account, variance, 0, None),
			(settings.cash_shortage_account, 0, variance, None),
		])  # fmt: skip

	for fieldname, name in links.items():
		if name:
			doc.db_set(fieldname, name, update_modified=False)
	check_post_conditions(doc, trip, agent)

	trip_doc = frappe.get_doc("Mobile Trip", trip.name)
	for purpose, fieldname in (
		("Return", "return_entry"),
		("Damage", "damage_entry"),
		("Shortage", "shortage_entry"),
		("Return Damage", "return_damage_entry"),
		("Return Shortage", "return_shortage_entry"),
	):
		if links.get(fieldname):
			stock.link_stock_entry(trip_doc, frappe.get_doc("Stock Entry", links[fieldname]), purpose)
	trip_doc.db_set({"status": "Settled", "settlement": doc.name})


def _customer_return_rows(doc, trip, settings) -> dict:
	"""Damaged customer returns -> damage warehouse, missing -> shortage; batches from the trip's
	credit notes, oldest first. Good returns stay in the customer return warehouse."""
	rows = {"Return Damage": [], "Return Shortage": []}
	if not doc.get("return_lines"):
		return rows
	_items, batches, _rates = reconciliation.return_movement(trip.name, settings.customer_return_warehouse)
	for line in doc.return_lines:
		good = flt(line.received_qty) - flt(line.damaged_qty)
		if line.has_batch_no:
			credited = {b: q for (code, b), q in batches.items() if code == line.item_code}
			plan = reconciliation.allocate_batches(credited, good, line.damaged_qty)
			rows["Return Damage"] += [(line.item_code, qty, batch) for batch, qty in plan["damaged"].items() if qty > 0]
			rows["Return Shortage"] += [(line.item_code, qty, batch) for batch, qty in plan["missing"].items() if qty > 0]
		else:
			if flt(line.damaged_qty) > 0:
				rows["Return Damage"].append((line.item_code, flt(line.damaged_qty), None))
			if flt(line.missing_qty) > 0:
				rows["Return Shortage"].append((line.item_code, flt(line.missing_qty), None))
	return rows


def _require(settings, *fieldnames):
	missing = [settings.meta.get_label(f) for f in fieldnames if f and not settings.get(f)]
	if missing:
		frappe.throw(_("Set {0} in Mobile Sales Settings before settling.").format(", ".join(_(m) for m in missing)))


def _stock_entry(doc, trip, purpose, entry_type, rows, target, expense_account=None, source=None):
	if not rows:
		return None
	se = frappe.new_doc("Stock Entry")
	se.stock_entry_type = entry_type
	se.purpose = entry_type
	se.company = trip.company
	se.set_posting_time = 1
	se.posting_date = nowdate()
	se.posting_time = nowtime()
	se.mobile_trip = trip.name
	se.mobile_purpose = purpose
	se.remarks = _("Mobile Settlement {0}: {1}").format(doc.name, _(purpose))
	for item_code, qty, batch in rows:
		row = {
			"item_code": item_code,
			"qty": qty,
			"uom": frappe.get_cached_value("Item", item_code, "stock_uom"),
			"conversion_factor": 1,
			"s_warehouse": source or trip.van_warehouse,
			"t_warehouse": target,
		}
		if batch:
			row.update({"use_serial_batch_fields": 1, "batch_no": batch})
		if expense_account:
			row["expense_account"] = expense_account
		se.append("items", row)
	se.flags.ignore_permissions = True
	se.flags[INTERNAL_FLAG] = True
	se.flags[SETTLEMENT_FLAG] = True
	se.insert()
	se.submit()
	return se.name


def _journal(doc, trip, remark, lines):
	cost_center = frappe.get_cached_value("Company", trip.company, "cost_center")
	je = frappe.new_doc("Journal Entry")
	je.voucher_type = "Journal Entry"
	je.company = trip.company
	je.posting_date = nowdate()
	je.mobile_trip = trip.name
	je.mobile_settlement = doc.name
	je.user_remark = _("Mobile Settlement {0}: {1}").format(doc.name, remark)
	for account, debit, credit, employee in lines:
		row = {
			"account": account,
			"debit_in_account_currency": debit,
			"credit_in_account_currency": credit,
			"cost_center": cost_center,
		}
		if employee:
			row.update({"party_type": "Employee", "party": employee})
		je.append("accounts", row)
	je.flags.ignore_permissions = True
	je.flags[INTERNAL_FLAG] = True
	je.insert()
	je.submit()
	return je.name


def check_post_conditions(doc, trip, agent):
	left = frappe.get_all(
		"Bin", filters={"warehouse": trip.van_warehouse, "actual_qty": ["!=", 0]}, fields=["item_code", "actual_qty"]
	)
	if left:
		frappe.throw(
			_("Van {0} is not empty after settlement: {1}").format(
				trip.van_warehouse, ", ".join(f"{b.item_code} {flt(b.actual_qty)}" for b in left)
			),
			title=_("Settlement post-condition failed"),
		)
	from erpnext.stock.doctype.batch.batch import get_batch_qty

	for line in doc.stock_lines:
		if not line.has_batch_no:
			continue
		for batch in get_batch_qty(warehouse=trip.van_warehouse, item_code=line.item_code):
			if flt(batch.get("qty"), 6):
				frappe.throw(
					_("Batch {0} of {1} still has {2} in the van after settlement.").format(
						batch.get("batch_no"), line.item_code, flt(batch.get("qty"))
					),
					title=_("Settlement post-condition failed"),
				)
	balance = reconciliation.get_agent_cash_balance(agent.cash_account)
	if balance:
		frappe.throw(
			_("Agent cash account {0} has a balance of {1} after settlement; it must be 0.").format(
				agent.cash_account, balance
			),
			title=_("Settlement post-condition failed"),
		)


def reverse_settlement(doc):
	"""Cancel every posting in reverse, then the trip goes back to Settling."""
	posted = [
		(doctype, doc.get(fieldname))
		for doctype, fieldname in (
			("Journal Entry", "variance_journal"),
			("Journal Entry", "cash_journal"),
			("Journal Entry", "recovery_journal"),
			("Stock Entry", "return_shortage_entry"),
			("Stock Entry", "return_damage_entry"),
			("Stock Entry", "shortage_entry"),
			("Stock Entry", "damage_entry"),
			("Stock Entry", "return_entry"),
		)
		if doc.get(fieldname)
	]
	# The trip (still submitted) lists these Stock Entries; unlink first or Frappe's back-link check
	# refuses to cancel them.
	stock_entries = [name for doctype, name in posted if doctype == "Stock Entry"]
	if stock_entries:
		frappe.db.delete("Mobile Trip Stock Entry", {"parent": doc.mobile_trip, "stock_entry": ["in", stock_entries]})
	for doctype, name in posted:
		back_links = {"mobile_trip": doc.mobile_trip}
		if doctype == "Journal Entry":
			back_links["mobile_settlement"] = doc.name
		vouchers.cancel_linked(doctype, name, **back_links)
	frappe.db.set_value("Mobile Trip", doc.mobile_trip, {"status": "Settling", "settlement": None})
