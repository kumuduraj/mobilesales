"""Timings on the performance volume (docs/PERFORMANCE.md): phone API calls as a real agent, the settlement draft of a
full day, every report and chart as a supervisor, and the guards' cost on standard documents. Server-side wall time
(no HTTP), median and max of `repeat` runs. Creates today's trip inside a transaction that is rolled back.

	bench --site mstest.local execute mobilesales.perf.timings.run
"""

import random
import statistics
import time
from collections import defaultdict
from datetime import datetime, timedelta
from unittest.mock import patch

import frappe
from frappe.desk.query_report import run as run_report
from frappe.utils import add_days, getdate, nowdate

from mobilesales.perf import seed

TARGETS = {"api": 2.0, "settlement": 3.0, "report": 5.0}
REPORTS = (
	"Salesperson Performance", "Daily Trip Summary", "Customer Visit Register", "No Sale Reason Analysis",
	"Customer Stock Position", "Route Coverage", "Mobile Stock Variance", "Mobile Cash Variance",
	"Outstanding by Agent", "Customer Returns Register", "Discount Report",
)  # fmt: skip


def timed(fn, repeat):
	runs = []
	for _i in range(repeat):
		began = time.perf_counter()
		fn()
		runs.append(time.perf_counter() - began)
	return statistics.median(runs), max(runs)


def run(repeat=3, guard_calls=2000):
	seed.guard()
	from mobilesales.api import mobile as api
	from mobilesales.overrides import guards
	from mobilesales.services import reports

	results = []

	def record(kind, name, fn, n=repeat):
		median, worst = timed(fn, n)
		target = TARGETS.get(kind)
		results.append((kind, name, median, worst, target))
		print(f"{kind:10} {name:45} median {median:7.3f}s  max {worst:7.3f}s  {'OK' if not target or worst < target else 'OVER ' + str(target)}", flush=True)

	world = seed.ensure_world(0, add_days(nowdate(), -61))  # existing world, no new agents
	agents = frappe.get_all("Mobile Sales Agent", filters={"agent_name": ["like", f"{seed.PREFIX}%"]}, fields=["name", "user", "default_route"], order_by="name")
	agent = frappe._dict(agents[0])
	agent.route = frappe.get_all("Mobile Route Customer", filters={"parent": agent.default_route}, pluck="customer", order_by="sequence")
	counts = {dt: frappe.db.count(dt) for dt in ("Mobile Trip", "Customer Visit", "Sales Invoice", "Payment Entry", "GL Entry", "Stock Ledger Entry")}
	print("volume", counts, flush=True)
	try:
		with patch("mobilesales.services.day_report.queue_attach"):
			# today's trip with a full day of visits, so price_cart and the settlement draft see a real day
			today = getdate(nowdate())
			stats = defaultdict(int)
			trip_name = open_day(world, agent, today, 30, random.Random(3), stats)
			customer = agent.route[0]
			owed = frappe.get_all("Sales Invoice", filters={"customer": customer, "docstatus": 1, "outstanding_amount": [">", 0]}, pluck="name", limit=1)
			lines = [{"item_code": i.item_code, "qty": 1} for i in world.stock_items[3:7]]
			frappe.set_user(agent.user)
			now = datetime.now()
			with patch("mobilesales.api.mobile.now_datetime", return_value=now):
				record("api", "get_context", api.get_context)
				record("api", "get_route_plan", lambda: api.get_route_plan(trip_name))
				record("api", "get_van_stock", lambda: api.get_van_stock(trip_name))
				record("api", "get_my_day", lambda: api.get_my_day(trip_name))
				record("api", "get_visits", lambda: api.get_visits(trip_name))
				record("api", "search_customers", lambda: api.search_customers("Shop 01"))
				record("api", "get_customer (card)", lambda: api.get_customer(customer))
				record("api", "get_customer_invoices", lambda: api.get_customer_invoices(customer))
				record("api", "price_cart (4 lines)", lambda: api.price_cart(trip_name, customer, lines))
				ret = seed.return_line(api, customer, random.Random(1))
				record("api", "price_cart (4 lines + return + previous)", lambda: api.price_cart(
					trip_name, customer, lines, returns_items=ret,
					collect_previous=[{"sales_invoice": owed[0], "allocated": 1}] if owed else None))  # fmt: skip
				api.end_day(trip_name)
				record("settlement", "get_settlement_draft (30 visits)", lambda: api.get_settlement_draft(trip_name))
				record("settlement", "save_settlement", lambda: api.save_settlement(trip_name, {}))

			frappe.set_user(seed.SUPERVISOR)
			start, end = add_days(today, -60), today
			for report in REPORTS:
				record("report", f"{report} (60 days)", lambda r=report: run_report(r, {"company": seed.COMPANY, "from_date": start, "to_date": end}))
			for report in ("Daily Trip Summary", "Customer Visit Register", "Route Coverage"):
				record("report", f"{report} (1 day)", lambda r=report: run_report(r, {"company": seed.COMPANY, "from_date": add_days(today, -1), "to_date": add_days(today, -1)}))
			settled = frappe.get_all("Mobile Trip", filters={"status": "Settled"}, pluck="name", order_by="trip_date desc", limit=1)[0]
			record("report", "Mobile Trip Day Report", lambda: run_report("Mobile Trip Day Report", {"mobile_trip": settled}))
			for chart in ("chart_sales_by_agent", "chart_strike_rate", "chart_no_sale_reasons", "chart_returns_by_reason"):
				record("report", f"workspace {chart} (30 days)", getattr(reports, chart))
			frappe.set_user(agent.user)
			record("report", "Customer Visit Register as agent (60 days)", lambda: run_report("Customer Visit Register", {"from_date": start, "to_date": end}))

			frappe.set_user("Administrator")
			guard_results = guard_costs(guards, world, guard_calls)
	finally:
		frappe.set_user("Administrator")
		frappe.db.rollback()
	return {"volume": counts, "timings": results, "guards": guard_results}


