"""Phase 6 report logic (spec §7, §7.1): one place for every figure the Script Reports, the Mobile Trip Day
Report (report + A4 print), the daily email, the workspace charts and the phone's "My day" show, so they cannot
disagree. Figures come from submitted documents and the ledgers, never from client totals.

Agents only ever see their own trips: `restricted_agent()` is applied inside `trip_rows()`, whatever filters
the caller sends."""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import add_days, cint, date_diff, flt, get_datetime, getdate, nowdate

from mobilesales.services import invoicing, prints
from mobilesales.services import settings as ms_settings

AGENT_ROLE = "Mobile Sales Agent"
STAFF_ROLES = (
	"Mobile Sales Supervisor",
	"Mobile Sales Store Keeper",
	"Mobile Sales Cashier",
	"System Manager",
	"Accounts Manager",
)
NOBODY = "__no_agent__"
NO_SALE_OUTCOMES = ("No Sale", "Shop Closed")
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
ISSUE_PURPOSES = ("Issue", "Top-up")
QTY = 3


# scope


def restricted_agent(user=None):
	"""None for staff (all trips); the agent's own record for an agent; NOBODY for anyone else."""
	user = user or frappe.session.user
	roles = set(frappe.get_roles(user))
	if user == "Administrator" or roles & set(STAFF_ROLES):
		return None
	if AGENT_ROLE in roles:
		return frappe.db.get_value("Mobile Sales Agent", {"user": user}, "name") or NOBODY
	return NOBODY


def trip_rows(filters=None) -> list:
	"""Submitted (not cancelled) trips in scope: company, date range, agent, vehicle, route, territory, trip."""
	f = frappe._dict(filters or {})
	conditions = {"docstatus": 1}
	if f.company:
		conditions["company"] = f.company
	if f.from_date and f.to_date:
		conditions["trip_date"] = ["between", [getdate(f.from_date), getdate(f.to_date)]]
	elif f.from_date:
		conditions["trip_date"] = [">=", getdate(f.from_date)]
	elif f.to_date:
		conditions["trip_date"] = ["<=", getdate(f.to_date)]
	agent = restricted_agent()
	if agent:
		if f.agent and f.agent != agent:
			return []
		conditions["agent"] = agent
	elif f.agent:
		conditions["agent"] = f.agent
	for field in ("vehicle", "route"):
		if f.get(field):
			conditions[field] = f.get(field)
	if f.mobile_trip:
		conditions["name"] = f.mobile_trip
	if f.territory:
		conditions["route"] = ["in", routes_in_territory(f.territory) or [""]]
	return frappe.get_all(
		"Mobile Trip",
		filters=conditions,
		fields=[
			"name", "agent", "agent_name", "trip_date", "route", "vehicle", "helper", "status", "company",
			"van_warehouse", "opening_cash_float", "opening_float_journal",
		],
		order_by="trip_date asc, name asc",
	)  # fmt: skip


def routes_in_territory(territory) -> list:
	lft, rgt = frappe.db.get_value("Territory", territory, ["lft", "rgt"]) or (0, 0)
	territories = frappe.get_all("Territory", filters={"lft": [">=", lft], "rgt": ["<=", rgt]}, pluck="name")
	return frappe.get_all("Mobile Route", filters={"territory": ["in", territories or [""]]}, pluck="name")


def check_trip_access(trip_name):
	"""The Day Report and "My day": staff see any trip, an agent only their own."""
	if not trip_name or not frappe.db.exists("Mobile Trip", trip_name):
		frappe.throw(_("Mobile Trip {0} not found.").format(trip_name))
	if not trip_rows({"mobile_trip": trip_name}):
		frappe.throw(_("You can only see your own trips."), frappe.PermissionError)


# route plan


def planned_on(row, day) -> bool:
	"""Route customer due on a date: Daily always; Weekly / Fortnightly on their visit day (any day when
	none is set; the fortnight's week is not recorded, so Fortnightly counts every visit-day week)."""
	if row.visit_frequency == "Daily" or not row.visit_day:
		return True
	return row.visit_day == WEEKDAYS[getdate(day).weekday()]


def route_customers(route) -> list:
	if not route:
		return []
	return frappe.get_all(
		"Mobile Route Customer",
		filters={"parent": route, "parenttype": "Mobile Route"},
		fields=["customer", "customer_name", "sequence", "visit_frequency", "visit_day"],
		order_by="sequence asc, idx asc",
	)


# per-trip facts


VISIT_FIELDS = [
	"name", "mobile_trip", "visit_datetime", "customer", "customer_name", "outcome", "no_sale_reason", "remarks",
	"off_route", "latitude", "longitude", "sales_invoice", "payment_entry", "credit_journal", "credit_notes",
	"rounded_total", "collect_amount", "total_collected", "return_total", "credit_applied", "discount_amount",
	"additional_discount_percentage",
]  # fmt: skip
INVOICE_FIELDS = [
	"name", "mobile_trip", "customer", "customer_name", "is_return", "return_against", "posting_date", "total",
	"net_total", "total_taxes_and_charges", "discount_amount", "grand_total", "rounded_total", "disable_rounded_total",
	"outstanding_amount",
]  # fmt: skip
RETURN_LINE_FIELDS = [
	"parent", "item_code", "item_name", "qty", "uom", "stock_qty", "rate", "amount", "against_invoice", "return_reason",
	"condition", "remarks", "credit_note", "batch_info",
]  # fmt: skip
CHUNK = 50  # trips loaded together: one query per table, IN lists of a few thousand names at most


def trip_documents(trip_name) -> frappe._dict:
	"""Every submitted document of one trip, loaded once."""
	trip = frappe.db.get_value("Mobile Trip", trip_name, ["name", "route", "van_warehouse"], as_dict=True)
	return trips_documents([trip])[trip_name]


def iter_trip_documents(trips, summary=True):
	"""(trip, documents) for every trip row, loaded CHUNK trips at a time (the reports run over hundreds of trips;
	one set of queries per trip made them grow with the period). summary=False leaves out what only trip_summary()
	reads: sale line counts, payment references and the van's stock ledger."""
	for index in range(0, len(trips), CHUNK):
		chunk = trips[index : index + CHUNK]
		docs = trips_documents(chunk, summary)
		for trip in chunk:
			yield trip, docs[trip.name]


def by_key(rows, key) -> dict:
	out = defaultdict(list)
	for row in rows:
		out[row[key]].append(row)
	return out


