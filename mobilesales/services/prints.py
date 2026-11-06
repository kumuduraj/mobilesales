"""Figures for the 4-inch prints (Mobile Visit Bill, Mobile Invoice 4in, Mobile Return Note), exposed to Jinja
through hooks.jinja. A return credit set off by a Credit Note journal entry is never shown as cash: the set-off
rows say which credit note paid which invoice. Frappe checks print permission on the printed document; these
helpers only read ledger rows that belong to it."""

from collections import defaultdict

import frappe
from frappe.utils import flt

from mobilesales.services import invoicing

SET_OFF_VOUCHER = "Credit Note"


def set_offs(reference: str) -> list:
	"""Every return-credit set-off touching this Sales Invoice, as credit note or as the invoice it paid:
	[{journal, credit_note, invoice, amount}] in posting order."""
	parents = frappe.get_all(
		"Journal Entry Account",
		filters={"reference_type": "Sales Invoice", "reference_name": reference, "docstatus": 1},
		pluck="parent",
		distinct=True,
	)
	journals = frappe.get_all(
		"Journal Entry",
		filters={"name": ["in", parents or [""]], "voucher_type": SET_OFF_VOUCHER, "docstatus": 1},
		pluck="name",
		order_by="posting_date asc, creation asc",
	)
	return [p for journal in journals for p in journal_pairs(journal) if reference in (p.credit_note, p.invoice)]


JOURNAL_ROW_FIELDS = ["parent", "reference_name", "debit_in_account_currency", "credit_in_account_currency"]


def journal_pairs(journal: str, rows=None) -> list:
	"""Pair the journal's debit rows (credit notes) with its credit rows (invoices paid), first in first out:
	ours are written Dr note / Cr invoice per set-off, ERPNext's reconciliation one pair per entry. `rows`: the
	journal's Sales Invoice rows in idx order when the caller loaded them already (JOURNAL_ROW_FIELDS)."""
	if rows is None:
		rows = frappe.get_all(
			"Journal Entry Account",
			filters={"parent": journal, "reference_type": "Sales Invoice"},
			fields=JOURNAL_ROW_FIELDS,
			order_by="idx asc",
		)
	debits = [[r.reference_name, flt(r.debit_in_account_currency)] for r in rows if flt(r.debit_in_account_currency) > 0]
	credits = [[r.reference_name, flt(r.credit_in_account_currency)] for r in rows if flt(r.credit_in_account_currency) > 0]
	pairs = []
	while debits and credits:
		amount = min(debits[0][1], credits[0][1])
		pairs.append(frappe._dict(journal=journal, credit_note=debits[0][0], invoice=credits[0][0], amount=flt(amount, 2)))
		for side in (debits, credits):
			side[0][1] -= amount
			if flt(side[0][1], 6) <= 0:
				side.pop(0)
	return pairs


def previous_outstanding(customer: str, company: str, exclude=()) -> float:
	"""The customer's balance on every other submitted invoice and credit note: what they owe, or below 0 the
	credit they hold (printed as "Credit", v1.0.2)."""
	return flt(
		sum(
			frappe.get_all(
				"Sales Invoice",
				filters={
					"customer": customer,
					"company": company,
					"docstatus": 1,
					"name": ["not in", list(exclude) or [""]],
				},
				pluck="outstanding_amount",
			)
		),
		2,
	)


def agent_name(mobile_trip) -> str:
	return frappe.db.get_value("Mobile Trip", mobile_trip, "agent_name") if mobile_trip else ""


def mobile_invoice_print(doc) -> dict:
	"""An invoice: the return credits it received (per credit note), the cash paid and the balance."""
	payable = invoicing.payable_amount(doc)
	credits = [p for p in set_offs(doc.name) if p.invoice == doc.name]
	credit_total = flt(sum(p.amount for p in credits), 2)
	return frappe._dict(
		agent_name=agent_name(doc.get("mobile_trip")),
		payable=payable,
		credits=credits,
		credit_total=credit_total,
		paid=flt(payable - flt(doc.outstanding_amount) - credit_total, 2),
		previous=previous_outstanding(doc.customer, doc.company, [doc.name]),
	)


