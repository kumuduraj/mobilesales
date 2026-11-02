"""Shared test scaffolding: own "_MS Test" masters under the site's existing company, patched
Mobile Sales Settings (never saved) and a fresh guard context per call. Each test runs inside a
savepoint that is rolled back; the class rolls back everything and checks counts at the end."""

from contextlib import contextmanager
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, nowdate
from frappe.utils.nestedset import get_root_of

from mobilesales.overrides import guards
from mobilesales.services import agent_setup, vehicles

PREFIX = "_MS Test"
COUNTED_DOCTYPES = (
	"Warehouse",
	"Account",
	"Mode of Payment",
	"Sales Person",
	"User Permission",
	"User",
	"Mobile Sales Agent",
	"Mobile Vehicle",
	"Mobile Trip",
	"Item",
	"Batch",
	"Customer",
	"Sales Invoice",
	"Customer Visit",
	"Item Price",
	"Pricing Rule",
	"Contact",
	"Address",
	"Stock Entry",
	"Journal Entry",
	"Payment Entry",
	"Stock Ledger Entry",
	"GL Entry",
	"Serial and Batch Bundle",
)


# Real role users for business flows (CLAUDE.md rule 13). "office" is standard, non-mobile staff.
ROLE_USERS = {
	"store": ("ms.test.store@example.com", ("Mobile Sales Store Keeper",)),
	"cashier": ("ms.test.cashier@example.com", ("Mobile Sales Cashier",)),
	"supervisor": ("ms.test.supervisor@example.com", ("Mobile Sales Supervisor",)),
	"office": ("ms.test.office@example.com", ("Accounts User", "Accounts Manager", "Sales User", "Stock User")),
}


def make_role_users() -> frappe._dict:
	users = frappe._dict()
	for key, (email, roles) in ROLE_USERS.items():
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": email,
					"first_name": f"{PREFIX} {key.title()}",
					"send_welcome_email": 0,
					"roles": [{"role": role} for role in roles],
				}
			).insert()
		users[key] = email
	return users


@contextmanager
def as_user(user):
	"""Run a business flow as a real role user; back to the previous user after (nested blocks must not
	fall back to Administrator mid-flow)."""
	previous = frappe.session.user
	frappe.set_user(user)
	try:
		yield
	finally:
		frappe.set_user(previous)


def counts():
	return {dt: frappe.db.count(dt) for dt in COUNTED_DOCTYPES}


def site_company():
	return frappe.defaults.get_global_default("company") or frappe.get_all("Company", pluck="name", limit=1)[0]


def leaf(doctype):
	return frappe.db.get_value(doctype, {"is_group": 0}, "name")


def make_warehouse(name, parent, company, is_group=0):
	return (
		frappe.get_doc(
			{
				"doctype": "Warehouse",
				"warehouse_name": name,
				"parent_warehouse": parent,
				"company": company,
				"is_group": is_group,
			}
		)
		.insert()
		.name
	)


def make_receipt(company, item_code, qty, warehouse, rate=50, batch_no=None, posting_date=None):
	row = {"item_code": item_code, "qty": qty, "t_warehouse": warehouse, "basic_rate": rate}
	if batch_no:
		row.update({"use_serial_batch_fields": 1, "batch_no": batch_no})
	se = frappe.get_doc(
		{
			"doctype": "Stock Entry",
			"stock_entry_type": "Material Receipt",
			"company": company,
			"set_posting_time": 1 if posting_date else 0,
			"posting_date": posting_date or nowdate(),
			"items": [row],
		}
	)
	se.insert()
	se.submit()
	return se