def open_day(world, agent, day, visit_count, rnd, stats):
	"""seed.run_day up to End Day (no settlement): the trip stays open for the API timings."""
	from mobilesales.api import mobile as api

	morning = datetime.combine(day, datetime.min.time()).replace(hour=6)
	frappe.set_user(seed.STORE)
	trip = frappe.get_doc({"doctype": "Mobile Trip", "agent": agent.name, "trip_date": day,
		"load_items": [{"item_code": i.item_code, "qty": 12 if i.has_batch_no else 18} for i in world.stock_items]})  # fmt: skip
	with seed.at(morning):
		trip.insert()
		trip.submit()
	frappe.set_user(agent.user)
	van = {i.item_code: (12 if i.has_batch_no else 18) for i in world.stock_items}
	api.start_trip(trip.name)
	for index in range(visit_count):
		moment = morning.replace(hour=8) + timedelta(minutes=15 * index)
		with seed.at(moment):
			seed.visit(api, trip, agent.route[index % len(agent.route)], van, world, rnd, stats, f"perf-t-{trip.name}-{index}")
	return trip.name


def guard_costs(guards, world, calls):
	"""Per call cost of each guard on a standard document that touches nothing mobile (the office path)."""
	store = frappe.db.get_value("Warehouse", {"company": seed.COMPANY, "warehouse_name": "Stores"})
	item = world.stock_items[5].item_code
	customer = frappe.db.get_value("Customer", {"customer_name": ["like", f"{seed.PREFIX} Shop%"]})
	si = frappe.get_doc({"doctype": "Sales Invoice", "company": seed.COMPANY, "customer": customer, "update_stock": 1,
		"items": [{"item_code": item, "qty": 1, "rate": 100, "warehouse": store}]})  # fmt: skip
	se = frappe.get_doc({"doctype": "Stock Entry", "stock_entry_type": "Material Receipt", "company": seed.COMPANY,
		"items": [{"item_code": item, "qty": 1, "t_warehouse": store, "basic_rate": 10}]})  # fmt: skip
	cash = frappe.get_cached_value("Company", seed.COMPANY, "default_cash_account")
	je = frappe.get_doc({"doctype": "Journal Entry", "company": seed.COMPANY, "accounts": [
		{"account": cash, "debit_in_account_currency": 10}, {"account": cash, "credit_in_account_currency": 10}]})  # fmt: skip
	out = {}
	for name, fn, doc in (
		("validate_sales_invoice", guards.validate_sales_invoice, si),
		("validate_stock_entry", guards.validate_stock_entry, se),
		("validate_journal_entry", guards.validate_journal_entry, je),
	):
		fn(doc)  # warm the cached context
		began = time.perf_counter()
		for _i in range(calls):
			fn(doc)
		per_call = (time.perf_counter() - began) / calls
		out[name] = per_call
		print(f"guard      {name:45} {per_call * 1e6:8.1f} µs per call", flush=True)
	return out
