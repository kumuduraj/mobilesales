"""Performance volume (Phase 7, docs/PERFORMANCE.md): `agents` agents x `days` days x `visits` visits, recorded through
the real phone API as the real role users and settled every evening through the workflow. Its own company
("_MS Perf Co") keeps it apart from the test suite's data. Runs on a test site only (allow_tests; never agrosys).
Commits after every trip and resumes where it stopped.

	bench --site mstest.local execute mobilesales.perf.seed.run --kwargs "{'agents': 10, 'days': 60, 'visits': 30}"

Each day is posted at its own date and times (load 06:00, visits from 08:00, settlement 20:00), as a real day is."""

import random
import time
from collections import defaultdict
from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta
from unittest.mock import patch

import frappe
from frappe.model.workflow import apply_workflow
from frappe.utils import add_days, flt, getdate, nowdate
from frappe.utils.nestedset import get_root_of

PREFIX = "_MS Perf"
COMPANY = f"{PREFIX} Co"
ABBR = "MSP"
ITEMS, BATCH_ITEMS, CUSTOMERS_PER_ROUTE = 20, 3, 40
STORE, CASHIER, SUPERVISOR = "perf.store@example.com", "perf.cashier@example.com", "perf.supervisor@example.com"


def guard():
	if not frappe.conf.allow_tests or frappe.local.site == "agrosys.evonet.lk":
		frappe.throw("mobilesales.perf runs on a test site only (allow_tests on, never agrosys).")


def run(agents=10, days=60, visits=30, seed=7):
	guard()
	frappe.flags.mute_emails = True
	rnd = random.Random(seed)
	start = getdate(add_days(nowdate(), -int(days)))
	world = ensure_world(int(agents), add_days(start, -1))
	frappe.db.commit()
	stats = defaultdict(int)
	began = time.monotonic()
	with patch("mobilesales.services.day_report.queue_attach"):  # no 600 PDFs on the shared workers
		for offset in range(int(days)):
			day = getdate(add_days(start, offset))
			for attempt in range(3):
				before = dict(stats)
				try:
					run_day(world, world.agents, day, int(visits), rnd, stats)
					frappe.db.commit()
					break
				except frappe.QueryDeadlockError:
					frappe.db.rollback()  # the shared workers touched the same rows: the whole day again
					stats.clear()
					stats.update(before)
					print(f"{day} deadlock, attempt {attempt + 1}", flush=True)
			else:
				frappe.throw(f"{day}: deadlocks three times running")
			print(f"{day} trips={stats['trips']} visits={stats['visits']} sales={stats['Sale']} {time.monotonic() - began:.0f}s", flush=True)
	frappe.set_user("Administrator")
	return dict(stats)


def smoke(visits=6):
	"""One agent, one day, then everything rolled back: checks the seed before the long run."""
	guard()
	frappe.flags.mute_emails = True
	stats = defaultdict(int)
	day = getdate(add_days(nowdate(), -60))
	try:
		world = ensure_world(1, add_days(day, -1))
		with patch("mobilesales.services.day_report.queue_attach"):
			began = time.monotonic()
			run_day(world, world.agents[:1], day, int(visits), random.Random(1), stats)
			print(f"smoke: {dict(stats)} in {time.monotonic() - began:.1f}s", flush=True)
	finally:
		frappe.set_user("Administrator")
		frappe.db.rollback()
	return dict(stats)


# Setup (idempotent)


