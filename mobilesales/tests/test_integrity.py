"""Phase 7 data integrity: every cancel chain (visit, settlement, trip) puts the ledgers back exactly as they were,
retries and double taps of each submit path change nothing twice, and the patches are idempotent. Flows run as the
real role users (rule 13); cancels as the real supervisor."""

from collections import defaultdict

import frappe
from frappe.utils import flt, now_datetime

from mobilesales.api import mobile as api
from mobilesales.patches.v0_5 import set_visit_off_route
from mobilesales.patches.v0_6 import create_vehicles_from_agent_vans
from mobilesales.patches.v1_0 import add_core_lookup_indexes
from mobilesales.services import settlement
from mobilesales.services import trip as trip_service
from mobilesales.setup.indexes import CORE_INDEXES
from mobilesales.tests.test_settlement import SUPERVISOR, SettlementTestBase
from mobilesales.tests.utils import PREFIX, as_user, make_receipt


class TestIntegrity(SettlementTestBase):
	def snapshot(self) -> dict:
		"""Everything a cancel chain must restore: stock (Bin, stock ledger, batches), the general ledger per
		account, the payment ledger per party / account, and every open invoice's outstanding."""
		qty = defaultdict(float)
		for row in frappe.get_all("Stock Ledger Entry", filters={"is_cancelled": 0}, fields=["item_code", "warehouse", "actual_qty"]):
			qty[(row.item_code, row.warehouse)] += flt(row.actual_qty)
		batches = defaultdict(float)
		for row in frappe.db.sql(
			"""select e.batch_no, b.warehouse, e.qty from `tabSerial and Batch Entry` e
			join `tabSerial and Batch Bundle` b on b.name = e.parent where b.docstatus = 1 and b.is_cancelled = 0""",
			as_dict=True,
		):
			batches[(row.batch_no, row.warehouse)] += flt(row.qty)
		gl = defaultdict(float)
		for row in frappe.get_all("GL Entry", filters={"is_cancelled": 0, "company": self.company}, fields=["account", "debit", "credit"]):
			gl[row.account] += flt(row.debit) - flt(row.credit)
		ple = defaultdict(float)
		for row in frappe.get_all("Payment Ledger Entry", filters={"delinked": 0}, fields=["party", "account", "amount"]):
			ple[(row.party, row.account)] += flt(row.amount)
		bins = {(b.item_code, b.warehouse): flt(b.actual_qty) for b in frappe.get_all("Bin", fields=["item_code", "warehouse", "actual_qty"])}

		def clean(values):
			return {k: flt(v, 6) for k, v in values.items() if flt(v, 6)}

		return {
			"stock": clean(qty),
			"bins": clean(bins),
			"batches": clean(batches),
			"gl": clean(gl),
			"ple": clean(ple),
			"outstanding": clean(
				{s.name: s.outstanding_amount for s in frappe.get_all("Sales Invoice", filters={"docstatus": 1}, fields=["name", "outstanding_amount"])}
			),
		}

	def assertRestored(self, before):
		after = self.snapshot()
		for key in before:
			self.assertEqual(after[key], before[key], key)

	def office_invoice(self, rate=300, update_stock=1):
		si = frappe.get_doc(
			{"doctype": "Sales Invoice", "company": self.company, "customer": self.customer, "update_stock": update_stock,
			 "items": [{"item_code": self.plain_item, "qty": 2, "rate": rate, "warehouse": self.store}]}
		).insert()  # fmt: skip
		si.submit()
		return si

	# cancel chains

	def test_visit_cancel_restores_every_ledger(self):
		"""Sale (batch and plain) + return against an older office invoice (credit note, set-off) + previous
		collection, then the supervisor cancels the visit: stock, batches, GL, payment ledger and outstanding
		are exactly as before the visit."""
		office = self.office_invoice()
		trip = self.run_trip([(self.plain_item, 5), (self.batch_item, 3)], end_day=False)
		before = self.snapshot()
		with as_user(self.agent_a.user):
			priced = api.price_cart(
				trip.name, self.customer, [{"item_code": self.plain_item, "qty": 2}, {"item_code": self.batch_item, "qty": 1}],
				returns_items=[{"item_code": self.plain_item, "qty": 1, "against_invoice": office.name, "return_reason": "Damaged", "condition": "Damaged"}],
				collect_previous=[{"sales_invoice": office.name, "allocated": 100}],
			)  # fmt: skip
			result = api.submit_visit(
				{"client_ref": "int-1", "mobile_trip": trip.name, "customer": self.customer, "outcome": "Sale",
				 "sale_items": [{"item_code": self.plain_item, "qty": 2}, {"item_code": self.batch_item, "qty": 1}],
				 "return_items": [{"item_code": self.plain_item, "qty": 1, "against_invoice": office.name, "return_reason": "Damaged", "condition": "Damaged"}],
				 "collect_previous": [{"sales_invoice": office.name, "allocated": 100}],
				 "collect_amount": priced["due_on_sale"]}
			)  # fmt: skip
		self.assertTrue(result["sales_invoice"] and result["payment_entry"] and result["credit_notes"])
		self.assertNotEqual(self.snapshot(), before)

		with as_user(SUPERVISOR):
			frappe.get_doc("Customer Visit", result["name"]).cancel()
		self.assertRestored(before)
		trip.reload()
		self.assertEqual((trip.visits, trip.invoices, flt(trip.invoiced_amount), flt(trip.collected_amount)), (0, 0, 0, 0))

	def test_settlement_cancel_restores_every_ledger(self):
		"""Return, damage, missing and a cash shortage posted, then cancelled: back to the End Day position."""
		trip = self.run_trip([(self.plain_item, 6), (self.batch_item, 3)], sales=[[(self.plain_item, 1)]], opening_cash_float=200)
		before = self.snapshot()
		draft = self.draft(trip, returned={self.plain_item: 3, self.batch_item: 2}, damaged={self.plain_item: 1})
		doc = self.approve_flow(self.draft(trip, returned={self.plain_item: 3, self.batch_item: 2}, damaged={self.plain_item: 1},
			handed=flt(draft.expected_cash) - 50).name)  # fmt: skip
		self.assertEqual(doc.docstatus, 1)
		self.assertTrue(all(doc.get(f) for f in ("return_entry", "damage_entry", "shortage_entry", "cash_journal", "variance_journal")))

		self.act(doc.name, "Cancel", SUPERVISOR)
		self.assertRestored(before)
		self.assertEqual(frappe.db.get_value("Mobile Trip", trip.name, ["status", "settlement"]), ("Settling", None))

	def test_trip_cancel_restores_every_ledger(self):
		before = self.snapshot()
		trip = frappe.get_doc(
			{"doctype": "Mobile Trip", "agent": self.agent_a.name, "trip_date": frappe.utils.nowdate(), "opening_cash_float": 150,
			 "load_items": [{"item_code": self.plain_item, "qty": 4}, {"item_code": self.batch_item, "qty": 2}]}
		)  # fmt: skip
		with as_user(self.users.store):
			trip.insert()
			trip.submit()
			trip_service.top_up(trip.name, [{"item_code": self.plain_item, "qty": 1}])
		with as_user(SUPERVISOR):
			frappe.get_doc("Mobile Trip", trip.name).cancel()
		self.assertRestored(before)
		self.assertEqual(frappe.db.get_value("Mobile Trip", trip.name, "status"), "Cancelled")

	def test_return_against_invoice_delivered_by_delivery_note_is_refused_clearly(self):
		delivered = self.office_invoice(update_stock=0)  # SO -> DN -> SI: the invoice moved no stock
		trip = self.run_trip([(self.plain_item, 1)], end_day=False)
		line = {"item_code": self.plain_item, "qty": 1, "against_invoice": delivered.name, "return_reason": "Damaged", "condition": "Damaged"}
		with as_user(self.agent_a.user):
			self.assertNotIn(delivered.name, [i.name for i in api.get_customer_invoices(self.customer)])
			picker = api.return_invoice_query("Sales Invoice", "", "name", 0, 50, {"customer": self.customer, "company": self.company})
			self.assertNotIn(delivered.name, [r[0] for r in picker])
			with self.assertRaisesRegex(frappe.ValidationError, "delivered with a Delivery Note"):
				api.price_cart(trip.name, self.customer, [], returns_items=[line])

	def test_item_without_price_is_never_sold_at_zero(self):
		unpriced = self.make_item(f"{PREFIX} Unpriced Item")
		make_receipt(self.company, unpriced, 5, self.store)
		trip = self.run_trip([(unpriced, 2)], end_day=False)
		with as_user(self.agent_a.user):
			with self.assertRaisesRegex(frappe.ValidationError, "has no price in price list"):
				api.price_cart(trip.name, self.customer, [{"item_code": unpriced, "qty": 1}])
			with self.assertRaisesRegex(frappe.ValidationError, "has no price in price list"):
				api.submit_visit({"client_ref": "int-noprice", "mobile_trip": trip.name, "customer": self.customer,
					"outcome": "Sale", "sale_items": [{"item_code": unpriced, "qty": 1}], "collect_amount": 0})  # fmt: skip

	# retries and double taps

	def test_retries_change_nothing_twice(self):
		trip = self.run_trip([(self.plain_item, 4)], end_day=False)
		payload = {"client_ref": "int-retry", "mobile_trip": trip.name, "customer": self.customer, "outcome": "Sale",
			"sale_items": [{"item_code": self.plain_item, "qty": 1}]}  # fmt: skip
		with as_user(self.agent_a.user):
			payload["collect_amount"] = api.price_cart(trip.name, self.customer, payload["sale_items"])["due_on_sale"]
			first = api.submit_visit(payload)
			self.assertEqual(api.start_trip(trip.name), "In Field")  # the start retried after a timeout
			after_first = self.snapshot()
			second = api.submit_visit(payload)
			self.assertEqual((second["name"], second["duplicate"]), (first["name"], True))
			self.assertEqual(self.snapshot(), after_first)

		with as_user(SUPERVISOR):
			frappe.get_doc("Customer Visit", first["name"]).cancel()
		with as_user(self.agent_a.user), self.assertRaisesRegex(frappe.ValidationError, "is cancelled; start a new visit"):
			api.submit_visit(payload)  # the phone retries a visit cancelled meanwhile: never shown as recorded

		with as_user(self.agent_a.user):
			self.assertEqual(api.end_day(trip.name), "Settling")
			self.assertEqual(api.end_day(trip.name), "Settling")
			name = settlement.make_settlement(trip.name)
			self.assertEqual(settlement.make_settlement(trip.name), name)
			saved = api.save_settlement(trip.name, {"stock_lines": [{"item_code": self.plain_item, "returned_qty": 4}]})
			self.assertEqual(api.save_settlement(trip.name, {"stock_lines": [{"item_code": self.plain_item, "returned_qty": 4}]})["name"], saved["name"])
			self.assertFalse(api.submit_settlement_for_verification(name)["duplicate"])
			self.assertTrue(api.submit_settlement_for_verification(name)["duplicate"])
		self.assertEqual(frappe.db.count("Mobile Settlement", {"mobile_trip": trip.name}), 1)
		self.assertEqual(frappe.db.get_value("Mobile Settlement", name, "workflow_state"), "Pending Store")

	# patches

	def test_patches_are_idempotent(self):
		trip = self.run_trip([(self.plain_item, 2)], end_day=False)
		with as_user(self.agent_a.user):
			visit = frappe.get_doc(
				{"doctype": "Customer Visit", "mobile_trip": trip.name, "customer": self.customer, "visit_datetime": now_datetime(),
				 "outcome": "Shop Closed"}
			).insert()  # fmt: skip
		frappe.db.set_value("Customer Visit", visit.name, "off_route", 0)
		for _run in range(2):
			set_visit_off_route.execute()
			self.assertEqual(frappe.db.get_value("Customer Visit", visit.name, "off_route"), 1)  # not on any route

		with self.assertRaisesRegex(frappe.ValidationError, "settle or cancel every Mobile Trip first"):
			create_vehicles_from_agent_vans.execute()  # an open trip: refuses, changes nothing
		frappe.db.delete("Customer Visit", {"name": visit.name})
		frappe.db.set_value("Mobile Trip", trip.name, "status", "Settled")  # test-only: nothing open any more
		legacy = frappe.get_doc({"doctype": "Warehouse", "warehouse_name": f"{PREFIX} Legacy Van", "parent_warehouse": self.van_group,
			"company": self.company}).insert().name  # fmt: skip
		frappe.db.set_value("Mobile Sales Agent", self.agent_b.name, {"van_warehouse": legacy, "default_vehicle": None})
		vehicles = frappe.db.count("Mobile Vehicle")
		create_vehicles_from_agent_vans.execute()
		vehicle = frappe.db.get_value("Mobile Vehicle", {"van_warehouse": legacy}, "name")
		self.assertTrue(vehicle)
		self.assertEqual(frappe.db.get_value("Mobile Sales Agent", self.agent_b.name, "default_vehicle"), vehicle)
		after_first = (frappe.db.count("Mobile Vehicle"), frappe.get_all("Mobile Sales Agent", fields=["name", "default_vehicle"], order_by="name"))
		create_vehicles_from_agent_vans.execute()
		self.assertEqual(after_first[0], vehicles + 1)
		self.assertEqual((frappe.db.count("Mobile Vehicle"), frappe.get_all("Mobile Sales Agent", fields=["name", "default_vehicle"], order_by="name")), after_first)

	def test_core_lookup_indexes(self):
		"""The migrate added the app's two indexes, the lookups use them, and the patch again is a no-op (no DDL:
		an ALTER would commit, which the test base refuses)."""
		for doctype, fieldname, index_name in CORE_INDEXES:
			self.assertTrue(index_name.startswith("ms_"), index_name)  # never clashes with an ERPNext index name
			self.assertTrue(frappe.db.has_index(f"tab{doctype}", index_name), index_name)
			plan = frappe.db.sql(f"explain select name from `tab{doctype}` where `{fieldname}` = 'x'", as_dict=True)
			self.assertEqual(plan[0].get("key"), index_name, plan)
		for _run in range(2):
			add_core_lookup_indexes.execute()
		self.assertEqual(len(frappe.db.sql("show index from `tabSales Invoice Item` where Column_name = 'sales_invoice_item'")), 1)