class MobileSalesTestCase(IntegrationTestCase):
	SHOW_TRANSACTION_COMMIT_WARNINGS = True
	AGENT_USERS = ("ms.test.agent.a@example.com", "ms.test.agent.b@example.com")
	EXTRA_USERS = tuple(email for email, _roles in ROLE_USERS.values())  # caches cleared at the end

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.counts_before = counts()
		cls.users = make_role_users()

		cls.company = site_company()
		root_wh = frappe.db.get_value(
			"Warehouse", {"company": cls.company, "is_group": 1, "parent_warehouse": ["is", "not set"]}
		)
		cls.store = make_warehouse(f"{PREFIX} Store", root_wh, cls.company)
		cls.van_group = make_warehouse(f"{PREFIX} Vans", root_wh, cls.company, is_group=1)

		cls.main_cash = frappe.get_cached_value("Company", cls.company, "default_cash_account")
		cash_root = frappe.db.get_value("Account", cls.main_cash, "parent_account")
		cls.cash_group = (
			frappe.get_doc(
				{
					"doctype": "Account",
					"account_name": f"{PREFIX} Cash In Hand",
					"parent_account": cash_root,
					"company": cls.company,
					"is_group": 1,
					"account_type": "Cash",
				}
			)
			.insert()
			.name
		)
		cls.sales_team = (
			frappe.get_doc(
				{
					"doctype": "Sales Person",
					"sales_person_name": f"{PREFIX} Sales Team",
					"parent_sales_person": get_root_of("Sales Person"),
					"is_group": 1,
				}
			)
			.insert()
			.name
		)

		cls.price_list = frappe.db.get_value(
			"Price List", {"selling": 1, "enabled": 1, "currency": frappe.get_cached_value("Company", cls.company, "default_currency")}
		)
		cls.settings = frappe.get_doc("Mobile Sales Settings")
		cls.settings.update(
			{
				"company": cls.company,
				"source_warehouse": cls.store,
				"return_warehouse": cls.store,
				"van_warehouse_group": cls.van_group,
				"agent_cash_parent_account": cls.cash_group,
				"main_cash_account": cls.main_cash,
				"sales_person_parent": cls.sales_team,
				"selling_price_list": cls.price_list,
				"sinv_naming_series": "MB-SINV-.YY.-.#####",
			}
		)
		cls._patches = [
			patch("mobilesales.services.settings.get_settings", return_value=cls.settings),
			patch("mobilesales.overrides.guards.get_guard_context", side_effect=guards.build_guard_context),
		]
		for p in cls._patches:
			p.start()

		cls.customer = (
			frappe.get_doc(
				{
					"doctype": "Customer",
					"customer_name": f"{PREFIX} Customer",
					"customer_group": leaf("Customer Group"),
					"territory": leaf("Territory"),
				}
			)
			.insert()
			.name
		)
		cls.plain_item = cls.make_item(f"{PREFIX} Plain Item")
		cls.batch_item = cls.make_item(f"{PREFIX} Batch Item", has_batch_no=1)
		cls.batch_a = frappe.get_doc({"doctype": "Batch", "batch_id": f"{PREFIX} Batch A", "item": cls.batch_item}).insert().name
		cls.batch_b = frappe.get_doc({"doctype": "Batch", "batch_id": f"{PREFIX} Batch B", "item": cls.batch_item}).insert().name
		for item_code, rate in ((cls.plain_item, 100), (cls.batch_item, 200)):
			frappe.get_doc(
				{"doctype": "Item Price", "item_code": item_code, "price_list": cls.price_list, "price_list_rate": rate}
			).insert()
		make_receipt(cls.company, cls.plain_item, 50, cls.store)
		make_receipt(cls.company, cls.batch_item, 5, cls.store, batch_no=cls.batch_a, posting_date=add_days(nowdate(), -2))
		make_receipt(cls.company, cls.batch_item, 10, cls.store, batch_no=cls.batch_b, posting_date=add_days(nowdate(), -1))

		cls.agents = []
		for idx, user in enumerate(cls.AGENT_USERS):
			name = f"{PREFIX} Agent {'AB'[idx]}"
			frappe.get_doc({"doctype": "User", "email": user, "first_name": name, "send_welcome_email": 0}).insert()
			vehicle = frappe.get_doc({"doctype": "Mobile Vehicle", "vehicle_no": f"{PREFIX} VAN-{'AB'[idx]}"}).insert().name
			agent = frappe.get_doc(
				{"doctype": "Mobile Sales Agent", "user": user, "agent_name": name, "default_vehicle": vehicle}
			).insert()
			with as_user(cls.users.supervisor):
				agent_setup.setup_agent(agent.name)
				vehicles.setup_vehicle(vehicle)
			agent = frappe.get_doc("Mobile Sales Agent", agent.name)
			# In memory only: "this agent's van" for the tests; the van belongs to the default vehicle.
			agent.van_warehouse = frappe.db.get_value("Mobile Vehicle", vehicle, "van_warehouse")
			cls.agents.append(agent)
		cls.agent_a, cls.agent_b = cls.agents

	@classmethod
	def make_item(cls, name, has_batch_no=0):
		return (
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": name,
					"item_name": name,
					"item_group": leaf("Item Group"),
					"stock_uom": "Nos",
					"is_stock_item": 1,
					"has_batch_no": has_batch_no,
				}
			)
			.insert()
			.name
		)

	@classmethod
	def tearDownClass(cls):
		for p in cls._patches:
			p.stop()
		frappe.set_user("Administrator")
		frappe.db.rollback()
		for user in (*cls.AGENT_USERS, *cls.EXTRA_USERS):
			frappe.clear_cache(user=user)
		counts_after = counts()
		super().tearDownClass()
		if counts_after != cls.counts_before:
			diff = {
				dt: (cls.counts_before[dt], counts_after[dt])
				for dt in COUNTED_DOCTYPES
				if cls.counts_before[dt] != counts_after[dt]
			}
			raise AssertionError(f"Test records left behind (before, after): {diff}")

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		frappe.db.savepoint("ms_test")
		self.addCleanup(self._restore)
		# Nothing inside a test may commit: a commit would write test data to the live site.
		guard = patch.object(frappe.db, "commit", side_effect=AssertionError("frappe.db.commit() inside a test"))
		guard.start()
		self.addCleanup(guard.stop)

	def _restore(self):
		frappe.set_user("Administrator")
		frappe.db.rollback(save_point="ms_test")