def ensure_world(agent_count, receipt_day) -> frappe._dict:
	frappe.set_user("Administrator")
	if not frappe.db.exists("Company", COMPANY):
		frappe.get_doc({"doctype": "Company", "company_name": COMPANY, "abbr": ABBR, "default_currency": "LKR",
			"country": "Sri Lanka", "chart_of_accounts": "Standard with Numbers"}).insert()  # fmt: skip
	company = frappe.get_doc("Company", COMPANY)
	root_wh = frappe.db.get_value("Warehouse", {"company": COMPANY, "is_group": 1, "parent_warehouse": ["is", "not set"]})
	store = frappe.db.get_value("Warehouse", {"company": COMPANY, "warehouse_name": "Stores"})
	vans = warehouse(f"{PREFIX} Vans", root_wh, is_group=1)
	damaged = warehouse(f"{PREFIX} Damaged", root_wh)
	customer_returns = warehouse(f"{PREFIX} Customer Returns", root_wh)
	cash_group = frappe.db.get_value("Account", company.default_cash_account, "parent_account")
	expense_group = frappe.db.get_value("Account", company.stock_adjustment_account, "parent_account")
	cash_shortage = account(f"{PREFIX} Cash Shortage", expense_group)
	team = frappe.db.get_value("Sales Person", f"{PREFIX} Team") or frappe.get_doc(
		{"doctype": "Sales Person", "sales_person_name": f"{PREFIX} Team", "parent_sales_person": get_root_of("Sales Person"), "is_group": 1}
	).insert().name
	price_list = "Standard Selling"

	settings = frappe.get_doc("Mobile Sales Settings")
	settings.update({
		"company": COMPANY, "selling_price_list": price_list, "source_warehouse": store, "return_warehouse": store,
		"damage_warehouse": damaged, "van_warehouse_group": vans, "agent_cash_parent_account": cash_group,
		"main_cash_account": company.default_cash_account, "stock_shortage_account": company.stock_adjustment_account,
		"cash_shortage_account": cash_shortage, "sales_person_parent": team, "returns_enabled": 1,
		"customer_return_warehouse": customer_returns, "allow_credit_sales": 1, "shortage_tolerance_value": 100000,
		"default_customer_group": leaf("Customer Group"), "default_territory": leaf("Territory"),
	})  # fmt: skip
	settings.save()

	for email, role in ((STORE, "Mobile Sales Store Keeper"), (CASHIER, "Mobile Sales Cashier"), (SUPERVISOR, "Mobile Sales Supervisor")):
		user(email, role)

	items = []
	for n in range(1, ITEMS + 1):
		code = f"{PREFIX} Item {n:02d}"
		batch = n <= BATCH_ITEMS
		if not frappe.db.exists("Item", code):
			frappe.get_doc({"doctype": "Item", "item_code": code, "item_name": code, "item_group": leaf("Item Group"),
				"stock_uom": "Nos", "is_stock_item": 1, "has_batch_no": batch}).insert()  # fmt: skip
			frappe.get_doc({"doctype": "Item Price", "item_code": code, "price_list": price_list,
				"price_list_rate": 50 + 37 * n, "valid_from": receipt_day}).insert()  # fmt: skip
			for b in (1, 2) if batch else (None,):
				batch_no = None
				if b:
					batch_no = frappe.get_doc({"doctype": "Batch", "batch_id": f"{code} B{b}", "item": code}).insert().name
				receipt(code, 60000 if not batch else 30000, store, batch_no, receipt_day)
		items.append(frappe._dict(item_code=code, has_batch_no=batch))

	agents = []
	for n in range(1, agent_count + 1):
		email = f"perf.agent.{n:02d}@example.com"
		user(email, None)
		route_name = f"{PREFIX} Route {n:02d}"
		if not frappe.db.exists("Mobile Route", route_name):
			customers = [customer(f"{PREFIX} Shop {n:02d}-{c:02d}") for c in range(1, CUSTOMERS_PER_ROUTE + 1)]
			frappe.get_doc({"doctype": "Mobile Route", "route_name": route_name,
				"customers": [{"customer": c, "sequence": i, "visit_frequency": "Daily"} for i, c in enumerate(customers, 1)]}).insert()  # fmt: skip
		name = frappe.db.get_value("Mobile Sales Agent", {"user": email})
		if not name:
			vehicle = frappe.get_doc({"doctype": "Mobile Vehicle", "vehicle_no": f"{PREFIX} VAN-{n:02d}"}).insert().name
			name = frappe.get_doc({"doctype": "Mobile Sales Agent", "user": email, "agent_name": f"{PREFIX} Agent {n:02d}",
				"default_vehicle": vehicle, "default_route": route_name, "max_discount_pct": 5,
				"credit_limit_per_invoice": 20000, "max_return_value_per_visit": 10000}).insert().name  # fmt: skip
			from mobilesales.services import agent_setup, vehicles

			frappe.set_user(SUPERVISOR)
			agent_setup.setup_agent(name)
			vehicles.setup_vehicle(vehicle)
			frappe.set_user("Administrator")
		route = frappe.get_all("Mobile Route Customer", filters={"parent": route_name}, pluck="customer", order_by="sequence")
		agents.append(frappe._dict(name=name, user=email, route=route))
	others = [c for a in agents for c in a.route]
	return frappe._dict(company=COMPANY, stock_items=items, agents=agents, all_customers=others)