def trips_documents(trips, summary=True) -> dict:
	"""{trip: documents} for trip rows (name, route, van_warehouse): the visits, invoices, payments, set-offs and
	settlement of each trip, plus what trip_summary() needs (route plan, visit discounts, sale line count, payment
	references, van stock by purpose) and the visits' return lines. One query per table for all the trips."""
	names = [t.name for t in trips]
	visits = frappe.get_all(
		"Customer Visit",
		filters={"mobile_trip": ["in", names], "docstatus": 1},
		fields=VISIT_FIELDS,
		order_by="visit_datetime asc, name asc",
	)
	invoices = frappe.get_all(
		"Sales Invoice",
		filters={"mobile_trip": ["in", names], "docstatus": 1},
		fields=INVOICE_FIELDS,
		order_by="posting_date asc, posting_time asc, name asc",
	)
	payments = frappe.get_all(
		"Payment Entry",
		filters={"mobile_trip": ["in", names], "docstatus": 1},
		fields=["name", "mobile_trip", "party", "party_name", "mode_of_payment", "paid_amount", "reference_no", "posting_date"],
		order_by="posting_date asc, name asc",
	)
	journals = frappe.get_all(
		"Journal Entry",
		filters={"mobile_trip": ["in", names], "docstatus": 1, "voucher_type": "Credit Note"},
		fields=["name", "mobile_trip"],
		order_by="creation desc",  # the order frappe.get_all gave the one-trip query
	)
	journal_rows = by_key(
		frappe.get_all(
			"Journal Entry Account",
			filters={"parent": ["in", [j.name for j in journals] or [""]], "reference_type": "Sales Invoice"},
			fields=prints.JOURNAL_ROW_FIELDS,
			order_by="parent asc, idx asc",
		),
		"parent",
	)
	visit_names = [v.name for v in visits]
	sales = [i for i in invoices if not i.is_return]
	refs = by_key(
		frappe.get_all(
			"Payment Entry Reference",
			filters={"parent": ["in", [p.name for p in payments] or [""]], "parenttype": "Payment Entry"},
			fields=["parent", "reference_name", "allocated_amount"],
			order_by="parent asc, idx asc",
		)
		if summary
		else [],
		"parent",
	)
	line_counts = sale_line_counts([i.name for i in sales]) if summary else {}
	returns = by_key(
		frappe.get_all(
			"Customer Visit Return Item",
			filters={"parent": ["in", visit_names or [""]], "parenttype": "Customer Visit"},
			fields=RETURN_LINE_FIELDS,
			order_by="parent asc, idx asc",
		),
		"parent",
	)
	discounts = visit_discounts(visit_names)
	plans = {route: route_customers(route) for route in {t.route for t in trips if t.route}}
	stock = stocks_by_purpose(trips, [i.name for i in sales], {i.name: i.mobile_trip for i in sales}) if summary else {}
	settlements = trip_settlements(names)
	visits_of, invoices_of, payments_of = by_key(visits, "mobile_trip"), by_key(invoices, "mobile_trip"), by_key(payments, "mobile_trip")
	journals_of = by_key(journals, "mobile_trip")
	out = {}
	for trip in trips:
		trip_visits = visits_of.get(trip.name, [])
		trip_invoices = invoices_of.get(trip.name, [])
		trip_payments = payments_of.get(trip.name, [])
		trip_sales = [i for i in trip_invoices if not i.is_return]
		out[trip.name] = frappe._dict(
			visits=trip_visits,
			sales=trip_sales,
			notes=[i for i in trip_invoices if i.is_return],
			payments=trip_payments,
			set_offs=[p for j in journals_of.get(trip.name, []) for p in prints.journal_pairs(j.name, journal_rows.get(j.name, []))],
			settlement=settlements.get(trip.name),
			route_plan=plans.get(trip.route, []),
			discounts=only(discounts, [v.name for v in trip_visits]),
			line_count=sum(line_counts.get(i.name, 0) for i in trip_sales),
			references=[r for p in trip_payments for r in refs.get(p.name, [])],
			return_lines=[line for v in trip_visits for line in returns.get(v.name, [])],
			stock=stock.get(trip.name) or defaultdict(empty_stock_row),
		)
	return out


def trip_settlements(trip_names) -> dict:
	"""{trip: its live settlement (submitted before draft, newest first)} with every child table, as plain rows."""
	parents = frappe.get_all(
		"Mobile Settlement",
		filters={"mobile_trip": ["in", trip_names], "docstatus": ["<", 2]},
		fields=["*"],
		order_by="docstatus desc, modified desc",
	)
	chosen = {}
	for row in parents:
		chosen.setdefault(row.mobile_trip, row)
	if not chosen:
		return {}
	names = [row.name for row in chosen.values()]
	for df in frappe.get_meta("Mobile Settlement").get_table_fields():
		children = by_key(
			frappe.get_all(
				df.options,
				filters={"parent": ["in", names], "parenttype": "Mobile Settlement", "parentfield": df.fieldname},
				fields=["*"],
				order_by="parent asc, idx asc",
			),
			"parent",
		)
		for row in chosen.values():
			row[df.fieldname] = children.get(row.name, [])
	return chosen


def payable(invoice) -> float:
	return invoicing.payable_amount(invoice)


def sale_lines(invoice_names) -> list:
	if not invoice_names:
		return []
	return frappe.get_all(
		"Sales Invoice Item",
		filters={"parent": ["in", invoice_names], "parenttype": "Sales Invoice"},
		fields=["parent", "item_code", "item_name", "qty", "stock_qty", "uom", "price_list_rate", "rate", "net_amount", "amount"],
		order_by="parent asc, idx asc",
	)


def no_discount():
	return frappe._dict(price_list_value=0.0, pricing_rule=0.0, line_manual=0.0)


def only(discounts, visit_names) -> dict:
	out = defaultdict(no_discount)
	out.update({name: discounts[name] for name in visit_names if name in discounts})
	return out


def sale_line_counts(invoice_names) -> dict:
	"""{invoice: number of lines}, from the parent index alone (the rows themselves are not read; the table only
	ever belongs to Sales Invoice, so no parenttype test)."""
	if not invoice_names:
		return {}
	return dict(
		frappe.db.sql(
			"""select parent, count(*) from `tabSales Invoice Item` where parent in %(names)s group by parent""",
			{"names": invoice_names},
		)
	)


