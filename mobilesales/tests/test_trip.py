"""Phase 2: Mobile Trip, stock issue, status actions, guards on mobile vouchers, trip permissions."""

import frappe
from frappe.utils import flt, nowdate

from erpnext.stock.doctype.batch.batch import get_batch_qty

from mobilesales.api import mobile as mobile_api
from mobilesales.overrides import guards
from mobilesales.services import trip as trip_service
from mobilesales.tests.utils import MobileSalesTestCase


class TestMobileTrip(MobileSalesTestCase):
	# helpers

	def make_trip(self, agent=None, items=None, opening_cash_float=0, submit=True):
		agent = agent or self.agent_a
		trip = frappe.get_doc(
			{
				"doctype": "Mobile Trip",
				"agent": agent.name,
				"trip_date": nowdate(),
				"opening_cash_float": opening_cash_float,
				"load_items": items or [{"item_code": self.plain_item, "qty": 3}],
			}
		)
		trip.insert()
		if submit:
			trip.submit()
			trip.reload()
		return trip

	def van_qty(self, agent, item_code):
		return flt(frappe.db.get_value("Bin", {"warehouse": agent.van_warehouse, "item_code": item_code}, "actual_qty"))

	def as_user(self, user):
		frappe.set_user(user)

	# 1
	def test_submit_moves_load_to_van(self):
		trip = self.make_trip(items=[{"item_code": self.plain_item, "qty": 3}, {"item_code": self.batch_item, "qty": 2}])
		self.assertEqual(trip.status, "Loaded")
		self.assertEqual(self.van_qty(self.agent_a, self.plain_item), 3)
		self.assertEqual(self.van_qty(self.agent_a, self.batch_item), 2)
		self.assertEqual([r.purpose for r in trip.stock_entries], ["Issue"])

		se = frappe.get_doc("Stock Entry", trip.stock_entries[0].stock_entry)
		self.assertEqual((se.docstatus, se.mobile_trip, se.mobile_purpose), (1, trip.name, "Issue"))
		self.assertEqual({r.t_warehouse for r in se.items}, {self.agent_a.van_warehouse})
		load = {r.item_code: r for r in trip.load_items}
		self.assertEqual(load[self.plain_item].stock_qty, 3)
		self.assertEqual(load[self.plain_item].available_at_source, 50)

	# 2
	def test_batch_issue_picks_fifo(self):
		self.make_trip(items=[{"item_code": self.batch_item, "qty": 7}])
		batches = {
			b.get("batch_no"): b.get("qty")
			for b in get_batch_qty(warehouse=self.agent_a.van_warehouse, item_code=self.batch_item)
		}
		self.assertEqual(batches, {self.batch_a: 5, self.batch_b: 2})

	# 3
	def test_insufficient_source_stock_rejected(self):
		with self.assertRaisesRegex(frappe.ValidationError, "Insufficient stock"):
			self.make_trip(items=[{"item_code": self.plain_item, "qty": 1000}], submit=False)

	def test_load_rejects_zero_qty(self):
		with self.assertRaisesRegex(frappe.ValidationError, "greater than 0"):
			self.make_trip(items=[{"item_code": self.plain_item, "qty": 0}], submit=False)

	# 4
	def test_second_open_trip_rejected(self):
		self.make_trip(submit=False)
		with self.assertRaisesRegex(frappe.ValidationError, "already has an open trip"):
			self.make_trip(submit=False)

	def test_inactive_agent_rejected(self):
		frappe.db.set_value("Mobile Sales Agent", self.agent_a.name, "is_active", 0)
		with self.assertRaisesRegex(frappe.ValidationError, "is not active"):
			self.make_trip(submit=False)

	# 5
	def test_submit_with_stock_in_van_rejected(self):
		first = self.make_trip()
		first.db_set("status", "Settled")  # simulate a settled trip that left stock behind
		with self.assertRaisesRegex(frappe.ValidationError, "Previous trip not settled"):
			self.make_trip()

	# 6
	def test_opening_float_journal(self):
		trip = self.make_trip(opening_cash_float=500)
		je = frappe.get_doc("Journal Entry", trip.opening_float_journal)
		self.assertEqual((je.docstatus, je.mobile_trip), (1, trip.name))
		lines = {(r.account, r.debit, r.credit) for r in je.accounts}
		self.assertEqual(lines, {(self.agent_a.cash_account, 500, 0), (self.main_cash, 0, 500)})

	# 7
	def test_status_actions(self):
		trip = self.make_trip()
		self.as_user(self.agent_b.user)
		with self.assertRaises(frappe.PermissionError):
			trip_service.start_trip(trip.name)

		self.as_user(self.agent_a.user)
		with self.assertRaisesRegex(frappe.ValidationError, "needs status"):
			trip_service.end_day(trip.name)
		self.assertEqual(trip_service.start_trip(trip.name), "In Field")
		with self.assertRaisesRegex(frappe.ValidationError, "needs status"):
			trip_service.start_trip(trip.name)
		self.assertEqual(trip_service.end_day(trip.name), "Settling")

	# 8
	def test_top_up(self):
		trip = self.make_trip()
		se_name = trip_service.top_up(trip.name, [{"item_code": self.plain_item, "qty": 2}])
		trip.reload()
		self.assertEqual([r.purpose for r in trip.stock_entries], ["Issue", "Top-up"])
		self.assertEqual(frappe.db.get_value("Stock Entry", se_name, "mobile_purpose"), "Top-up")
		self.assertEqual(self.van_qty(self.agent_a, self.plain_item), 5)

		self.as_user(self.agent_a.user)
		with self.assertRaises(frappe.PermissionError):
			trip_service.top_up(trip.name, [{"item_code": self.plain_item, "qty": 1}])

		self.as_user("Administrator")
		trip_service.start_trip(trip.name)
		trip_service.end_day(trip.name)
		with self.assertRaisesRegex(frappe.ValidationError, "needs status"):
			trip_service.top_up(trip.name, [{"item_code": self.plain_item, "qty": 1}])

	# 9
	def test_cancel_from_loaded_reverses_everything(self):
		trip = self.make_trip(opening_cash_float=300)
		se_name = trip.stock_entries[0].stock_entry
		trip.cancel()
		trip.reload()
		self.assertEqual(trip.status, "Cancelled")
		self.assertEqual(frappe.db.get_value("Stock Entry", se_name, "docstatus"), 2)
		self.assertEqual(frappe.db.get_value("Journal Entry", trip.opening_float_journal, "docstatus"), 2)
		self.assertEqual(self.van_qty(self.agent_a, self.plain_item), 0)

		in_field = self.make_trip()
		trip_service.start_trip(in_field.name)
		in_field.reload()
		with self.assertRaisesRegex(frappe.ValidationError, "Only a Loaded trip"):
			in_field.cancel()

	# 10
	def test_manual_mobile_stock_entry_rejected(self):
		trip = self.make_trip()
		se = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"stock_entry_type": "Material Transfer",
				"company": self.company,
				"mobile_trip": trip.name,
				"mobile_purpose": "Top-up",
				"items": [
					{"item_code": self.plain_item, "qty": 1, "s_warehouse": self.store, "t_warehouse": trip.van_warehouse}
				],
			}
		)
		with self.assertRaisesRegex(frappe.ValidationError, "can only be created by the Mobile Sales app"):
			se.insert()

	def test_internal_stock_entry_must_use_trip_van(self):
		trip = self.make_trip()
		se = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"stock_entry_type": "Material Transfer",
				"company": self.company,
				"mobile_trip": trip.name,
				"mobile_purpose": "Top-up",
				"items": [
					{"item_code": self.plain_item, "qty": 1, "s_warehouse": self.store, "t_warehouse": self.agent_b.van_warehouse}
				],
			}
		)
		se.flags[guards.INTERNAL_FLAG] = True
		with self.assertRaisesRegex(frappe.ValidationError, "may only use van warehouse"):
			se.insert()

	def test_mobile_sales_invoice_rules(self):
		trip = self.make_trip()

		def invoice(warehouse):
			return frappe.get_doc(
				{
					"doctype": "Sales Invoice",
					"company": self.company,
					"customer": self.customer,
					"update_stock": 1,
					"mobile_trip": trip.name,
					"items": [{"item_code": self.plain_item, "qty": 1, "rate": 100, "warehouse": warehouse}],
				}
			)

		with self.assertRaisesRegex(frappe.ValidationError, "needs In Field"):
			invoice(trip.van_warehouse).insert()

		trip_service.start_trip(trip.name)
		with self.assertRaisesRegex(frappe.ValidationError, "may only use van warehouse"):
			invoice(self.store).insert()

		si = invoice(trip.van_warehouse)
		si.insert()
		si.submit()
		self.assertEqual(self.van_qty(self.agent_a, self.plain_item), 2)

		frappe.db.set_value("Mobile Trip", trip.name, "status", "Settled")
		with self.assertRaisesRegex(frappe.ValidationError, "is Settled"):
			si.cancel()

	def test_mobile_journal_and_payment_rules(self):
		trip = self.make_trip()
		je = frappe.get_doc(
			{
				"doctype": "Journal Entry",
				"company": self.company,
				"posting_date": nowdate(),
				"mobile_trip": trip.name,
				"accounts": [
					{"account": self.agent_a.cash_account, "debit_in_account_currency": 10},
					{"account": self.main_cash, "credit_in_account_currency": 10},
				],
			}
		)
		with self.assertRaisesRegex(frappe.ValidationError, "can only be created by the Mobile Sales app"):
			je.insert()

		frappe.db.set_value("Mobile Trip", trip.name, "status", "Settled")
		pe = frappe.get_doc(
			{
				"doctype": "Payment Entry",
				"payment_type": "Receive",
				"company": self.company,
				"posting_date": nowdate(),
				"party_type": "Customer",
				"party": self.customer,
				"paid_from": frappe.get_cached_value("Company", self.company, "default_receivable_account"),
				"paid_to": self.agent_a.cash_account,
				"paid_amount": 10,
				"received_amount": 10,
				"source_exchange_rate": 1,
				"target_exchange_rate": 1,
				"mobile_trip": trip.name,
			}
		)
		with self.assertRaisesRegex(frappe.ValidationError, "is Settled"):
			pe.insert()

	# 11
	def test_agent_cannot_read_other_agents_trip(self):
		trip_a = self.make_trip(agent=self.agent_a)
		trip_b = self.make_trip(agent=self.agent_b)

		self.as_user(self.agent_a.user)
		self.assertEqual(frappe.get_list("Mobile Trip", pluck="name"), [trip_a.name])
		self.assertTrue(frappe.has_permission("Mobile Trip", "read", doc=trip_a.name))
		self.assertFalse(frappe.has_permission("Mobile Trip", "read", doc=trip_b.name))
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc("Mobile Trip", trip_b.name).check_permission("read")
		with self.assertRaises(frappe.PermissionError):
			mobile_api.get_van_stock(trip_b.name)

		own = mobile_api.get_van_stock(trip_a.name)
		self.assertEqual({r.item_code: r.actual_qty for r in own}, {self.plain_item: 3})
		self.assertFalse(frappe.has_permission("Mobile Trip", "create"))

	def test_get_context_and_van_stock_batches(self):
		trip = self.make_trip(items=[{"item_code": self.batch_item, "qty": 6}])
		self.as_user(self.agent_a.user)
		context = mobile_api.get_context()
		self.assertEqual(context["agent"].name, self.agent_a.name)
		self.assertEqual((context["trip"].name, context["trip"].status), (trip.name, "Loaded"))
		self.assertEqual(context["settings"]["company"], self.company)

		(row,) = mobile_api.get_van_stock(trip.name)
		self.assertEqual(row.actual_qty, 6)
		self.assertEqual({b["batch_no"]: b["qty"] for b in row.batches}, {self.batch_a: 5, self.batch_b: 1})