def warehouse(name, parent, is_group=0):
	existing = frappe.db.get_value("Warehouse", {"warehouse_name": name, "company": COMPANY})
	return existing or frappe.get_doc({"doctype": "Warehouse", "warehouse_name": name, "parent_warehouse": parent,
		"company": COMPANY, "is_group": is_group}).insert().name  # fmt: skip


def account(name, parent):
	existing = frappe.db.get_value("Account", {"account_name": name, "company": COMPANY})
	return existing or frappe.get_doc({"doctype": "Account", "account_name": name, "parent_account": parent,
		"company": COMPANY}).insert().name  # fmt: skip


def user(email, role):
	if not frappe.db.exists("User", email):
		frappe.get_doc({"doctype": "User", "email": email, "first_name": f"{PREFIX} {email.split('@')[0]}",
			"send_welcome_email": 0, "roles": [{"role": role}] if role else []}).insert()  # fmt: skip


def customer(name):
	return frappe.db.get_value("Customer", {"customer_name": name}) or frappe.get_doc({"doctype": "Customer",
		"customer_name": name, "customer_group": leaf("Customer Group"), "territory": leaf("Territory")}).insert().name  # fmt: skip


def leaf(doctype):
	return frappe.db.get_value(doctype, {"is_group": 0}, "name")


def receipt(item_code, qty, warehouse_name, batch_no, day):
	row = {"item_code": item_code, "qty": qty, "t_warehouse": warehouse_name, "basic_rate": 30}
	if batch_no:
		row.update({"use_serial_batch_fields": 1, "batch_no": batch_no})
	se = frappe.get_doc({"doctype": "Stock Entry", "stock_entry_type": "Material Receipt", "company": COMPANY,
		"set_posting_time": 1, "posting_date": day, "posting_time": "05:00:00", "items": [row]})  # fmt: skip
	se.insert()
	se.submit()


# One day


@contextmanager
def at(moment: datetime):
	"""Pin "now" for the app's own postings to the simulated moment."""
	day = moment.date().isoformat()
	with ExitStack() as stack:
		stack.enter_context(patch("mobilesales.api.mobile.now_datetime", return_value=moment))
		stack.enter_context(patch("mobilesales.services.stock.nowtime", return_value="06:00:00"))
		stack.enter_context(patch("mobilesales.services.settlement.nowdate", return_value=day))
		stack.enter_context(patch("mobilesales.services.settlement.nowtime", return_value="20:00:00"))
		yield


def run_day(world, agents, day, visit_count, rnd, stats):
	"""One day of every agent, in clock order as on a real day: all vans load at 06:00, visits from 08:00 every
	15 minutes (agents side by side), all settlements at 20:00. Postings never go back in time."""
	from mobilesales.api import mobile as api

	morning = datetime.combine(day, datetime.min.time()).replace(hour=6)
	days = []
	for agent in agents:
		if frappe.db.exists("Mobile Trip", {"agent": agent.name, "trip_date": day, "docstatus": 1}):
			continue
		frappe.set_user(STORE)
		trip = frappe.get_doc({"doctype": "Mobile Trip", "agent": agent.name, "trip_date": day,
			"opening_cash_float": 1000 if rnd.random() < 0.3 else 0,
			"load_items": [{"item_code": i.item_code, "qty": 12 if i.has_batch_no else 18} for i in world.stock_items]})  # fmt: skip
		with at(morning):
			trip.insert()
			trip.submit()
		stats["trips"] += 1
		frappe.set_user(agent.user)
		api.start_trip(trip.name)
		route = list(agent.route)
		rnd.shuffle(route)
		days.append(frappe._dict(agent=agent, trip=trip, route=route, van={i.item_code: (12 if i.has_batch_no else 18) for i in world.stock_items}))

	for index in range(visit_count):
		moment = morning.replace(hour=8) + timedelta(minutes=15 * index)
		for d in days:
			frappe.set_user(d.agent.user)
			customer = d.route[index % len(d.route)] if rnd.random() > 0.05 else rnd.choice(world.all_customers)  # 5% off route
			with at(moment):
				visit(api, d.trip, customer, d.van, world, rnd, stats, f"perf-{d.trip.name}-{index}")

	for d in days:
		frappe.set_user(d.agent.user)
		api.end_day(d.trip.name)
		draft = api.get_settlement_draft(d.trip.name)
		lines = []
		for row in draft["stock_lines"]:
			returned = flt(row["expected_balance"])
			if returned >= 1 and rnd.random() < 0.03:
				returned -= 1  # one missing now and then
			lines.append({"item_code": row["item_code"], "returned_qty": returned})
		handed = flt(draft["expected_cash"]) - (50 if rnd.random() < 0.05 else 0)
		with at(morning.replace(hour=20)):
			saved = api.save_settlement(d.trip.name, {"stock_lines": lines, "cash_handed_over": handed})
			api.submit_settlement_for_verification(saved["name"])
			for user_id, action in ((STORE, "Verify Stock"), (CASHIER, "Verify Cash")):
				frappe.set_user(user_id)
				apply_workflow(frappe.get_doc("Mobile Settlement", saved["name"]), action)
		stats["settlements"] += 1
	frappe.set_user("Administrator")