def visit_discounts(visit_names) -> dict:
	"""{visit: {price_list_value, pricing_rule, line_manual}} from the visit lines (pricing_rule_rate is kept
	there: the manual discount applies on top of it, spec §5.1)."""
	out = defaultdict(no_discount)
	if not visit_names:
		return out
	for row in frappe.get_all(
		"Customer Visit Item",
		filters={"parent": ["in", visit_names], "parenttype": "Customer Visit"},
		fields=["parent", "qty", "price_list_rate", "pricing_rule_rate", "rate"],
	):
		base = flt(row.pricing_rule_rate) or flt(row.rate)
		list_rate = flt(row.price_list_rate) or base
		d = out[row.parent]
		d.price_list_value += flt(row.qty) * list_rate
		d.pricing_rule += flt(row.qty) * (list_rate - base)
		d.line_manual += flt(row.qty) * (base - flt(row.rate))
	return out


def empty_stock_row():
	return frappe._dict(issued=0.0, topped_up=0.0, sold=0.0, issued_value=0.0, sold_value=0.0)


def stock_by_purpose(trip, van) -> dict:
	"""{item: {issued, topped_up, sold, issued_value, sold_value}} from the van's Stock Ledger."""
	trip_row = frappe._dict(name=trip, van_warehouse=van)
	sales = frappe.get_all("Sales Invoice", filters={"mobile_trip": trip, "docstatus": 1, "is_return": 0}, pluck="name")
	return stocks_by_purpose([trip_row], sales, dict.fromkeys(sales, trip)).get(trip) or defaultdict(empty_stock_row)


def stocks_by_purpose(trips, sales, sale_trip) -> dict:
	"""{trip: stock_by_purpose} for trip rows (name, van_warehouse); `sales` their sale invoices, `sale_trip`
	invoice -> trip."""
	entries = {
		e.name: e
		for e in frappe.get_all(
			"Stock Entry",
			filters={"mobile_trip": ["in", [t.name for t in trips]], "docstatus": 1, "mobile_purpose": ["in", ISSUE_PURPOSES]},
			fields=["name", "mobile_purpose", "mobile_trip"],
		)
	}
	if not (entries or sales):
		return {}
	vans = {t.name: t.van_warehouse for t in trips}
	out = defaultdict(lambda: defaultdict(empty_stock_row))
	for sle in frappe.get_all(
		"Stock Ledger Entry",
		filters={"warehouse": ["in", list(set(vans.values()))], "is_cancelled": 0, "voucher_no": ["in", list(entries) + sales]},
		fields=["item_code", "warehouse", "voucher_type", "voucher_no", "actual_qty", "stock_value_difference"],
	):
		entry = entries.get(sle.voucher_no) if sle.voucher_type == "Stock Entry" else None
		trip = entry.mobile_trip if entry else sale_trip.get(sle.voucher_no)
		if not trip or vans.get(trip) != sle.warehouse:
			continue
		row = out[trip][sle.item_code]
		if entry:
			row["topped_up" if entry.mobile_purpose == "Top-up" else "issued"] += flt(sle.actual_qty)
			row.issued_value += flt(sle.stock_value_difference)
		else:
			row.sold -= flt(sle.actual_qty)
			row.sold_value -= flt(sle.stock_value_difference)
	return out


def trip_summary(trip, docs=None) -> frappe._dict:
	"""Every KPI of one trip (Daily Trip Summary row, Day Report KPIs, "My day", performance sums)."""
	docs = docs or trip_documents(trip.name)
	visits = docs.visits
	visited = {v.customer for v in visits}
	planned = [r for r in docs.route_plan if planned_on(r, trip.trip_date)]
	discounts = docs.discounts
	sale_payable = {i.name: payable(i) for i in docs.sales}
	# credit given at the sale: what the visit left open on its own invoice after its own return credit
	# (a later visit's return credit paying that invoice does not make it less of a credit sale)
	own_credit = defaultdict(float)
	for p in docs.set_offs:
		own_credit[(p.journal, p.invoice)] += p.amount
	credit_given = sum(
		max(flt(sale_payable.get(v.sales_invoice, v.rounded_total)) - flt(v.collect_amount) - own_credit[(v.credit_journal, v.sales_invoice)], 0)
		for v in visits
		if v.outcome == "Sale" and v.sales_invoice
	)
	stock = docs.stock
	s = docs.settlement
	s_items = s.stock_lines if s else []
	s_returns = s.return_lines if s else []
	trip_invoices = set(sale_payable)
	collected_current = collected_previous = 0.0
	for ref in docs.references:
		if ref.reference_name in trip_invoices:
			collected_current += flt(ref.allocated_amount)
		else:
			collected_previous += flt(ref.allocated_amount)
	return frappe._dict(
		trip=trip.name,
		trip_date=trip.trip_date,
		agent=trip.agent,
		agent_name=trip.agent_name,
		vehicle=trip.vehicle,
		route=trip.route,
		status=trip.status,
		visits=len(visits),
		planned_visits=len(planned),
		planned_visited=sum(1 for r in planned if r.customer in visited),
		missed=sum(1 for r in planned if r.customer not in visited),
		off_route=sum(1 for v in visits if v.off_route),
		sales_visits=sum(1 for v in visits if v.outcome == "Sale"),
		no_sale_visits=sum(1 for v in visits if v.outcome in NO_SALE_OUTCOMES),
		collection_visits=sum(1 for v in visits if v.outcome == "Collection Only"),
		return_visits=sum(1 for v in visits if v.outcome == "Return Only"),
		invoices=len(docs.sales),
		lines=docs.line_count,
		net_sales=flt(sum(flt(i.net_total) for i in docs.sales), 2),
		taxes=flt(sum(flt(i.total_taxes_and_charges) for i in docs.sales), 2),
		sales_total=flt(sum(sale_payable.values()), 2),
		price_list_value=flt(sum(d.price_list_value for d in discounts.values()), 2),
		pricing_rule_discount=flt(sum(d.pricing_rule for d in discounts.values()), 2),
		line_discount=flt(sum(d.line_manual for d in discounts.values()), 2),
		invoice_discount=flt(sum(flt(i.discount_amount) for i in docs.sales), 2),
		cash_collected=flt(sum(flt(p.paid_amount) for p in docs.payments), 2),
		collected_current=flt(collected_current, 2),
		collected_previous=flt(collected_previous, 2),
		credit_given=flt(credit_given, 2),
		return_value=flt(sum(abs(payable(n)) for n in docs.notes), 2),
		credit_applied=flt(sum(p.amount for p in docs.set_offs), 2),
		credit_left=flt(sum(-flt(n.outstanding_amount) for n in docs.notes if flt(n.outstanding_amount) < 0), 2),
		issued_qty=flt(sum(r.issued + r.topped_up for r in stock.values()), QTY),
		issued_value=flt(sum(r.issued_value for r in stock.values()), 2),
		sold_qty=flt(sum(r.sold for r in stock.values()), QTY),
		sold_value=flt(sum(r.sold_value for r in stock.values()), 2),
		returned_qty=flt(sum(flt(r.returned_qty) for r in s_items), QTY),
		damaged_qty=flt(sum(flt(r.damaged_qty) for r in s_items), QTY),
		missing_qty=flt(sum(flt(r.missing_qty) for r in s_items), QTY),
		missing_value=flt(sum(flt(r.missing_value) for r in s_items), 2),
		returned_value=flt(sum(flt(r.returned_qty) * flt(r.valuation_rate) for r in s_items), 2),
		damaged_value=flt(sum(flt(r.damaged_qty) * flt(r.valuation_rate) for r in s_items), 2),
		customer_returns_received=flt(sum(flt(r.received_qty) for r in s_returns), QTY),
		customer_returns_damaged=flt(sum(flt(r.damaged_qty) for r in s_returns), QTY),
		customer_returns_missing=flt(sum(flt(r.missing_qty) for r in s_returns), QTY),
		settlement=s.name if s else None,
		settlement_status=(s.workflow_state if s else None) or (_("Not started") if not s else None),
		settled=bool(s and s.docstatus == 1),
		opening_float=flt(s.opening_cash_float) if s else flt(trip.opening_cash_float),
		expected_cash=flt(s.expected_cash) if s else None,
		handed_over=flt(s.cash_handed_over) if s else None,
		cash_variance=flt(s.cash_variance) if s and s.docstatus == 1 else 0,
		variance_action=s.variance_action if s and flt(s.cash_variance) else None,
	)


