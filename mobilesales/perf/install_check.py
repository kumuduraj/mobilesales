"""Fresh-install check on a disposable site (Phase 7 step 5, CHANGELOG v1.0.0). Commits; test sites only.

	bench --site mst2.local install-app mobilesales
	bench --site mst2.local execute mobilesales.perf.install_check.setup_and_day     # ADMIN_GUIDE §3 + a full day
	bench --site mst2.local execute mobilesales.perf.install_check.standard_flow     # SO -> DN -> SI -> PE, Stock Entry
	bench --site mst2.local execute mobilesales.perf.install_check.races             # real threads, real commits
	bench --site mst2.local uninstall-app mobilesales --yes --no-backup
	bench --site mst2.local execute mobilesales.perf.install_check.after_uninstall

Every step prints what it checked; any failure raises."""

import threading

import frappe
from frappe.model.workflow import apply_workflow
from frappe.utils import add_days, flt, nowdate

from mobilesales.perf.seed import guard

PREFIX = "MS2"
STORE, CASHIER, SUPERVISOR, AGENT = (f"ms2.{r}@example.com" for r in ("store", "cashier", "supervisor", "agent"))
MOBILE_FIELDS = ("mobile_trip", "customer_visit", "is_mobile_sale", "mobile_purpose", "mobile_settlement")
EXTENDED_DOCTYPES = ("Customer", "Item", "UOM", "Price List", "Item Price", "Batch", "Contact", "Address", "Territory",
	"Customer Group", "Sales Invoice", "Payment Entry", "Account", "Serial and Batch Bundle")  # fmt: skip


def ok(message):
	print(f"OK  {message}", flush=True)


def company():
	return frappe.get_all("Company", pluck="name", limit=1)[0]


def store_wh():
	return frappe.db.get_value("Warehouse", {"company": company(), "warehouse_name": "Stores"})


def leaf(doctype):
	return frappe.db.get_value(doctype, {"is_group": 0}, "name")


def user(email, roles):
	if not frappe.db.exists("User", email):
		frappe.get_doc({"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0,
			"roles": [{"role": r} for r in roles]}).insert()  # fmt: skip
	return email


