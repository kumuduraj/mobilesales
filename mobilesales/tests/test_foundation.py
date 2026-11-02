"""Phase 1 foundation tests: guards leave the standard path alone, block van/cash misuse,
agent setup is idempotent, settings validate.

Own data only ("_MS Test" prefix) under the site's existing company. Mobile Sales Settings is
never saved: a test settings object is patched in, so live cached settings stay untouched.
Everything is rolled back at class end and record counts are compared before/after."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import cint, nowdate
from frappe.utils.nestedset import get_root_of

from mobilesales.overrides import guards, permissions
from mobilesales.services import agent_setup, vehicles
from mobilesales.tests.utils import ROLE_USERS, as_user, make_role_users

PREFIX = "_MS Test"
TEST_USER = "ms.test.agent@example.com"
COUNTED_DOCTYPES = (
	"Warehouse",
	"Account",
	"Mode of Payment",
	"Sales Person",
	"User Permission",
	"User",
	"Mobile Sales Agent",
	"Mobile Vehicle",
	"Item",
	"Customer",
	"Sales Invoice",
	"Delivery Note",
	"Stock Entry",
	"Payment Entry",
	"Stock Ledger Entry",
	"GL Entry",
)


def _counts():
	return {dt: frappe.db.count(dt) for dt in COUNTED_DOCTYPES}


def _company():
	return frappe.defaults.get_global_default("company") or frappe.get_all("Company", pluck="name", limit=1)[0]


def _leaf(doctype):
	return frappe.db.get_value(doctype, {"is_group": 0}, "name")


def _warehouse(name, parent, company, is_group=0):
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


def _account(name, parent, company, is_group=0, account_type=None, account_number=None):
	return (
		frappe.get_doc(
			{
				"doctype": "Account",
				"account_name": name,
				"account_number": account_number,
				"parent_account": parent,
				"company": company,
				"is_group": is_group,
				"account_type": account_type,
			}
		)
		.insert()
		.name
	)


class TestFoundation(IntegrationTestCase):
	SHOW_TRANSACTION_COMMIT_WARNINGS = True

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.counts_before = _counts()
		cls.users = make_role_users()

		cls.company = _company()
		root_wh = frappe.db.get_value(
			"Warehouse", {"company": cls.company, "is_group": 1, "parent_warehouse": ["is", "not set"]}
		)
		cls.store = _warehouse(f"{PREFIX} Store", root_wh, cls.company)
		cls.other_store = _warehouse(f"{PREFIX} Other Store", root_wh, cls.company)
		cls.van_group = _warehouse(f"{PREFIX} Vans", root_wh, cls.company, is_group=1)

		default_cash = frappe.get_cached_value("Company", cls.company, "default_cash_account")
		cash_root = frappe.db.get_value("Account", default_cash, "parent_account")
		cls.cash_group = _account(f"{PREFIX} Cash In Hand", cash_root, cls.company, 1, "Cash")
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

		cls.settings = frappe.get_doc("Mobile Sales Settings")
		cls.settings.update(
			{
				"company": cls.company,
				"source_warehouse": cls.store,
				"return_warehouse": cls.store,
				"van_warehouse_group": cls.van_group,
				"agent_cash_parent_account": cls.cash_group,
				"sales_person_parent": cls.sales_team,
			}
		)
		cls._patches = [
			patch("mobilesales.services.settings.get_settings", return_value=cls.settings),
			patch("mobilesales.overrides.guards.get_guard_context", side_effect=guards.build_guard_context),
		]
		for p in cls._patches:
			p.start()

		cls.item = (
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": f"{PREFIX} Item",
					"item_name": f"{PREFIX} Item",
					"item_group": _leaf("Item Group"),
					"stock_uom": "Nos",
					"is_stock_item": 1,
					"has_batch_no": 0,
				}
			)
			.insert()
			.name
		)
		cls.customer = (
			frappe.get_doc(
				{
					"doctype": "Customer",
					"customer_name": f"{PREFIX} Customer",
					"customer_group": _leaf("Customer Group"),
					"territory": _leaf("Territory"),
				}
			)
			.insert()
			.name
		)
		receipt = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"stock_entry_type": "Material Receipt",
				"company": cls.company,
				"items": [{"item_code": cls.item, "qty": 20, "t_warehouse": cls.store, "basic_rate": 50}],
			}
		)
		receipt.insert()
		receipt.submit()

		frappe.get_doc(
			{
				"doctype": "User",
				"email": TEST_USER,
				"first_name": f"{PREFIX} Agent",
				"send_welcome_email": 0,
			}
		).insert()
		cls.agent = (
			frappe.get_doc({"doctype": "Mobile Sales Agent", "user": TEST_USER, "agent_name": f"{PREFIX} Agent"})
			.insert()
			.name
		)
		cls.vehicle = frappe.get_doc({"doctype": "Mobile Vehicle", "vehicle_no": f"{PREFIX} VAN"}).insert().name
		with as_user(cls.users.supervisor):
			cls.setup_result = agent_setup.setup_agent(cls.agent)
			cls.van_warehouse = vehicles.setup_vehicle(cls.vehicle)

	@classmethod
	def tearDownClass(cls):
		for p in cls._patches:
			p.stop()
		frappe.db.rollback()
		for user in (TEST_USER, *(email for email, _roles in ROLE_USERS.values())):
			frappe.clear_cache(user=user)
		counts_after = _counts()
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
		# Nothing inside a test may commit: a commit would write test data to the live site.
		guard = patch.object(frappe.db, "commit", side_effect=AssertionError("frappe.db.commit() inside a test"))
		guard.start()
		self.addCleanup(guard.stop)

	# helpers

	def _sales_invoice(self, warehouse):
		return frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"company": self.company,
				"customer": self.customer,
				"posting_date": nowdate(),
				"update_stock": 1,
				"items": [{"item_code": self.item, "qty": 1, "rate": 100, "warehouse": warehouse}],
			}
		)

	def _transfer(self, target):
		return frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"stock_entry_type": "Material Transfer",
				"company": self.company,
				"items": [
					{
						"item_code": self.item,
						"qty": 1,
						"s_warehouse": self.store,
						"t_warehouse": target,
					}
				],
			}
		)

	@property
	def van(self):
		return self.van_warehouse

	# 1
	def test_standard_sales_invoice_unaffected(self):
		with as_user(self.users.office):
			si = self._sales_invoice(self.store)
			si.insert()
			si.submit()
			self.assertEqual(si.docstatus, 1)
			self.assertFalse(si.get("mobile_trip"))
			self.assertFalse(cint(si.get("is_mobile_sale")))
			si.cancel()
		self.assertEqual(si.docstatus, 2)

	# 2
	def test_sales_invoice_on_van_without_trip_blocked(self):
		with as_user(self.users.office), self.assertRaisesRegex(frappe.ValidationError, "Van warehouse"):
			self._sales_invoice(self.van).insert()

	def test_delivery_note_on_van_blocked(self):
		dn = frappe.get_doc(
			{
				"doctype": "Delivery Note",
				"company": self.company,
				"customer": self.customer,
				"items": [{"item_code": self.item, "qty": 1, "rate": 100, "warehouse": self.van}],
			}
		)
		with as_user(self.users.office), self.assertRaisesRegex(frappe.ValidationError, "Van warehouse"):
			dn.insert()

	# 3
	def test_stock_entry_into_van_without_trip_blocked(self):
		with as_user(self.users.office), self.assertRaisesRegex(frappe.ValidationError, "Van warehouse"):
			self._transfer(self.van).insert()

	# 4
	def test_stock_entry_not_touching_vans_passes(self):
		with as_user(self.users.office):
			se = self._transfer(self.other_store)
			se.insert()
			se.submit()
		self.assertEqual(se.docstatus, 1)

	# 5
	def test_payment_entry_to_agent_cash_without_trip_blocked(self):
		pe = frappe.get_doc(
			{
				"doctype": "Payment Entry",
				"payment_type": "Receive",
				"company": self.company,
				"posting_date": nowdate(),
				"party_type": "Customer",
				"party": self.customer,
				"paid_from": frappe.get_cached_value("Company", self.company, "default_receivable_account"),
				"paid_to": self.setup_result["cash_account"],
				"paid_amount": 100,
				"received_amount": 100,
				"source_exchange_rate": 1,
				"target_exchange_rate": 1,
			}
		)
		with as_user(self.users.office), self.assertRaisesRegex(frappe.ValidationError, "Agent cash account"):
			pe.insert()

	# 6
	def test_setup_agent_is_idempotent(self):
		first = self.setup_result
		self.assertNotIn("van_warehouse", first)  # the van belongs to the vehicle (v0.6.0)
		self.assertEqual(frappe.db.get_value("Account", first["cash_account"], "account_type"), "Cash")
		self.assertEqual(
			frappe.db.get_value(
				"Mode of Payment Account",
				{"parent": first["mode_of_payment"], "company": self.company},
				"default_account",
			),
			first["cash_account"],
		)
		self.assertEqual(
			frappe.db.get_value("Sales Person", first["sales_person"], "parent_sales_person"), self.sales_team
		)
		self.assertIn("Mobile Sales Agent", frappe.get_roles(TEST_USER))

		counts = _counts()
		with as_user(self.users.supervisor):
			second = agent_setup.setup_agent(self.agent)
		self.assertEqual(first, second)
		self.assertEqual(counts, _counts())
		self.assertEqual(
			frappe.db.count(
				"User Permission", {"user": TEST_USER, "allow": "Mobile Sales Agent", "for_value": self.agent}
			),
			len(agent_setup.SCOPED_DOCTYPES),
		)

	def test_setup_vehicle_creates_van_once(self):
		self.assertTrue(frappe.db.exists("Warehouse", {"name": self.van, "parent_warehouse": self.van_group, "is_group": 0}))
		self.assertEqual(self.van, f"{PREFIX} VAN Van - {frappe.get_cached_value('Company', self.company, 'abbr')}")
		counts = _counts()
		with as_user(self.users.supervisor):
			self.assertEqual(vehicles.setup_vehicle(self.vehicle), self.van)
		self.assertEqual(counts, _counts())
		for user in (self.users.office, self.users.store, TEST_USER):
			with as_user(user), self.assertRaises(frappe.PermissionError):
				vehicles.setup_vehicle(self.vehicle)
		other = frappe.get_doc({"doctype": "Mobile Vehicle", "vehicle_no": f"{PREFIX} VAN 2", "van_warehouse": self.van})
		with self.assertRaisesRegex(frappe.ValidationError, "already belongs to vehicle"):
			other.insert()

	def test_vehicle_legacy_patch(self):
		from mobilesales.patches.v0_6 import create_vehicles_from_agent_vans as legacy

		legacy_van = _warehouse(f"{PREFIX} Legacy Van", self.van_group, self.company)
		frappe.db.set_value("Mobile Sales Agent", self.agent, {"van_warehouse": legacy_van, "default_vehicle": None})

		def old_trip(name, status):
			trip = frappe.new_doc("Mobile Trip")  # trips from before v0.6.0: no vehicle
			trip.update({"name": name, "agent": self.agent, "trip_date": nowdate(), "company": self.company, "status": status,
				"docstatus": 1, "van_warehouse": legacy_van, "source_warehouse": self.store})  # fmt: skip
			trip.db_insert()
			return name

		settled = old_trip(f"{PREFIX} OLD-1", "Settled")
		open_trip = old_trip(f"{PREFIX} OLD-2", "In Field")
		with self.assertRaisesRegex(frappe.ValidationError, f"settle or cancel every Mobile Trip first. Open: .*{open_trip} \\(In Field\\)"):
			legacy.execute()
		self.assertFalse(frappe.db.exists("Mobile Vehicle", {"van_warehouse": legacy_van}))

		frappe.db.set_value("Mobile Trip", open_trip, "status", "Settled")
		expected_no = legacy.next_vehicle_no()
		legacy.execute()
		vehicle = frappe.get_doc("Mobile Vehicle", {"van_warehouse": legacy_van})
		self.assertEqual((vehicle.name, vehicle.is_active), (expected_no, 1))
		self.assertRegex(vehicle.name, r"^VAN-\d{2}$")
		agent = frappe.db.get_value("Mobile Sales Agent", self.agent, ["van_warehouse", "default_vehicle"], as_dict=True)
		self.assertEqual((agent.van_warehouse, agent.default_vehicle), (legacy_van, vehicle.name))  # legacy field kept
		self.assertEqual({frappe.db.get_value("Mobile Trip", t, "vehicle") for t in (settled, open_trip)}, {vehicle.name})
		self.assertIn(legacy_van, guards.build_guard_context()["vans"])  # still a guarded van

		counts = (frappe.db.count("Mobile Vehicle"), _counts())
		legacy.execute()  # idempotent
		self.assertEqual(counts, (frappe.db.count("Mobile Vehicle"), _counts()))

		# an inactive (old) agent's van becomes an inactive vehicle
		frappe.db.delete("Mobile Vehicle", vehicle.name)
		frappe.db.set_value("Mobile Sales Agent", self.agent, {"is_active": 0, "default_vehicle": None})
		legacy.execute()
		self.assertEqual(frappe.db.get_value("Mobile Vehicle", {"van_warehouse": legacy_van}, "is_active"), 0)

	def test_setup_agent_needs_supervisor(self):
		for user in (self.users.office, self.users.store, TEST_USER):
			with as_user(user), self.assertRaises(frappe.PermissionError):
				agent_setup.setup_agent(self.agent)

	def test_cash_account_number(self):
		# The test parent has no numbered children, so the agent ledger is unnumbered.
		self.assertIsNone(frappe.db.get_value("Account", self.setup_result["cash_account"], "account_number"))

		numbers = frappe.get_all("Account", filters={"company": self.company}, pluck="account_number")
		base = max([cint(n) for n in numbers if n and str(n).isdigit()] or [0]) + 100
		_account(f"{PREFIX} Numbered Cash", self.cash_group, self.company, 0, "Cash", str(base))
		self.assertEqual(agent_setup.next_account_number(self.cash_group, self.company), str(base + 1))

	# 7
	def test_settings_reject_non_group_van_warehouse_group(self):
		settings = frappe.get_doc("Mobile Sales Settings")
		settings.update({"company": self.company, "van_warehouse_group": self.store})
		with self.assertRaisesRegex(frappe.ValidationError, "must be a group warehouse"):
			settings.validate()

	def test_settings_accept_valid_values(self):
		self.settings.validate()

	def _isolated(self):
		frappe.db.savepoint("ms_settings_test")
		self.addCleanup(frappe.db.rollback, save_point="ms_settings_test")

	def _settings_copy(self, **overrides):
		settings = frappe.get_doc(self.settings.as_dict())
		settings.update(overrides)
		return settings

	def test_settings_reject_root_van_warehouse_group(self):
		root = frappe.db.get_value("Warehouse", self.van_group, "parent_warehouse")
		with self.assertRaisesRegex(frappe.ValidationError, "is a root warehouse"):
			self._settings_copy(van_warehouse_group=root).validate()

	def test_settings_reject_store_inside_van_group(self):
		self._isolated()
		inner = _warehouse(f"{PREFIX} Inner Store", self.van_group, self.company)
		for fieldname in ("source_warehouse", "return_warehouse", "damage_warehouse"):
			with self.assertRaisesRegex(frappe.ValidationError, "must not be inside Van Warehouse Group"):
				self._settings_copy(**{fieldname: inner}).validate()

	def test_settings_reject_stocked_non_agent_warehouse_in_van_group(self):
		self._isolated()
		stray = _warehouse(f"{PREFIX} Stray", self.van_group, self.company)
		receipt = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"stock_entry_type": "Material Receipt",
				"company": self.company,
				"items": [{"item_code": self.item, "qty": 1, "t_warehouse": stray, "basic_rate": 50}],
			}
		)
		# Guards would (rightly) block a receipt into the van group; bypass them to plant the stock.
		with patch("mobilesales.overrides.guards.get_guard_context", return_value=guards.EMPTY_CONTEXT):
			receipt.insert()
			receipt.submit()
		with self.assertRaisesRegex(frappe.ValidationError, "not agent vans"):
			self._settings_copy().validate()

	def test_agent_sees_only_own_agent_record(self):
		agent_doc = frappe.get_doc("Mobile Sales Agent", self.agent)
		self.assertTrue(permissions.is_restricted_agent(TEST_USER))
		self.assertTrue(permissions.agent_has_permission(agent_doc, "read", TEST_USER))
		self.assertFalse(permissions.agent_has_permission(frappe._dict(user="someone@example.com"), "read", TEST_USER))
		self.assertIn(frappe.db.escape(TEST_USER), permissions.agent_query_conditions(TEST_USER))
		self.assertEqual(permissions.agent_query_conditions("Administrator"), "")

	def test_settings_customer_defaults_must_be_leaves(self):
		group = frappe.db.get_value("Customer Group", {"is_group": 1})
		settings = frappe.get_doc(self.settings.as_dict())
		settings.default_customer_group = group
		with self.assertRaisesRegex(frappe.ValidationError, "must not be a group"):
			settings.validate()