def pct(part, whole) -> float:
	return flt(flt(part) / flt(whole) * 100, 2) if flt(whole) else 0


# the Day Report (spec §7.1)


def day_report(trip_name) -> frappe._dict:
	"""All sections of the Mobile Trip Day Report for one trip."""
	check_trip_access(trip_name)
	trip = trip_rows({"mobile_trip": trip_name})[0]
	trip.update(frappe.db.get_value("Mobile Trip", trip_name, ["helper", "route"], as_dict=True))
	docs = trip_documents(trip_name)
	summary = trip_summary(trip, docs)
	visits = docs.visits
	visit_names = [v.name for v in visits]
	credit_to = defaultdict(float)
	for p in docs.set_offs:
		credit_to[p.invoice] += p.amount

	visit_log = [
		frappe._dict(
			time=get_datetime(v.visit_datetime).strftime("%H:%M"),
			visit=v.name,
			customer=v.customer_name or v.customer,
			outcome=v.outcome,
			off_route=cint(v.off_route),
			reason=v.no_sale_reason,
			remarks=v.remarks,
			invoice=v.sales_invoice,
			amount=flt(v.rounded_total) if v.sales_invoice else 0,
			collected=flt(v.total_collected),
			returns=flt(v.return_total),
			map=f"https://maps.google.com/?q={v.latitude},{v.longitude}" if v.latitude or v.longitude else "",
		)
		for v in visits
	]
	visited = {v.customer for v in visits}
	missed = [r for r in docs.route_plan if planned_on(r, trip.trip_date) and r.customer not in visited]
	names = {v.name: v.customer_name or v.customer for v in visits}
	changes = [
		frappe._dict(customer=names.get(c.parent), field=c.field_label, old=c.old_value, new=c.new_value, status=c.status)
		for c in (
			frappe.get_all(
				"Customer Visit Change",
				filters={"parent": ["in", visit_names], "parenttype": "Customer Visit"},
				fields=["parent", "field_label", "old_value", "new_value", "status"],
				order_by="parent asc, idx asc",
			)
			if visit_names
			else []
		)
	]
	shelf = [
		frappe._dict(customer=names.get(r.parent), item=r.item_code, qty=flt(r.qty_on_shelf), uom=r.uom,
			expiry=r.expiry_date, competitor=r.competitor_item)  # fmt: skip
		for r in (
			frappe.get_all(
				"Customer Visit Shelf Stock",
				filters={"parent": ["in", visit_names], "parenttype": "Customer Visit"},
				fields=["parent", "item_code", "qty_on_shelf", "uom", "expiry_date", "competitor_item"],
				order_by="parent asc, idx asc",
			)
			if visit_names
			else []
		)
	]
	invoices = [
		frappe._dict(
			invoice=i.name,
			customer=i.customer_name or i.customer,
			net=flt(i.net_total),
			tax=flt(i.total_taxes_and_charges),
			total=payable(i),
			credit=flt(credit_to.get(i.name, 0), 2),
			paid=flt(payable(i) - flt(i.outstanding_amount) - credit_to.get(i.name, 0), 2),
			outstanding=flt(i.outstanding_amount),
		)
		for i in docs.sales
	]
	items = {}
	for line in sale_lines([i.name for i in docs.sales]):
		row = items.setdefault(
			(line.item_code, line.uom),
			frappe._dict(item=line.item_code, item_name=line.item_name, uom=line.uom, qty=0.0, amount=0.0, discount=0.0),
		)
		row.qty += flt(line.qty)
		row.amount += flt(line.amount)
		row.discount += max(flt(line.price_list_rate) - flt(line.rate), 0) * flt(line.qty)
	for row in items.values():
		row.rate = flt(row.amount / row.qty, 2) if row.qty else 0
		row.discount = flt(row.discount, 2)
	trip_invoices = {i.name for i in docs.sales}
	collections = []
	refs_of = by_key(docs.references, "parent")
	for p in docs.payments:
		for ref in refs_of.get(p.name) or [frappe._dict(reference_name=None, allocated_amount=p.paid_amount)]:
			collections.append(
				frappe._dict(payment=p.name, customer=p.party_name or p.party, invoice=ref.reference_name,
					against=_("Today") if ref.reference_name in trip_invoices else _("Previous"),
					mode=p.mode_of_payment, amount=flt(ref.allocated_amount))  # fmt: skip
			)
	returns = return_rows({"mobile_trip": trip_name}, docs=docs, trips=[trip])
	stock = []
	moved = docs.stock
	s = docs.settlement
	for row in s.stock_lines if s else []:
		m = moved.get(row.item_code) or frappe._dict(issued=row.issued_qty, topped_up=0)
		stock.append(
			frappe._dict(item=row.item_code, item_name=row.item_name, uom=row.uom, issued=flt(m.issued, QTY),
				topped_up=flt(m.topped_up, QTY), sold=flt(row.sold_qty), returned=flt(row.returned_qty),
				damaged=flt(row.damaged_qty), missing=flt(row.missing_qty), missing_value=flt(row.missing_value))  # fmt: skip
		)
	if not s:
		for code, m in moved.items():
			stock.append(
				frappe._dict(item=code, item_name=frappe.get_cached_value("Item", code, "item_name"), uom=frappe.get_cached_value("Item", code, "stock_uom"),
					issued=flt(m.issued, QTY), topped_up=flt(m.topped_up, QTY), sold=flt(m.sold, QTY), returned=0, damaged=0, missing=0, missing_value=0)  # fmt: skip
			)
	cash = frappe._dict(
		opening=summary.opening_float,
		collected=summary.cash_collected,
		expected=summary.expected_cash,
		handed_over=summary.handed_over,
		variance=flt(s.cash_variance) if s else None,
		action=summary.variance_action,
		denominations=[d for d in (s.denominations if s else []) if cint(d.count)],
		cheques=list(s.cheques_handed_over) if s else [],
	)
	first = visit_log[0].time if visit_log else None
	last = visit_log[-1].time if visit_log else None
	return frappe._dict(
		trip=trip,
		first_visit=first,
		last_visit=last,
		summary=summary,
		strike_rate=pct(summary.sales_visits, summary.visits),
		visit_log=visit_log,
		missed=missed,
		changes=changes,
		shelf=shelf,
		invoices=invoices,
		sales_items=list(items.values()),
		collections=collections,
		returns=returns,
		stock=stock,
		cash=cash,
		signoff=sign_off(s),
	)