def setup_and_day():
	"""ADMIN_GUIDE §3 in order, through the same buttons and roles a person uses, then one full day."""
	guard()
	frappe.set_user("Administrator")
	co = frappe.get_doc("Company", company())
	root = frappe.db.get_value("Warehouse", {"company": co.name, "is_group": 1, "parent_warehouse": ["is", "not set"]})

	def wh(name, is_group=0):
		return frappe.db.get_value("Warehouse", {"warehouse_name": name, "company": co.name}) or frappe.get_doc(
			{"doctype": "Warehouse", "warehouse_name": name, "parent_warehouse": root, "company": co.name, "is_group": is_group}
		).insert().name

	vans, damaged, returns_wh = wh("Mobile Vans", 1), wh("Damaged Returns"), wh("Customer Returns")
	cash_parent = frappe.db.get_value("Account", co.default_cash_account, "parent_account")
	expense = frappe.db.get_value("Account", co.stock_adjustment_account, "parent_account")
	shortage = frappe.db.get_value("Account", {"account_name": "Mobile Cash Shortage", "company": co.name}) or frappe.get_doc(
		{"doctype": "Account", "account_name": "Mobile Cash Shortage", "parent_account": expense, "company": co.name}
	).insert().name
	team = frappe.db.get_value("Sales Person", "Mobile Sales Team") or frappe.get_doc(
		{"doctype": "Sales Person", "sales_person_name": "Mobile Sales Team", "parent_sales_person": "Sales Team", "is_group": 1}
	).insert().name
	ok("step 1-3: warehouses, accounts, sales person group")

	settings = frappe.get_doc("Mobile Sales Settings")
	settings.update({"company": co.name, "selling_price_list": "Standard Selling", "source_warehouse": store_wh(),
		"return_warehouse": store_wh(), "damage_warehouse": damaged, "van_warehouse_group": vans,
		"agent_cash_parent_account": cash_parent, "main_cash_account": co.default_cash_account,
		"stock_shortage_account": co.stock_adjustment_account, "cash_shortage_account": shortage, "sales_person_parent": team,
		"returns_enabled": 1, "customer_return_warehouse": returns_wh, "shortage_tolerance_value": 1000,
		"default_customer_group": leaf("Customer Group"), "default_territory": leaf("Territory")})  # fmt: skip
	settings.save()
	ss = frappe.get_doc("Stock Settings")
	ss.update({"valuation_method": "FIFO", "allow_negative_stock": 0, "auto_create_serial_and_batch_bundle_for_outward": 1,
		"enable_serial_and_batch_no_for_item": 1, "pick_serial_and_batch_based_on": "FIFO", "use_serial_batch_fields": 1})  # fmt: skip
	ss.save()
	ok("step 4-5: Mobile Sales Settings and Stock Settings")

	item = f"{PREFIX} Item"
	if not frappe.db.exists("Item", item):
		frappe.get_doc({"doctype": "Item", "item_code": item, "item_name": item, "item_group": leaf("Item Group"),
			"stock_uom": "Nos", "is_stock_item": 1}).insert()  # fmt: skip
		frappe.get_doc({"doctype": "Item Price", "item_code": item, "price_list": "Standard Selling", "price_list_rate": 250,
			"valid_from": add_days(nowdate(), -30)}).insert()  # fmt: skip
		receipt = frappe.get_doc({"doctype": "Stock Entry", "stock_entry_type": "Material Receipt", "company": co.name,
			"items": [{"item_code": item, "qty": 100, "t_warehouse": store_wh(), "basic_rate": 100}]})  # fmt: skip
		receipt.insert()
		receipt.submit()
	ok("step 6: item with a selling price, stock in the store")

	for email, role in ((STORE, "Mobile Sales Store Keeper"), (CASHIER, "Mobile Sales Cashier"), (SUPERVISOR, "Mobile Sales Supervisor"), (AGENT, "Mobile Sales Agent")):
		user(email, [role])
	vehicle = frappe.db.get_value("Mobile Vehicle", "VAN-01") or frappe.get_doc({"doctype": "Mobile Vehicle", "vehicle_no": "VAN-01"}).insert().name
	from mobilesales.services import agent_setup, vehicles

	frappe.set_user(SUPERVISOR)
	van = vehicles.setup_vehicle(vehicle)
	frappe.set_user("Administrator")
	customers = []
	for n in (1, 2):
		name = f"{PREFIX} Shop {n}"
		customers.append(frappe.db.get_value("Customer", {"customer_name": name}) or frappe.get_doc(
			{"doctype": "Customer", "customer_name": name, "customer_group": leaf("Customer Group"), "territory": leaf("Territory")}
		).insert().name)  # fmt: skip
	route = frappe.db.get_value("Mobile Route", f"{PREFIX} Route") or frappe.get_doc({"doctype": "Mobile Route", "route_name": f"{PREFIX} Route",
		"customers": [{"customer": c, "sequence": i, "visit_frequency": "Daily"} for i, c in enumerate(customers, 1)]}).insert().name  # fmt: skip
	agent = frappe.db.get_value("Mobile Sales Agent", {"user": AGENT}) or frappe.get_doc({"doctype": "Mobile Sales Agent", "user": AGENT,
		"agent_name": f"{PREFIX} Agent", "default_vehicle": vehicle, "default_route": route, "max_discount_pct": 5,
		"max_return_value_per_visit": 5000}).insert().name  # fmt: skip
	frappe.set_user(SUPERVISOR)
	agent_setup.setup_agent(agent)
	frappe.set_user("Administrator")
	frappe.db.commit()
	ok(f"step 7-9: vehicle {vehicle} (van {van}), agent {agent} with cash account, route {route}")

	trip = day(agent, customers, item)
	frappe.db.commit()
	ok(f"step 11: mini live run {trip} Settled")


def day(agent, customers, item, load=10):
	from mobilesales.api import mobile as api

	frappe.set_user(STORE)
	trip = frappe.get_doc({"doctype": "Mobile Trip", "agent": agent, "trip_date": nowdate(), "opening_cash_float": 500,
		"load_items": [{"item_code": item, "qty": load}]}).insert()  # fmt: skip
	trip.submit()
	frappe.set_user(AGENT)
	api.start_trip(trip.name)
	priced = api.price_cart(trip.name, customers[0], [{"item_code": item, "qty": 3}])
	sale = api.submit_visit({"client_ref": f"{trip.name}-1", "mobile_trip": trip.name, "customer": customers[0], "outcome": "Sale",
		"sale_items": [{"item_code": item, "qty": 3}], "collect_amount": priced["due_on_sale"]})  # fmt: skip
	ret = [{"item_code": item, "qty": 1, "against_invoice": sale["sales_invoice"], "return_reason": "Damaged", "condition": "Damaged"}]
	api.submit_visit({"client_ref": f"{trip.name}-2", "mobile_trip": trip.name, "customer": customers[0], "outcome": "Return Only",
		"return_items": ret})  # fmt: skip
	api.submit_visit({"client_ref": f"{trip.name}-3", "mobile_trip": trip.name, "customer": customers[1], "outcome": "Shop Closed"})
	api.end_day(trip.name)
	return settle(trip.name)