def visit(api, trip, customer, van, world, rnd, stats, ref):
	roll = rnd.random()
	payload = {"client_ref": ref, "mobile_trip": trip.name, "customer": customer}
	if roll < 0.62:
		lines = []
		for item in rnd.sample(world.stock_items, rnd.randint(1, 4)):
			qty = rnd.randint(1, 3)
			if van[item.item_code] >= qty:
				lines.append({"item_code": item.item_code, "qty": qty})
		if not lines:
			roll = 0.9
		else:
			returns_items = []
			if rnd.random() < 0.05:
				returns_items = return_line(api, customer, rnd, trip.trip_date)
			priced = api.price_cart(trip.name, customer, lines, returns_items=returns_items)
			credit = rnd.random() < 0.15 and priced["due_on_sale"] <= 20000
			payload.update({"outcome": "Sale", "sale_items": lines, "return_items": returns_items,
				"collect_amount": 0 if credit else priced["due_on_sale"]})  # fmt: skip
			if rnd.random() < 0.1:
				payload["sale_items"][0]["discount_percentage"] = 3
				payload["collect_amount"] = 0 if credit else api.price_cart(trip.name, customer, payload["sale_items"], returns_items=returns_items)["due_on_sale"]
			api.submit_visit(payload)
			for line in lines:
				van[line["item_code"]] -= line["qty"]
			stats["Sale"] += 1
			stats["visits"] += 1
			return
	if roll < 0.70:
		owed = frappe.get_all("Sales Invoice", filters={"customer": customer, "docstatus": 1, "outstanding_amount": [">", 0], "is_return": 0},
			fields=["name", "outstanding_amount"], limit=1)  # fmt: skip
		if owed:
			payload.update({"outcome": "Collection Only", "collect_previous": [{"sales_invoice": owed[0].name, "allocated": flt(owed[0].outstanding_amount)}]})
			api.submit_visit(payload)
			stats["Collection Only"] += 1
			stats["visits"] += 1
			return
	if roll < 0.74:
		returns_items = return_line(api, customer, rnd, trip.trip_date)
		if returns_items:
			payload.update({"outcome": "Return Only", "return_items": returns_items})
			api.submit_visit(payload)
			stats["Return Only"] += 1
			stats["visits"] += 1
			return
	if roll < 0.82:
		payload.update({"outcome": "Shop Closed"})
	else:
		payload.update({"outcome": "No Sale", "no_sale_reason": rnd.choice(frappe.get_all("Visit No Sale Reason", filters={"requires_remark": 0}, pluck="name"))})
	api.submit_visit(payload)
	stats[payload["outcome"]] += 1
	stats["visits"] += 1


def return_line(api, customer, rnd, day=None) -> list:
	"""One unit back against a recent invoice of an earlier day (agents are simulated one after another, so a
	same-day invoice of another agent may carry a later time than this visit)."""
	for invoice in api.get_customer_invoices(customer)[:3]:
		if day and getdate(invoice.posting_date) >= getdate(day):
			continue
		for line in invoice.returnable:
			if not frappe.get_cached_value("Item", line.item_code, "has_batch_no"):
				return [{"item_code": line.item_code, "qty": 1, "against_invoice": invoice.name,
					"return_reason": "Damaged", "condition": "Damaged" if rnd.random() < 0.5 else "Resaleable"}]  # fmt: skip
	return []