def sign_off(settlement) -> list:
	"""Who moved the settlement through the workflow and when, spec §7.1 section 12: the "Workflow" comments
	apply_workflow() writes for every transition (state, user, time)."""
	if not settlement:
		return []
	labels = {
		"Pending Store": _("Agent (submitted for verification)"),
		"Pending Cashier": _("Store keeper (stock verified)"),
		"Pending Approval": _("Cashier (cash verified, needs approval)"),
		"Approved": _("Approved"),
		"Draft": _("Sent back"),
	}
	by_label = {_(state): state for state in labels}
	out = []
	previous = None
	for comment in frappe.get_all(
		"Comment",
		filters={"comment_type": "Workflow", "reference_doctype": "Mobile Settlement", "reference_name": settlement.name},
		fields=["owner", "creation", "content"],
		order_by="creation asc",
	):
		state = by_label.get(comment.content) or (comment.content if comment.content in labels else None)
		if state:
			# Verify Cash within the tolerance goes straight from Pending Cashier to Approved: the cashier's step
			step = _("Cashier (cash verified)") if state == "Approved" and previous == "Pending Cashier" else labels[state]
			out.append(
				frappe._dict(step=step, state=state, user=comment.owner,
					full_name=frappe.utils.get_fullname(comment.owner), at=comment.creation)  # fmt: skip
			)
			previous = state
	return out


# report rows


def return_rows(filters=None, docs=None, trips=None) -> list:
	"""Customer Returns Register: one row per return line (credit note, credit applied, settlement count of
	the trip x item on its first row), plus every other movement out of / into the customer return warehouse
	so the quantity column always adds up to the Stock Ledger."""
	trips = trips if trips is not None else trip_rows(filters)
	settings = ms_settings.get_settings()
	rows = []
	for trip, d in [(trips[0], docs)] if docs is not None and len(trips) == 1 else iter_trip_documents(trips, summary=False):
		visit_map = {v.name: v for v in d.visits}
		applied = defaultdict(list)
		for p in d.set_offs:
			applied[p.credit_note].append(p)
		note_out = {n.name: n for n in d.notes}
		counted = {r.item_code: r for r in (d.settlement.return_lines if d.settlement else [])}
		first_row = set()
		for line in d.return_lines:
			visit = visit_map[line.parent]
			note = note_out.get(line.credit_note)
			count = counted.get(line.item_code) if (trip.name, line.item_code) not in first_row else None
			first_row.add((trip.name, line.item_code))
			rows.append(
				frappe._dict(
					row_type=_("Return"),
					date=getdate(visit.visit_datetime),
					agent=trip.agent,
					agent_name=trip.agent_name,
					mobile_trip=trip.name,
					visit=visit.name,
					customer=visit.customer,
					customer_name=visit.customer_name,
					item_code=line.item_code,
					item_name=line.item_name,
					qty=flt(line.stock_qty or line.qty),
					uom=line.uom,
					rate=flt(line.rate),
					amount=flt(line.amount),
					reason=line.return_reason,
					condition=line.condition,
					remarks=line.remarks,
					against_invoice=line.against_invoice,
					credit_note=line.credit_note,
					credit_applied=", ".join(f"{p.invoice}: {flt(p.amount, 2)}" for p in applied.get(line.credit_note, [])),
					credit_applied_amount=flt(sum(p.amount for p in applied.get(line.credit_note, [])), 2),
					credit_left=flt(-flt(note.outstanding_amount), 2) if note and flt(note.outstanding_amount) < 0 else 0,
					received=flt(count.received_qty) if count else None,
					damaged=flt(count.damaged_qty) if count else None,
					missing=flt(count.missing_qty) if count else None,
					voucher=line.credit_note,
				)
			)
		# one credit note can carry several lines: count its applied credit once (on its first line)
		seen_notes = set()
		for r in rows:
			if r.mobile_trip == trip.name and r.row_type == _("Return"):
				if r.credit_note in seen_notes:
					r.credit_applied_amount = 0
				seen_notes.add(r.credit_note)
	if settings.customer_return_warehouse and (filters is None or not (filters or {}).get("mobile_trip")):
		rows += warehouse_moves(filters, settings.customer_return_warehouse, trips)
	return rows


