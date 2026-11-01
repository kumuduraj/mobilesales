"""Plain-text receipts for thermal printers (spec §6.3). Lines only; the ESC/POS hand-off to the Android
print service is deferred (docs/SPEC.md §6.3)."""

import frappe
from frappe import _
from frappe.utils import flt, fmt_money, format_date

SUPPORTED = ("Sales Invoice", "Payment Entry")


def render(doc, width: int) -> list[str]:
	return _invoice(doc, width) if doc.doctype == "Sales Invoice" else _receipt(doc, width)


def _money(value, doc):
	return fmt_money(flt(value), currency=doc.get("currency") or doc.get("paid_to_account_currency"))


def _pair(left, right, width):
	left, right = str(left), str(right)
	space = width - len(right) - 1
	return f"{left[:space]:<{space}} {right}"


def _header(doc, title, width) -> list[str]:
	agent = frappe.db.get_value("Mobile Trip", doc.mobile_trip, "agent_name") if doc.get("mobile_trip") else ""
	lines = [doc.company[:width].center(width), _(title).center(width), "-" * width]
	lines.append(_pair(_("No"), doc.name, width))
	lines.append(_pair(_("Date"), format_date(doc.posting_date), width))
	lines.append(_pair(_("Customer"), doc.get("customer_name") or doc.get("party_name") or doc.get("party"), width))
	if agent:
		lines.append(_pair(_("Agent"), agent, width))
	lines.append("-" * width)
	return lines


def _invoice(doc, width) -> list[str]:
	lines = _header(doc, "INVOICE", width)
	for item in doc.items:
		lines.append(item.item_name[:width])
		lines.append(_pair(f"  {flt(item.qty):g} {item.uom} x {_money(item.rate, doc)}", _money(item.amount, doc), width))
	lines.append("-" * width)
	payable = doc.grand_total if (doc.disable_rounded_total or not doc.rounded_total) else doc.rounded_total
	previous = sum(
		flt(v)
		for v in frappe.get_all(
			"Sales Invoice",
			filters={"customer": doc.customer, "company": doc.company, "docstatus": 1,
					 "outstanding_amount": [">", 0], "name": ["!=", doc.name]},
			pluck="outstanding_amount",
		)
	)  # fmt: skip
	lines.append(_pair(_("Net Total"), _money(doc.net_total, doc), width))
	for tax in doc.taxes:
		if flt(tax.tax_amount):
			lines.append(_pair(tax.description[: width // 2], _money(tax.tax_amount, doc), width))
	lines.append(_pair(_("TOTAL"), _money(payable, doc), width))
	lines.append(_pair(_("Paid"), _money(flt(payable) - flt(doc.outstanding_amount), doc), width))
	lines.append(_pair(_("Balance"), _money(doc.outstanding_amount, doc), width))
	lines.append(_pair(_("Previous Outstanding"), _money(previous, doc), width))
	lines.append(_pair(_("TOTAL DUE"), _money(previous + flt(doc.outstanding_amount), doc), width))
	lines += ["-" * width, _("Thank you for your business").center(width)]
	return lines


def _receipt(doc, width) -> list[str]:
	lines = _header(doc, "PAYMENT RECEIPT", width)
	lines.append(_pair(_("Mode"), doc.mode_of_payment or "", width))
	lines.append("-" * width)
	for ref in doc.references:
		lines.append(_pair(ref.reference_name, _money(ref.allocated_amount, doc), width))
	if flt(doc.unallocated_amount):
		lines.append(_pair(_("On account"), _money(doc.unallocated_amount, doc), width))
	lines += ["-" * width, _pair(_("RECEIVED"), _money(doc.paid_amount, doc), width), "-" * width]
	lines.append(_("Thank you").center(width))
	return lines