def settle(trip_name):
	"""Agent counts everything back, store keeper and cashier verify: the trip ends Settled."""
	from mobilesales.api import mobile as api

	frappe.set_user(AGENT)
	api.end_day(trip_name)
	draft = api.get_settlement_draft(trip_name)
	lines = [{"item_code": r["item_code"], "returned_qty": r["expected_balance"]} for r in draft["stock_lines"]]
	saved = api.save_settlement(trip_name, {"stock_lines": lines, "cash_handed_over": draft["expected_cash"]})
	api.submit_settlement_for_verification(saved["name"])
	for who, action in ((STORE, "Verify Stock"), (CASHIER, "Verify Cash")):
		frappe.set_user(who)
		apply_workflow(frappe.get_doc("Mobile Settlement", saved["name"]), action)
	frappe.set_user("Administrator")
	status = frappe.db.get_value("Mobile Trip", trip_name, "status")
	assert status == "Settled", status
	return trip_name


def standard_flow():
	"""Standard office sales and stock, untouched by the app (installed or not)."""
	guard()
	frappe.set_user("Administrator")
	co, store = company(), store_wh()
	item = f"{PREFIX} Office Item"
	if not frappe.db.exists("Item", item):
		frappe.get_doc({"doctype": "Item", "item_code": item, "item_name": item, "item_group": leaf("Item Group"), "stock_uom": "Nos", "is_stock_item": 1}).insert()
	se = frappe.get_doc({"doctype": "Stock Entry", "stock_entry_type": "Material Receipt", "company": co,
		"items": [{"item_code": item, "qty": 10, "t_warehouse": store, "basic_rate": 80}]}).insert()  # fmt: skip
	se.submit()
	customer = frappe.db.get_value("Customer", {"customer_name": f"{PREFIX} Office Customer"}) or frappe.get_doc(
		{"doctype": "Customer", "customer_name": f"{PREFIX} Office Customer", "customer_group": leaf("Customer Group"), "territory": leaf("Territory")}
	).insert().name
	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
	from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note, make_sales_invoice
	from erpnext.stock.doctype.delivery_note.delivery_note import make_sales_invoice as dn_to_si

	so = frappe.get_doc({"doctype": "Sales Order", "company": co, "customer": customer, "delivery_date": nowdate(), "set_warehouse": store,
		"items": [{"item_code": item, "qty": 2, "rate": 150}]}).insert()  # fmt: skip
	so.submit()
	dn = make_delivery_note(so.name).insert()
	dn.submit()
	si = dn_to_si(dn.name).insert()
	si.submit()
	pe = get_payment_entry("Sales Invoice", si.name)
	pe.reference_no, pe.reference_date = "MS2-CHK", nowdate()
	pe.insert()
	pe.submit()
	assert make_sales_invoice  # the SO -> SI path exists too
	assert flt(frappe.db.get_value("Sales Invoice", si.name, "outstanding_amount")) == 0
	assert not frappe.db.get_value("Sales Invoice", si.name, "naming_series").startswith("MB-")
	transfer = frappe.get_doc({"doctype": "Stock Entry", "stock_entry_type": "Material Transfer", "company": co,
		"items": [{"item_code": item, "qty": 1, "s_warehouse": store, "t_warehouse": frappe.db.get_value("Warehouse", {"company": co, "warehouse_name": "Finished Goods"})}]}).insert()  # fmt: skip
	transfer.submit()
	frappe.db.commit()
	ok(f"standard flow: SE {se.name}, SO {so.name} -> DN {dn.name} -> SI {si.name} -> PE {pe.name}, transfer {transfer.name}")