def warehouse_moves(filters, warehouse, trips) -> list:
	"""Movements in the customer return warehouse that are not credit notes (settlement damage / shortage
	entries, manual Stock Entries), as negative / positive quantity rows."""
	f = frappe._dict(filters or {})
	if restricted_agent():
		return []  # agents see only their own returns, not the warehouse
	conditions = {"warehouse": warehouse, "is_cancelled": 0, "voucher_type": ["!=", "Sales Invoice"]}
	if f.from_date and f.to_date:
		conditions["posting_date"] = ["between", [getdate(f.from_date), getdate(f.to_date)]]
	trip_names = {t.name for t in trips}
	rows = []
	moves = frappe.get_all(
		"Stock Ledger Entry",
		filters=conditions,
		fields=["posting_date", "voucher_type", "voucher_no", "item_code", "actual_qty", "stock_uom"],
		order_by="posting_date asc, posting_time asc, creation asc",
	)
	entries = {
		e.name: e
		for e in frappe.get_all(
			"Stock Entry",
			filters={"name": ["in", [m.voucher_no for m in moves if m.voucher_type == "Stock Entry"] or [""]]},
			fields=["name", "mobile_trip", "mobile_purpose"],
		)
	}
	for sle in moves:
		entry = entries.get(sle.voucher_no) if sle.voucher_type == "Stock Entry" else None
		trip = entry.mobile_trip if entry else None
		if f.agent or f.vehicle or f.route or f.territory:
			if trip not in trip_names:
				continue
		rows.append(
			frappe._dict(
				row_type=_("Moved in") if flt(sle.actual_qty) > 0 else _("Moved out"),
				date=sle.posting_date,
				mobile_trip=trip,
				item_code=sle.item_code,
				item_name=frappe.get_cached_value("Item", sle.item_code, "item_name"),
				qty=flt(sle.actual_qty),
				uom=sle.stock_uom,
				voucher=sle.voucher_no,
				remarks=entry.mobile_purpose if entry else None,
			)
		)
	return rows


def visit_rows(filters=None) -> list:
	"""Customer Visit Register."""
	rows = []
	for trip, docs in iter_trip_documents(trip_rows(filters), summary=False):
		discounts = docs.discounts
		for v in docs.visits:
			d = discounts.get(v.name) or frappe._dict(line_manual=0)
			rows.append(
				frappe._dict(
					visit=v.name,
					visit_datetime=v.visit_datetime,
					agent=trip.agent,
					agent_name=trip.agent_name,
					vehicle=trip.vehicle,
					mobile_trip=trip.name,
					route=trip.route,
					customer=v.customer,
					customer_name=v.customer_name,
					territory=frappe.get_cached_value("Customer", v.customer, "territory"),
					outcome=v.outcome,
					off_route=cint(v.off_route),
					no_sale_reason=v.no_sale_reason,
					remarks=v.remarks,
					sales_invoice=v.sales_invoice,
					amount=flt(v.rounded_total) if v.sales_invoice else 0,
					discount=flt(flt(d.line_manual) + flt(v.discount_amount), 2) if v.sales_invoice else 0,
					return_total=flt(v.return_total),
					credit_applied=flt(v.credit_applied),
					collected=flt(v.total_collected),
					gps=f"https://maps.google.com/?q={v.latitude},{v.longitude}" if v.latitude or v.longitude else "",
				)
			)
	return rows


def discount_rows(filters=None) -> list:
	"""Discount Report: per invoice, the pricing-rule effect apart from the agent's manual discounts (line +
	invoice) and the manual share of the price-list value against the agent's cap."""
	rows = []
	caps = {}
	for trip, docs in iter_trip_documents(trip_rows(filters), summary=False):
		sale_visits = [v for v in docs.visits if v.sales_invoice]
		discounts = docs.discounts
		net_totals = {i.name: i.net_total for i in docs.sales}
		if trip.agent not in caps:
			caps[trip.agent] = flt(frappe.db.get_value("Mobile Sales Agent", trip.agent, "max_discount_pct"))
		cap = caps[trip.agent]
		for v in sale_visits:
			d = discounts[v.name]
			manual = flt(d.line_manual + flt(v.discount_amount), 2)
			share = pct(manual, d.price_list_value)
			rows.append(
				frappe._dict(
					sales_invoice=v.sales_invoice,
					date=getdate(v.visit_datetime),
					agent=trip.agent,
					agent_name=trip.agent_name,
					mobile_trip=trip.name,
					customer=v.customer,
					customer_name=v.customer_name,
					price_list_value=flt(d.price_list_value, 2),
					pricing_rule_discount=flt(d.pricing_rule, 2),
					line_discount=flt(d.line_manual, 2),
					invoice_discount=flt(v.discount_amount),
					invoice_discount_pct=flt(v.additional_discount_percentage),
					manual_discount=manual,
					manual_pct=share,
					cap_pct=cap,
					within_cap=_("Yes") if share <= cap + 0.0005 else _("No"),
					net_total=flt(net_totals.get(v.sales_invoice)),
				)
			)
	return rows


def stock_variance_rows(filters=None) -> list:
	"""Mobile Stock Variance: agent x item over the period, from the settled trips."""
	out = {}
	for trip, docs in iter_trip_documents(trip_rows(filters), summary=False):
		s = docs.settlement
		if not (s and s.docstatus == 1):
			continue
		for line in s.stock_lines:
			row = out.setdefault(
				(trip.agent, line.item_code),
				frappe._dict(agent=trip.agent, agent_name=trip.agent_name, item_code=line.item_code, item_name=line.item_name,
					uom=line.uom, trips=0, issued=0.0, sold=0.0, returned=0.0, damaged=0.0, missing=0.0, excess=0.0,
					issued_value=0.0, damaged_value=0.0, missing_value=0.0),  # fmt: skip
			)
			row.trips += 1
			row.issued += flt(line.issued_qty)
			row.sold += flt(line.sold_qty)
			row.returned += flt(line.returned_qty)
			row.damaged += flt(line.damaged_qty)
			row.missing += flt(line.missing_qty)
			row.excess += flt(line.excess_qty)
			row.issued_value += flt(line.issued_qty) * flt(line.valuation_rate)
			row.damaged_value += flt(line.damaged_qty) * flt(line.valuation_rate)
			row.missing_value += flt(line.missing_value)
	for row in out.values():
		for key in ("issued_value", "damaged_value", "missing_value"):
			row[key] = flt(row[key], 2)
	return list(out.values())


def cash_variance_rows(filters=None) -> list:
	"""Mobile Cash Variance: one row per settled trip."""
	rows = []
	settlements = {}
	trips = trip_rows(filters)
	for index in range(0, len(trips), CHUNK):
		settlements.update(trip_settlements([t.name for t in trips[index : index + CHUNK]]))
	for trip in trips:
		s = settlements.get(trip.name)
		if not (s and s.docstatus == 1):
			continue
		rows.append(
			frappe._dict(
				mobile_trip=trip.name, trip_date=trip.trip_date, agent=trip.agent, agent_name=trip.agent_name,
				vehicle=trip.vehicle, settlement=s.name, opening_float=flt(s.opening_cash_float),
				expected=flt(s.expected_cash), handed_over=flt(s.cash_handed_over), variance=flt(s.cash_variance),
				action=s.variance_action if flt(s.cash_variance) else None,
				journal=s.variance_journal or s.recovery_journal,
			)  # fmt: skip
		)
	return rows