def mobile_return_note_print(doc) -> dict:
	"""A credit note: its lines with the visit's reason / condition, where the credit went and what is left."""
	reasons = {}
	for row in frappe.get_all(
		"Customer Visit Return Item",
		filters={"credit_note": doc.name, "docstatus": 1},
		fields=["sales_invoice_item", "item_code", "return_reason", "condition", "remarks", "against_invoice"],
		order_by="idx asc",
	):
		reasons.setdefault((row.sales_invoice_item or None, row.item_code), row)
	lines = []
	for item in doc.items:
		info = reasons.get((item.get("sales_invoice_item") or None, item.item_code)) or frappe._dict()
		lines.append(
			frappe._dict(
				item_name=item.item_name,
				qty=abs(flt(item.qty)),
				uom=item.uom,
				rate=flt(item.rate),
				amount=abs(flt(item.amount)),
				reason=info.return_reason,
				condition=info.condition,
				remarks=info.remarks,
			)
		)
	applied = [p for p in set_offs(doc.name) if p.credit_note == doc.name]
	visit = frappe.db.get_value("Customer Visit Return Item", {"credit_note": doc.name, "docstatus": 1}, "parent")
	credit = abs(invoicing.payable_amount(doc))
	lines_total = flt(sum(line.amount for line in lines), 2)
	return frappe._dict(
		agent_name=agent_name(doc.get("mobile_trip")),
		visit=visit,
		against=list(dict.fromkeys([doc.return_against] if doc.return_against else [])),
		lines=lines,
		credit=credit,
		lines_total=lines_total,
		# the credit is the note's rounded total: 0.5 Kg x 1,325.00 = 662.50 on the lines, 662.00 credited
		rounding=flt(credit - lines_total, 2),
		applied=applied,
		credit_left=flt(-flt(doc.outstanding_amount), 2) if flt(doc.outstanding_amount) < 0 else 0,
	)


def mobile_visit_bill_print(visit) -> dict:
	"""The combined bill of one visit: today's sale, the return notes, the set-off, cash and what is due."""
	sale = frappe.get_doc("Sales Invoice", visit.sales_invoice) if visit.sales_invoice else None
	notes = [frappe.get_doc("Sales Invoice", n.strip()) for n in (visit.credit_notes or "").split(",") if n.strip()]
	pairs = frappe.get_all("Journal Entry", filters={"name": visit.credit_journal or "", "docstatus": 1}, pluck="name")
	set_off = journal_pairs(pairs[0]) if pairs else []

	returns = []
	for note in notes:
		figures = mobile_return_note_print(note)
		returns.append(
			frappe._dict(
				name=note.name,
				return_against=note.return_against,
				lines=figures.lines,
				total=figures.credit,
				rounding=figures.rounding,
			)
		)
	return_total = flt(sum(r.total for r in returns), 2)
	applied = defaultdict(float)
	for p in set_off:
		applied[p.invoice] += p.amount
	credit_applied = flt(sum(applied.values()), 2)

	payable = invoicing.payable_amount(sale) if sale else 0
	on_sale = flt(applied.get(sale.name, 0), 2) if sale else 0
	exclude = ([sale.name] if sale else []) + [n.name for n in notes]  # this visit's own documents are above
	return frappe._dict(
		agent_name=visit.agent_name or agent_name(visit.mobile_trip),
		sale=sale,
		line_discount=bool(sale and any(flt(i.price_list_rate) - flt(i.rate) > 0.004 for i in sale.items)),
		payable=payable,
		returns=returns,
		return_total=return_total,
		applied=[frappe._dict(invoice=k, amount=flt(v, 2)) for k, v in applied.items()],
		credit_applied=credit_applied,
		credit_left=flt(return_total - credit_applied, 2) if returns else 0,
		net_payable=flt(payable - on_sale, 2),
		paid=flt(visit.collect_amount, 2) if sale else 0,
		paid_previous=[r for r in visit.collect_previous if flt(r.allocated) > 0],
		balance=flt(sale.outstanding_amount, 2) if sale else 0,
		previous=previous_outstanding(visit.customer, visit.company, exclude),
	)


VISIT_BILL = "Mobile Visit Bill"
INVOICE = "Mobile Invoice 4in"
RETURN_NOTE = "Mobile Return Note"


def visit_documents(visit) -> list:
	"""What "Print All" prints for a visit, in order: the bill, today's invoice, then each return note."""
	docs = []
	if visit.sales_invoice or visit.credit_notes or visit.payment_entry:
		docs.append(("Customer Visit", visit.name, VISIT_BILL))
	if visit.sales_invoice:
		docs.append(("Sales Invoice", visit.sales_invoice, INVOICE))
	docs += [("Sales Invoice", n.strip(), RETURN_NOTE) for n in (visit.credit_notes or "").split(",") if n.strip()]
	return docs