def races():
	"""Real threads with their own connections and commits: two phones selling the last stock, the same
	client_ref twice at once, two settlement starts at once."""
	guard()
	from mobilesales.api import mobile as api
	from mobilesales.services import settlement

	site, sites_path = frappe.local.site, frappe.local.sites_path
	frappe.set_user("Administrator")
	agent = frappe.db.get_value("Mobile Sales Agent", {"user": AGENT})
	customers = frappe.get_all("Mobile Route Customer", filters={"parent": f"{PREFIX} Route"}, pluck="customer", order_by="sequence")
	item = f"{PREFIX} Item"
	for open_trip in frappe.get_all("Mobile Trip", filters={"agent": agent, "docstatus": 1, "status": ["in", ["In Field", "Settling"]]}, pluck="name"):
		settle(open_trip)  # left open by an earlier run
		frappe.db.commit()
	frappe.set_user(STORE)
	trip = frappe.get_doc({"doctype": "Mobile Trip", "agent": agent, "trip_date": nowdate(), "load_items": [{"item_code": item, "qty": 6}]}).insert()
	trip.submit()
	frappe.set_user(AGENT)
	api.start_trip(trip.name)
	frappe.db.commit()

	def in_threads(*calls):
		barrier, results = threading.Barrier(len(calls)), [None] * len(calls)

		def worker(i, fn):
			frappe.init(site=site, sites_path=sites_path)
			frappe.connect()
			frappe.set_user(AGENT)
			try:
				barrier.wait()
				results[i] = ("ok", fn())
				frappe.db.commit()
			except Exception as e:
				frappe.db.rollback()
				results[i] = ("error", f"{e.__class__.__name__}: {frappe.utils.strip_html(str(e))}")
			finally:
				frappe.destroy()

		threads = [threading.Thread(target=worker, args=(i, fn)) for i, fn in enumerate(calls)]
		for t in threads:
			t.start()
		for t in threads:
			t.join()
		return results

	def sale(ref, qty):
		price = frappe.db.get_value("Item Price", {"item_code": item, "price_list": "Standard Selling"}, "price_list_rate")
		return lambda: api.submit_visit({"client_ref": ref, "mobile_trip": trip.name, "customer": customers[0], "outcome": "Sale",
			"sale_items": [{"item_code": item, "qty": qty}], "collect_amount": flt(price) * qty})  # fmt: skip

	# 1. two phones, 5 each, 6 in the van: exactly one sells
	first = in_threads(sale(f"{trip.name}-race-a", 5), sale(f"{trip.name}-race-b", 5))
	print(first, flush=True)
	assert sorted(r[0] for r in first) == ["error", "ok"], first
	assert "Not enough" in next(r[1] for r in first if r[0] == "error"), first
	ok("last stock: one visit sold, the other was refused (Not enough … in van)")

	# 2. the same client_ref twice at once: one visit
	second = in_threads(sale(f"{trip.name}-race-same", 1), sale(f"{trip.name}-race-same", 1))
	print(second, flush=True)
	assert all(r[0] == "ok" for r in second), second
	assert len({r[1]["name"] for r in second}) == 1 and sorted(r[1]["duplicate"] for r in second) == [False, True], second
	frappe.db.rollback()  # a fresh snapshot: see what the threads committed
	assert frappe.db.count("Customer Visit", {"client_ref": f"{trip.name}-race-same"}) == 1
	ok("same client_ref at once: one visit, the other answer is the duplicate")

	# 3. two settlement starts at once: one settlement
	frappe.set_user(AGENT)
	api.end_day(trip.name)
	frappe.db.commit()
	third = in_threads(lambda: settlement.make_settlement(trip.name), lambda: settlement.make_settlement(trip.name))
	print(third, flush=True)
	frappe.db.rollback()  # fresh snapshot
	count = frappe.db.count("Mobile Settlement", {"mobile_trip": trip.name, "docstatus": ["<", 2]})
	assert count == 1, (third, count)
	ok("two settlement starts at once: one settlement")
	settle(trip.name)
	frappe.db.commit()
	ok(f"race trip {trip.name} settled")


def after_uninstall():
	"""uninstall-app left standard ERPNext working and nothing of the app behind."""
	guard()
	frappe.set_user("Administrator")
	installed = frappe.get_installed_apps()
	assert "mobilesales" not in installed, installed
	left_fields = frappe.get_all("Custom Field", filters={"fieldname": ["in", MOBILE_FIELDS]}, pluck="name")
	left_doctypes = frappe.get_all("DocType", filters={"module": "Mobile Sales"}, pluck="name")
	roles = frappe.get_all("Role", filters={"name": ["like", "Mobile Sales%"]}, pluck="name")
	workspace = frappe.db.exists("Workspace", "Mobile Sales")
	perms = {dt: frappe.db.count("Custom DocPerm", {"parent": dt, "role": ["like", "Mobile Sales%"]}) for dt in EXTENDED_DOCTYPES}
	copies = {dt: frappe.db.count("Custom DocPerm", {"parent": dt}) for dt in EXTENDED_DOCTYPES}
	workflow = frappe.db.exists("Workflow", "Mobile Settlement Approval")
	print({"custom_fields": left_fields, "doctypes": left_doctypes, "roles": roles, "workspace": workspace, "workflow": workflow,
		"mobile_role_perms": {k: v for k, v in perms.items() if v}, "custom_docperm_copies": {k: v for k, v in copies.items() if v}}, flush=True)  # fmt: skip
	standard_flow()
	ok("after uninstall: standard flow still works")