def outstanding_rows(filters=None) -> list:
	"""Outstanding by Agent: the agent's mobile invoices still open, aged on the report date."""
	f = frappe._dict(filters or {})
	report_date = getdate(f.to_date or nowdate())
	trips = {t.name: t for t in trip_rows({k: v for k, v in f.items() if k not in ("from_date", "to_date")})}
	if not trips:
		return []
	out = {}
	for inv in frappe.get_all(
		"Sales Invoice",
		filters={"mobile_trip": ["in", list(trips)], "docstatus": 1, "is_return": 0, "outstanding_amount": [">", 0],
			"posting_date": ["<=", report_date]},  # fmt: skip
		fields=["name", "customer", "customer_name", "posting_date", "outstanding_amount", "mobile_trip"],
	):
		trip = trips[inv.mobile_trip]
		row = out.setdefault(
			(trip.agent, inv.customer),
			frappe._dict(agent=trip.agent, agent_name=trip.agent_name, customer=inv.customer, customer_name=inv.customer_name,
				invoices=0, outstanding=0.0, range_0_30=0.0, range_31_60=0.0, range_61_90=0.0, range_90_above=0.0,
				oldest=inv.posting_date),  # fmt: skip
		)
		age = date_diff(report_date, inv.posting_date)
		bucket = "range_0_30" if age <= 30 else "range_31_60" if age <= 60 else "range_61_90" if age <= 90 else "range_90_above"
		row.invoices += 1
		row.outstanding += flt(inv.outstanding_amount)
		row[bucket] += flt(inv.outstanding_amount)
		row.oldest = min(row.oldest, inv.posting_date)
	return list(out.values())


def stock_position_rows(filters=None) -> list:
	"""Customer Stock Position: latest shelf count per customer x item, days since the last visit and the last
	quantity bought on a mobile invoice (for next-load planning)."""
	trips = {t.name: t for t in trip_rows(filters)}
	if not trips:
		return []
	visits = frappe.get_all(
		"Customer Visit",
		filters={"mobile_trip": ["in", list(trips)], "docstatus": 1},
		fields=["name", "customer", "customer_name", "visit_datetime", "mobile_trip"],
		order_by="visit_datetime desc",
	)
	last_visit = {}
	for v in visits:
		last_visit.setdefault(v.customer, v)
	out = {}
	for shelf in frappe.get_all(
		"Customer Visit Shelf Stock",
		filters={"parent": ["in", [v.name for v in visits] or [""]], "parenttype": "Customer Visit"},
		fields=["parent", "item_code", "qty_on_shelf", "uom", "expiry_date", "competitor_item"],
	):
		visit = next(v for v in visits if v.name == shelf.parent)
		key = (visit.customer, shelf.item_code)
		if key in out and getdate(out[key].counted_on) >= getdate(visit.visit_datetime):
			continue
		out[key] = frappe._dict(
			customer=visit.customer, customer_name=visit.customer_name, item_code=shelf.item_code,
			qty_on_shelf=flt(shelf.qty_on_shelf), uom=shelf.uom, expiry_date=shelf.expiry_date,
			competitor_item=shelf.competitor_item, counted_on=getdate(visit.visit_datetime),
		)  # fmt: skip
	today = getdate(nowdate())
	for row in out.values():
		row.days_since_visit = date_diff(today, getdate(last_visit[row.customer].visit_datetime))
		last = frappe.db.sql(
			"""select i.qty, s.posting_date from `tabSales Invoice Item` i join `tabSales Invoice` s on s.name = i.parent
			where s.docstatus = 1 and s.is_return = 0 and s.is_mobile_sale = 1 and s.customer = %s and i.item_code = %s
			order by s.posting_date desc, s.posting_time desc limit 1""",
			(row.customer, row.item_code),
			as_dict=True,
		)
		row.last_purchase_qty = flt(last[0].qty) if last else 0
		row.last_purchase_date = last[0].posting_date if last else None
	return sorted(out.values(), key=lambda r: (r.customer_name or r.customer, r.item_code))


def coverage_rows(filters=None) -> list:
	"""Route Coverage: per trip day, each route customer planned / visited, plus off-route visits."""
	rows = []
	for trip in trip_rows(filters):
		visits = frappe.get_all(
			"Customer Visit",
			filters={"mobile_trip": trip.name, "docstatus": 1},
			fields=["customer", "customer_name", "outcome", "visit_datetime"],
			order_by="visit_datetime asc",
		)
		by_customer = {}
		for v in visits:
			by_customer.setdefault(v.customer, v)
		plan = route_customers(trip.route)
		out_of_sequence = visited_out_of_sequence(plan, visits)
		on_route = set()
		for r in plan:
			on_route.add(r.customer)
			planned = planned_on(r, trip.trip_date)
			v = by_customer.get(r.customer)
			if not planned and not v:
				continue
			rows.append(
				frappe._dict(
					trip_date=trip.trip_date, mobile_trip=trip.name, agent=trip.agent, agent_name=trip.agent_name,
					route=trip.route, sequence=r.sequence, customer=r.customer, customer_name=r.customer_name,
					planned=cint(planned), visited=cint(bool(v)), outcome=v.outcome if v else None,
					status=_("Visited") if planned and v else _("Missed") if planned else _("Visited (not due)"),
					out_of_sequence=cint(r.customer in out_of_sequence),
					trip_out_of_sequence=len(out_of_sequence),
				)  # fmt: skip
			)
		for customer, v in by_customer.items():
			if customer not in on_route:
				rows.append(
					frappe._dict(
						trip_date=trip.trip_date, mobile_trip=trip.name, agent=trip.agent, agent_name=trip.agent_name,
						route=trip.route, customer=customer, customer_name=v.customer_name, planned=0, visited=1,
						outcome=v.outcome, status=_("Off route"),
					)  # fmt: skip
				)
	return rows


def visited_out_of_sequence(plan, visits) -> set:
	"""Route customers first visited after a customer further down the route was already visited (the agent
	may visit in any order; this only reports it)."""
	sequence = {r.customer: cint(r.sequence) for r in plan}
	furthest, out, seen = 0, set(), set()
	for v in visits:  # visit time order
		if v.customer in seen or v.customer not in sequence:
			continue
		seen.add(v.customer)
		if sequence[v.customer] < furthest:
			out.add(v.customer)
		furthest = max(furthest, sequence[v.customer])
	return out


