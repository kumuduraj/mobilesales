# Copyright (c) 2026, Evonet and contributors
# For license information, please see license.txt
"""Mobile Trip Day Report (spec §7.1): every section of one trip's day as rows (section headers in bold).
The A4 print format "Mobile Trip Day Report" on Mobile Settlement renders the same reports.day_report()."""

from frappe import _
from frappe.utils import flt

from mobilesales.services import reports


def execute(filters=None):
	trip = (filters or {}).get("mobile_trip")
	if not trip:
		return columns(), []
	return columns(), rows(reports.day_report(trip))


def columns():
	return [
		{"fieldname": "section", "label": _("Section"), "fieldtype": "Data", "width": 170},
		{"fieldname": "line", "label": _("Line"), "fieldtype": "Data", "width": 220},
		{"fieldname": "detail", "label": _("Detail"), "fieldtype": "Data", "width": 360},
		{"fieldname": "qty", "label": _("Qty"), "fieldtype": "Float", "width": 90},
		{"fieldname": "amount", "label": _("Amount"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "amount2", "label": _("Collected / Value"), "fieldtype": "Currency", "width": 130},
	]


def rows(r):
	out = []

	def section(title):
		out.append({"section": title, "is_section": 1})

	def line(label, detail=None, qty=None, amount=None, amount2=None):
		out.append({"line": label, "detail": detail, "qty": qty, "amount": amount, "amount2": amount2})

	t, s = r.trip, r.summary
	section(_("1. Header"))
	line(_("Trip"), f"{t.name} · {t.trip_date} · {t.status}")
	line(_("Agent"), f"{t.agent_name} ({t.agent})")
	line(_("Vehicle / helper"), " · ".join(x for x in (t.vehicle, t.helper) if x))
	line(_("Route"), t.route)
	line(_("First / last visit"), f"{r.first_visit or '-'} – {r.last_visit or '-'}")
	line(_("Settlement"), f"{s.settlement or '-'} · {s.settlement_status or '-'}")

	section(_("2. Day KPIs"))
	for label, qty in (
		(_("Planned visits"), s.planned_visits), (_("Visited"), s.visits), (_("Missed"), s.missed),
		(_("Off-route visits"), s.off_route), (_("Sales visits"), s.sales_visits), (_("No-sale visits"), s.no_sale_visits),
		(_("Strike rate %"), r.strike_rate), (_("Invoices"), s.invoices),
	):  # fmt: skip
		line(label, qty=qty)
	for label, amount in (
		(_("Net sales"), s.net_sales), (_("Invoice total"), s.sales_total), (_("Cash collected"), s.cash_collected),
		(_("Credit given"), s.credit_given), (_("Customer returns"), s.return_value), (_("Return credit applied"), s.credit_applied),
		(_("Line discounts"), s.line_discount), (_("Invoice discounts"), s.invoice_discount),
	):  # fmt: skip
		line(label, amount=amount)

	section(_("3. Visit log"))
	for v in r.visit_log:
		detail = " · ".join(x for x in (v.outcome, _("off route") if v.off_route else None, v.reason, v.invoice, v.remarks, v.map) if x)
		line(f"{v.time} {v.customer}", detail, amount=v.amount, amount2=v.collected)

	section(_("4. Missed customers"))
	for m in r.missed:
		line(m.customer_name or m.customer, f"{_('Seq')} {m.sequence} · {m.visit_frequency} {m.visit_day or ''}".strip())

	section(_("5. Customer updates"))
	for c in r.changes:
		line(c.customer, f"{c.field}: {c.old or ''} → {c.new or ''} ({c.status or ''})")

	section(_("6. Customer shelf stock"))
	for sh in r.shelf:
		line(sh.customer, " · ".join(str(x) for x in (sh.item, sh.uom, sh.expiry, sh.competitor) if x), qty=sh.qty)

	section(_("7. Sales by invoice"))
	for i in r.invoices:
		detail = f"{i.customer} · {_('net')} {flt(i.net, 2)} · {_('tax')} {flt(i.tax, 2)} · {_('credit')} {flt(i.credit, 2)} · {_('cash')} {flt(i.paid, 2)} · {_('outstanding')} {flt(i.outstanding, 2)}"
		line(i.invoice, detail, amount=i.total, amount2=i.paid)

	section(_("8. Sales by item"))
	for it in r.sales_items:
		line(it.item_name or it.item, f"{it.uom} · {_('avg rate')} {it.rate} · {_('discount')} {it.discount}", qty=it.qty, amount=it.amount)

	section(_("9. Collections"))
	for c in r.collections:
		line(c.payment, " · ".join(x for x in (c.customer, c.against, c.invoice, c.mode) if x), amount=c.amount)

	section(_("9b. Customer returns"))
	for ret in [x for x in r.returns if x.visit]:
		detail = " · ".join(str(x) for x in (ret.customer_name or ret.customer, ret.reason, ret.condition, ret.against_invoice, ret.credit_note, ret.credit_applied) if x)
		line(f"{ret.item_name or ret.item_code} × {ret.qty} {ret.uom}", detail, qty=ret.qty, amount=ret.amount)

	section(_("10. Stock reconciliation"))
	for st in r.stock:
		detail = f"{_('issued')} {st.issued} · {_('top-up')} {st.topped_up} · {_('sold')} {st.sold} · {_('returned')} {st.returned} · {_('damaged')} {st.damaged} · {_('missing')} {st.missing}"
		line(st.item_name or st.item, detail, qty=st.missing, amount2=st.missing_value)

	section(_("11. Cash reconciliation"))
	c = r.cash
	line(_("Opening float"), amount=c.opening)
	line(_("Cash collected"), amount=c.collected)
	line(_("Expected"), amount=c.expected)
	line(_("Handed over"), amount=c.handed_over)
	line(_("Variance"), c.action, amount=c.variance)
	for d in c.denominations:
		line(_("Denomination"), f"{flt(d.denomination)} × {d.count}", amount=d.amount)
	for ch in c.cheques:
		line(_("Cheque"), f"{ch.cheque_no} · {ch.payment_entry}", amount=ch.amount)

	section(_("12. Sign-off"))
	for so in r.signoff:
		line(so.step, f"{so.full_name} ({so.user}) · {so.at}")
	return out