def no_sale_rows(filters=None, group_by="agent") -> list:
	"""No Sale Reason Analysis: reason x agent (or territory): count and % of all visits in that group."""
	totals = defaultdict(int)
	counts = defaultdict(int)
	labels = {}
	for trip in trip_rows(filters):
		for v in frappe.get_all(
			"Customer Visit",
			filters={"mobile_trip": trip.name, "docstatus": 1},
			fields=["customer", "outcome", "no_sale_reason"],
		):
			group = trip.agent if group_by != "territory" else frappe.get_cached_value("Customer", v.customer, "territory")
			labels[group] = trip.agent_name if group_by != "territory" else group
			totals[group] += 1
			if v.outcome in NO_SALE_OUTCOMES:
				reason = v.no_sale_reason or _("Shop Closed")
				counts[(group, reason)] += 1
	rows = []
	for (group, reason), count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
		category = frappe.db.get_value("Visit No Sale Reason", reason, "category") if frappe.db.exists("Visit No Sale Reason", reason) else None
		rows.append(
			frappe._dict(group=group, group_name=labels[group], reason=reason, category=category or _("Shop Closed"),
				count=count, visits=totals[group], pct=pct(count, totals[group]))  # fmt: skip
		)
	return rows


def performance_rows(filters=None) -> list:
	"""Salesperson Performance: agent over the period."""
	out = {}
	for trip, docs in iter_trip_documents(trip_rows(filters)):
		s = trip_summary(trip, docs)
		row = out.setdefault(
			trip.agent,
			frappe._dict(agent=trip.agent, agent_name=trip.agent_name, trips=0, days=set(), visits=0, planned_visits=0,
				planned_visited=0, sales_visits=0, invoices=0, lines=0, net_sales=0.0, sales_total=0.0, collections=0.0,
				credit_given=0.0, return_value=0.0, issued_qty=0.0, returned_qty=0.0, damaged_qty=0.0, missing_value=0.0,
				cash_variance=0.0, manual_discount=0.0, price_list_value=0.0, customer_returns_received=0.0),  # fmt: skip
		)
		row.trips += 1
		row.days.add(trip.trip_date)
		for key in ("visits", "planned_visits", "planned_visited", "sales_visits", "invoices", "lines", "net_sales",
			"sales_total", "credit_given", "return_value", "issued_qty", "returned_qty", "damaged_qty", "missing_value",
			"cash_variance", "price_list_value", "customer_returns_received"):  # fmt: skip
			row[key] += flt(s[key])
		row.collections += s.cash_collected
		row.manual_discount += s.line_discount + s.invoice_discount
	rows = []
	for row in out.values():
		days = len(row.pop("days"))
		row.update(
			working_days=days,
			route_coverage=pct(row.planned_visited, row.planned_visits),
			strike_rate=pct(row.sales_visits, row.visits),
			avg_invoice=flt(row.sales_total / row.invoices, 2) if row.invoices else 0,
			lines_per_invoice=flt(row.lines / row.invoices, 2) if row.invoices else 0,
			collection_pct=pct(row.collections, row.sales_total),
			returns_pct=pct(row.returned_qty, row.issued_qty),
			damage_pct=pct(row.damaged_qty, row.issued_qty),
			discount_pct=pct(row.manual_discount, row.price_list_value),
			sales_per_day=flt(row.sales_total / days, 2) if days else 0,
		)
		for key in ("net_sales", "sales_total", "collections", "credit_given", "return_value", "missing_value",
			"cash_variance", "manual_discount", "price_list_value"):  # fmt: skip
			row[key] = flt(row[key], 2)
		rows.append(row)
	return sorted(rows, key=lambda r: r.agent_name or r.agent)


def trip_summary_rows(filters=None) -> list:
	"""Daily Trip Summary."""
	return [trip_summary(trip, docs) for trip, docs in iter_trip_documents(trip_rows(filters))]


# phone, charts, email


def my_day(trip_name) -> dict:
	"""The phone's Today screen: the same figures as the Day Report KPIs."""
	check_trip_access(trip_name)
	trip = trip_rows({"mobile_trip": trip_name})[0]
	s = trip_summary(trip)
	return {
		"visits": s.visits,
		"planned_visits": s.planned_visits,
		"sales_visits": s.sales_visits,
		"invoices": s.invoices,
		"sales_total": s.sales_total,
		"cash_collected": s.cash_collected,
		"credit_given": s.credit_given,
		"return_value": s.return_value,
		"credit_applied": s.credit_applied,
	}


def last_days(days=30):
	end = getdate(nowdate())
	return add_days(end, -(days - 1)), end


def mobile_day_report(trip_name) -> frappe._dict:
	"""Jinja (hooks.jinja): the A4 "Mobile Trip Day Report" print on Mobile Settlement."""
	return day_report(trip_name)


# workspace charts (Dashboard Chart Sources, last 30 days)


def _chart(labels, values, name):
	return {"labels": labels, "datasets": [{"name": name, "values": values}]}


def chart_sales_by_agent(days=30):
	from_date, to_date = last_days(days)
	totals = defaultdict(float)
	for trip, docs in iter_trip_documents(trip_rows({"from_date": from_date, "to_date": to_date})):
		totals[trip.agent_name or trip.agent] += trip_summary(trip, docs).sales_total
	return _chart(list(totals), [flt(v, 2) for v in totals.values()], _("Mobile sales"))


def chart_strike_rate(days=30):
	from_date, to_date = last_days(days)
	visits, sales = defaultdict(int), defaultdict(int)
	for trip in trip_rows({"from_date": from_date, "to_date": to_date}):
		for v in frappe.get_all("Customer Visit", filters={"mobile_trip": trip.name, "docstatus": 1}, pluck="outcome"):
			visits[trip.trip_date] += 1
			sales[trip.trip_date] += v == "Sale"
	days_sorted = sorted(visits)
	return _chart([frappe.format(d, "Date") for d in days_sorted], [pct(sales[d], visits[d]) for d in days_sorted], _("Strike rate %"))


def chart_no_sale_reasons(days=30):
	from_date, to_date = last_days(days)
	counts = defaultdict(int)
	for row in no_sale_rows({"from_date": from_date, "to_date": to_date}):
		counts[row.reason] += row.count
	return _chart(list(counts), list(counts.values()), _("No-sale visits"))


def chart_returns_by_reason(days=30):
	from_date, to_date = last_days(days)
	totals = defaultdict(float)
	for row in return_rows({"from_date": from_date, "to_date": to_date}):
		if row.visit:
			totals[row.reason or _("Not set")] += flt(row.amount)
	return _chart(list(totals), [flt(v, 2) for v in totals.values()], _("Returns (credit)"))
