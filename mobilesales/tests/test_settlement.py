"""Phase 4: Mobile Settlement reconciliation, workflow, per-state edit rules, postings, cancel."""

from unittest.mock import patch

import frappe
from frappe.model.workflow import apply_workflow
from frappe.utils import add_years, flt, now_datetime, nowdate

from erpnext.stock.doctype.batch.batch import get_batch_qty

from mobilesales.api import mobile as mobile_api
from mobilesales.overrides import guards
from mobilesales.services import invoicing, reconciliation, settlement
from mobilesales.services import trip as trip_service
from mobilesales.tests.utils import PREFIX, ROLE_USERS, MobileSalesTestCase, as_user, make_receipt, make_warehouse

STORE_KEEPER = ROLE_USERS["store"][0]
CASHIER = ROLE_USERS["cashier"][0]
SUPERVISOR = ROLE_USERS["supervisor"][0]


class TestMobileSettlement(MobileSalesTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()  # creates the store keeper / cashier / supervisor / office users

		root_wh = frappe.db.get_value("Warehouse", cls.store, "parent_warehouse")
		cls.damage_wh = make_warehouse(f"{PREFIX} Damaged", root_wh, cls.company)
		cls.cash_item = cls.make_item(f"{PREFIX} Cash Item")
		frappe.get_doc({"doctype": "Item Price", "item_code": cls.cash_item, "price_list": cls.price_list, "price_list_rate": 485}).insert()
		make_receipt(cls.company, cls.plain_item, 200, cls.store)
		make_receipt(cls.company, cls.cash_item, 100, cls.store, rate=300)

		stock_adjustment = frappe.get_cached_value("Company", cls.company, "stock_adjustment_account")
		expense_group = frappe.db.get_value("Account", stock_adjustment, "parent_account")
		cls.cash_shortage = cls.make_account(f"{PREFIX} Cash Shortage", expense_group)
		payable_group = frappe.db.get_value(
			"Account", frappe.get_cached_value("Company", cls.company, "default_payable_account"), "parent_account"
		)
		cls.recovery_account = cls.make_account(f"{PREFIX} Employee Recovery", payable_group, "Payable")
		cls.settings.update(
			{
				"damage_warehouse": cls.damage_wh,
				"stock_shortage_account": stock_adjustment,
				"cash_shortage_account": cls.cash_shortage,
				"employee_recovery_account": cls.recovery_account,
				"shortage_tolerance_value": 100000,
				"recover_shortage_from_agent": 0,
				"allow_credit_sales": 0,
			}
		)

	@classmethod
	def make_account(cls, name, parent, account_type=None):
		return frappe.get_doc(
			{"doctype": "Account", "account_name": name, "parent_account": parent, "company": cls.company, "account_type": account_type}
		).insert().name

	# helpers

	def set_setting(self, fieldname, value):
		old = self.settings.get(fieldname)
		self.settings.set(fieldname, value)
		self.addCleanup(self.settings.set, fieldname, old)

	def run_trip(self, load, sales=(), opening_cash_float=0, agent=None, end_day=True):
		agent = agent or self.agent_a
		trip = frappe.get_doc(
			{
				"doctype": "Mobile Trip",
				"agent": agent.name,
				"trip_date": nowdate(),
				"opening_cash_float": opening_cash_float,
				"load_items": [{"item_code": item, "qty": qty} for item, qty in load],
			}
		)
		with as_user(self.users.store):
			trip.insert()
			trip.submit()
		with as_user(agent.user):
			trip_service.start_trip(trip.name)
			for items in sales:
				self._sell(trip.name, items)
			if end_day:
				trip_service.end_day(trip.name)
		return frappe.get_doc("Mobile Trip", trip.name)

	def sell(self, trip_name, items):
		agent_user = frappe.db.get_value("Mobile Sales Agent", frappe.db.get_value("Mobile Trip", trip_name, "agent"), "user")
		with as_user(agent_user):
			return self._sell(trip_name, items)

	def _sell(self, trip_name, items):
		visit = frappe.get_doc(
			{
				"doctype": "Customer Visit",
				"mobile_trip": trip_name,
				"customer": self.customer,
				"visit_datetime": now_datetime(),
				"outcome": "Sale",
				"sale_items": [{"item_code": item, "qty": qty} for item, qty in items],
			}
		)
		visit.collect_amount = invoicing.payable_amount(invoicing.build_invoice(visit))
		visit.insert()
		visit.submit()
		return visit

	def draft(self, trip, returned=None, damaged=None, damaged_batch=None, handed=None, agent=None):
		frappe.set_user((agent or self.agent_a).user)
		name = settlement.make_settlement(trip.name)
		doc = frappe.get_doc("Mobile Settlement", name)
		for row in doc.stock_lines:
			row.returned_qty = (returned or {}).get(row.item_code, 0)
			row.damaged_qty = (damaged or {}).get(row.item_code, 0)
			row.damaged_batch_no = (damaged_batch or {}).get(row.item_code)
		doc.cash_handed_over = doc.expected_cash if handed is None else handed
		doc.save()
		frappe.set_user("Administrator")
		return doc

	def act(self, name, action, user):
		frappe.set_user(user)
		try:
			apply_workflow(frappe.get_doc("Mobile Settlement", name), action)
		finally:
			frappe.set_user("Administrator")
		return frappe.get_doc("Mobile Settlement", name)

	def approve_flow(self, name):
		self.act(name, "Submit for Verification", self.agent_a.user)
		self.act(name, "Verify Stock", STORE_KEEPER)
		return self.act(name, "Verify Cash", CASHIER)

	def van_qty(self, item_code, agent=None):
		van = (agent or self.agent_a).van_warehouse
		return flt(frappe.db.get_value("Bin", {"warehouse": van, "item_code": item_code}, "actual_qty"))

	def se_rows(self, name):
		return sorted((r.item_code, flt(r.qty), r.batch_no or None) for r in frappe.get_doc("Stock Entry", name).items)

	def je_lines(self, name):
		return {(r.account, flt(r.debit), flt(r.credit), r.party or None) for r in frappe.get_doc("Journal Entry", name).accounts}

	# 1  SPEC §8.3
	def test_issued_sold_returned_damaged_missing(self):
		trip = self.run_trip(
			[(self.plain_item, 100), (self.batch_item, 7)],
			sales=[[(self.plain_item, 70), (self.batch_item, 3)]],  # batch sale takes A first: van A 2, B 2
		)
		doc = self.draft(trip, returned={self.plain_item: 25, self.batch_item: 4}, damaged={self.plain_item: 3})
		line = next(r for r in doc.stock_lines if r.item_code == self.plain_item)
		self.assertEqual((line.issued_qty, line.sold_qty, line.expected_balance, line.missing_qty), (100, 70, 30, 2))
		self.assertEqual(doc.stock_variance_value, 2 * line.valuation_rate)

		doc = self.approve_flow(doc.name)
		self.assertEqual((doc.docstatus, doc.workflow_state), (1, "Approved"))
		self.assertEqual(self.se_rows(doc.return_entry), sorted([(self.plain_item, 25, None), (self.batch_item, 2, self.batch_a), (self.batch_item, 2, self.batch_b)]))
		self.assertEqual(self.se_rows(doc.damage_entry), [(self.plain_item, 3, None)])
		self.assertEqual(self.se_rows(doc.shortage_entry), [(self.plain_item, 2, None)])
		self.assertEqual(
			{frappe.db.get_value("Stock Entry", n, "mobile_purpose") for n in (doc.return_entry, doc.damage_entry, doc.shortage_entry)},
			{"Return", "Damage", "Shortage"},
		)
		self.assertEqual(self.van_qty(self.plain_item), 0)
		self.assertEqual(self.van_qty(self.batch_item), 0)
		self.assertFalse([b for b in get_batch_qty(warehouse=self.agent_a.van_warehouse, item_code=self.batch_item) if flt(b.get("qty"))])
		trip.reload()
		self.assertEqual((trip.status, trip.settlement), ("Settled", doc.name))
		self.assertEqual([r.purpose for r in trip.stock_entries], ["Issue", "Return", "Damage", "Shortage"])
		self.assertIn(doc.name, frappe.get_print("Mobile Settlement", doc.name, print_format="Mobile Settlement Sheet"))

	# 2
	def test_cash_shortage_posts_variance_journal(self):
		trip = self.run_trip([(self.cash_item, 100)], sales=[[(self.cash_item, 100)]], opening_cash_float=2000)
		doc = self.draft(trip, handed=50000)
		self.assertEqual((doc.opening_cash_float, doc.expected_cash, doc.cash_variance), (2000, 50500, -500))
		self.assertEqual((doc.collected_current, doc.cash_sales_amount), (48500, 48500))
		doc = self.approve_flow(doc.name)
		self.assertEqual(self.je_lines(doc.cash_journal), {(self.main_cash, 50000, 0, None), (self.agent_a.cash_account, 0, 50000, None)})
		self.assertEqual(self.je_lines(doc.variance_journal), {(self.cash_shortage, 500, 0, None), (self.agent_a.cash_account, 0, 500, None)})
		self.assertEqual(reconciliation.get_agent_cash_balance(self.agent_a.cash_account), 0)

	# 3
	def test_cash_excess_posts_reversed_journal(self):
		trip = self.run_trip([(self.plain_item, 1)], sales=[[(self.plain_item, 1)]])
		doc = self.approve_flow(self.draft(trip, handed=150).name)
		self.assertEqual(doc.cash_variance, 50)
		self.assertEqual(self.je_lines(doc.variance_journal), {(self.agent_a.cash_account, 50, 0, None), (self.cash_shortage, 0, 50, None)})
		self.assertEqual(reconciliation.get_agent_cash_balance(self.agent_a.cash_account), 0)

	# 4
	def test_over_tolerance_needs_supervisor(self):
		self.set_setting("shortage_tolerance_value", 0)
		trip = self.run_trip([(self.plain_item, 1)], sales=[[(self.plain_item, 1)]])
		doc = self.draft(trip, handed=90)
		self.assertTrue(doc.needs_approval)
		doc = self.approve_flow(doc.name)
		self.assertEqual((doc.docstatus, doc.workflow_state), (0, "Pending Approval"))

		frappe.set_user(CASHIER)
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc("Mobile Settlement", doc.name).submit()
		frappe.set_user("Administrator")
		with self.assertRaises(frappe.ValidationError):
			self.act(doc.name, "Approve", CASHIER)

		doc = self.act(doc.name, "Approve", SUPERVISOR)
		self.assertEqual((doc.docstatus, doc.workflow_state), (1, "Approved"))

	# 5
	def test_within_tolerance_submits_on_verify_cash(self):
		self.set_setting("shortage_tolerance_value", 100)
		trip = self.run_trip([(self.plain_item, 1)], sales=[[(self.plain_item, 1)]])
		doc = self.approve_flow(self.draft(trip, handed=90).name)
		self.assertFalse(doc.needs_approval)
		self.assertEqual((doc.docstatus, doc.workflow_state, doc.verified_by_store, doc.verified_by_cashier), (1, "Approved", STORE_KEEPER, CASHIER))

	# 6
	def test_field_rules_per_state(self):
		trip = self.run_trip([(self.plain_item, 5)], sales=[[(self.plain_item, 2)]])
		doc = self.draft(trip, returned={self.plain_item: 3})
		self.act(doc.name, "Submit for Verification", self.agent_a.user)

		def edit(user, change):
			frappe.set_user(user)
			try:
				target = frappe.get_doc("Mobile Settlement", doc.name)
				change(target)
				target.save()
			finally:
				frappe.set_user("Administrator")

		def set_returned(qty):
			return lambda d: setattr(d.stock_lines[0], "returned_qty", qty)

		def set_cash(amount):
			return lambda d: setattr(d, "cash_handed_over", amount)

		with self.assertRaisesRegex(frappe.PermissionError, "cannot change"):
			edit(self.agent_a.user, set_returned(2))
		with self.assertRaisesRegex(frappe.PermissionError, "cannot change"):
			edit(STORE_KEEPER, set_cash(1))
		edit(STORE_KEEPER, set_returned(2))

		self.act(doc.name, "Verify Stock", STORE_KEEPER)
		with self.assertRaisesRegex(frappe.PermissionError, "cannot change"):
			edit(CASHIER, set_returned(3))
		edit(CASHIER, set_cash(150))
		doc.reload()
		self.assertEqual((doc.stock_lines[0].returned_qty, doc.cash_handed_over, doc.verified_by_store), (2, 150, STORE_KEEPER))

	# 7
	def test_excess_stock_blocks_submit(self):
		trip = self.run_trip([(self.plain_item, 5)], sales=[[(self.plain_item, 2)]])
		doc = self.draft(trip, returned={self.plain_item: 4})
		self.assertEqual(doc.stock_lines[0].excess_qty, 1)
		self.act(doc.name, "Submit for Verification", self.agent_a.user)
		self.act(doc.name, "Verify Stock", STORE_KEEPER)
		with self.assertRaisesRegex(frappe.ValidationError, "more than expected"):
			self.act(doc.name, "Verify Cash", CASHIER)

	# 8
	def test_bin_ledger_mismatch_blocks_submit(self):
		trip = self.run_trip([(self.plain_item, 5)])
		with patch("mobilesales.overrides.guards.get_guard_context", return_value=guards.EMPTY_CONTEXT):
			make_receipt(self.company, self.plain_item, 1, self.agent_a.van_warehouse)
		doc = self.draft(trip, returned={self.plain_item: 5})
		self.act(doc.name, "Submit for Verification", self.agent_a.user)
		self.act(doc.name, "Verify Stock", STORE_KEEPER)
		with self.assertRaisesRegex(frappe.ValidationError, "van stock is 6.0 but the trip ledger expects 5.0"):
			self.act(doc.name, "Verify Cash", CASHIER)

	# 9
	def test_batches_return_oldest_first_and_named_damage(self):
		trip = self.run_trip([(self.batch_item, 7)], sales=[[(self.batch_item, 3)]])  # van: A 2, B 2
		doc = self.draft(trip, returned={self.batch_item: 2}, damaged={self.batch_item: 1}, damaged_batch={self.batch_item: self.batch_b})
		self.assertEqual(
			{(r.batch_no, r.expected, r.returned, r.damaged, r.missing) for r in doc.batch_lines},
			{(self.batch_a, 2, 2, 0, 0), (self.batch_b, 2, 0, 1, 1)},
		)
		doc = self.approve_flow(doc.name)
		self.assertEqual(self.se_rows(doc.return_entry), [(self.batch_item, 2, self.batch_a)])
		self.assertEqual(self.se_rows(doc.damage_entry), [(self.batch_item, 1, self.batch_b)])
		self.assertEqual(self.se_rows(doc.shortage_entry), [(self.batch_item, 1, self.batch_b)])

	# 10
	def test_recover_shortages_from_agent(self):
		employee = frappe.get_doc(
			{
				"doctype": "Employee",
				"first_name": f"{PREFIX} Employee",
				"gender": frappe.db.get_value("Gender", {}),
				"date_of_birth": add_years(nowdate(), -30),
				"date_of_joining": add_years(nowdate(), -1),
				"company": self.company,
				"status": "Active",
			}
		).insert().name
		frappe.db.set_value("Mobile Sales Agent", self.agent_a.name, "employee", employee)
		self.set_setting("recover_shortage_from_agent", 1)

		trip = self.run_trip([(self.plain_item, 10)], sales=[[(self.plain_item, 5)]])
		doc = self.draft(trip, returned={self.plain_item: 3}, handed=450)
		self.assertEqual(doc.variance_action, "Recover from Agent")
		doc = self.approve_flow(doc.name)
		value = flt(frappe.db.get_value("Stock Entry", doc.shortage_entry, "total_outgoing_value"), 2)
		self.assertEqual(self.je_lines(doc.recovery_journal), {(self.recovery_account, value, 0, employee), (self.settings.stock_shortage_account, 0, value, None)})
		self.assertEqual(self.je_lines(doc.variance_journal), {(self.recovery_account, 50, 0, employee), (self.agent_a.cash_account, 0, 50, None)})

	# 11
	def test_cancel_reverses_and_allows_resettle(self):
		trip = self.run_trip([(self.plain_item, 5)], sales=[[(self.plain_item, 2)]], opening_cash_float=100)
		doc = self.approve_flow(self.draft(trip, returned={self.plain_item: 2}, handed=250).name)
		postings = [doc.get(f) for f in ("return_entry", "shortage_entry", "cash_journal", "variance_journal")]
		self.assertTrue(all(postings))

		doc = self.act(doc.name, "Cancel", SUPERVISOR)
		self.assertEqual((doc.docstatus, doc.workflow_state), (2, "Cancelled"))
		for name in postings:
			doctype = "Stock Entry" if frappe.db.exists("Stock Entry", name) else "Journal Entry"
			self.assertEqual(frappe.db.get_value(doctype, name, "docstatus"), 2, name)
		trip.reload()
		self.assertEqual((trip.status, trip.settlement), ("Settling", None))
		self.assertEqual([r.purpose for r in trip.stock_entries], ["Issue"])
		self.assertEqual(self.van_qty(self.plain_item), 3)

		again = self.approve_flow(self.draft(trip, returned={self.plain_item: 3}).name)
		self.assertNotEqual(again.name, doc.name)
		self.assertEqual(again.docstatus, 1)

	# 12
	def test_lifecycle_rules(self):
		in_field = self.run_trip([(self.plain_item, 5)], end_day=False)
		with as_user(self.agent_a.user):
			with self.assertRaisesRegex(frappe.ValidationError, "settle only after End Day"):
				frappe.get_doc({"doctype": "Mobile Settlement", "mobile_trip": in_field.name}).insert()
			draft_visit = frappe.get_doc(
				{"doctype": "Customer Visit", "mobile_trip": in_field.name, "customer": self.customer, "visit_datetime": now_datetime(),
				 "outcome": "Sale", "sale_items": [{"item_code": self.plain_item, "qty": 1}], "collect_amount": 100}
			).insert()  # fmt: skip
			with self.assertRaisesRegex(frappe.ValidationError, "Submit or delete the draft visits"):
				trip_service.end_day(in_field.name)
			frappe.delete_doc("Customer Visit", draft_visit.name)  # agents may delete their own drafts
			trip_service.end_day(in_field.name)

		first = self.draft(in_field, returned={self.plain_item: 5})
		with as_user(self.users.store):
			with self.assertRaisesRegex(frappe.ValidationError, "already has settlement"):
				frappe.get_doc({"doctype": "Mobile Settlement", "mobile_trip": in_field.name}).insert()
			self.assertEqual(settlement.make_settlement(in_field.name), first.name)

		frappe.db.set_value("Mobile Trip", in_field.name, "status", "In Field")
		with self.assertRaisesRegex(frappe.ValidationError, "already has settlement"):
			self.sell(in_field.name, [(self.plain_item, 1)])

	def test_manual_settlement_stock_entry_rejected(self):
		trip = self.run_trip([(self.plain_item, 5)])
		se = frappe.get_doc(
			{"doctype": "Stock Entry", "stock_entry_type": "Material Transfer", "company": self.company, "mobile_trip": trip.name,
			 "mobile_purpose": "Return", "items": [{"item_code": self.plain_item, "qty": 1, "s_warehouse": trip.van_warehouse, "t_warehouse": self.store}]}
		)  # fmt: skip
		se.flags[guards.INTERNAL_FLAG] = True
		with as_user(self.users.office), self.assertRaisesRegex(frappe.ValidationError, "created only by Mobile Settlement"):
			se.insert()

	# 13
	def test_agent_cannot_see_other_agents_settlement(self):
		own = self.draft(self.run_trip([(self.plain_item, 2)]), returned={self.plain_item: 2})
		other = self.draft(self.run_trip([(self.plain_item, 2)], agent=self.agent_b), returned={self.plain_item: 2}, agent=self.agent_b)

		frappe.set_user(self.agent_a.user)
		self.assertEqual(frappe.get_list("Mobile Settlement", pluck="name"), [own.name])
		self.assertFalse(frappe.has_permission("Mobile Settlement", "read", doc=other.name))
		with self.assertRaises(frappe.PermissionError):
			mobile_api.get_settlement_draft(other.mobile_trip)
		self.assertEqual(mobile_api.get_settlement_draft(own.mobile_trip)["expected_cash"], 0)

	def test_real_roles_post_batch_documents(self):
		"""Store keeper loads, agent sells, cashier submits: each creates Serial and Batch Bundles."""
		trip = self.run_trip([(self.batch_item, 6)], sales=[[(self.batch_item, 2)]])
		self.assertEqual(frappe.db.get_value("Mobile Trip", trip.name, "owner"), STORE_KEEPER)
		invoice = frappe.db.get_value("Sales Invoice", {"mobile_trip": trip.name}, ["name", "owner"], as_dict=True)
		self.assertEqual(invoice.owner, self.agent_a.user)
		doc = self.approve_flow(self.draft(trip, returned={self.batch_item: 4}).name)
		self.assertEqual(doc.docstatus, 1)
		self.assertEqual(frappe.db.get_value("Stock Entry", doc.return_entry, "owner"), CASHIER)

	def test_reject_from_pending_cashier_clears_verifiers(self):
		trip = self.run_trip([(self.plain_item, 2)])
		doc = self.draft(trip, returned={self.plain_item: 2})
		self.act(doc.name, "Submit for Verification", self.agent_a.user)
		doc = self.act(doc.name, "Verify Stock", STORE_KEEPER)
		self.assertEqual((doc.workflow_state, doc.verified_by_store), ("Pending Cashier", STORE_KEEPER))

		doc = self.act(doc.name, "Reject", CASHIER)
		self.assertEqual((doc.workflow_state, doc.docstatus), ("Draft", 0))
		self.assertFalse(doc.verified_by_store or doc.verified_by_cashier)

		doc = self.approve_flow(doc.name)  # recounted and verified again from Draft
		self.assertEqual((doc.docstatus, doc.verified_by_store, doc.verified_by_cashier), (1, STORE_KEEPER, CASHIER))

	# Reopen Trip (Settling -> In Field)

	def test_reopen_trip_rules(self):
		trip = self.run_trip([(self.plain_item, 5)], sales=[[(self.plain_item, 1)]])
		for user in (self.agent_b.user, STORE_KEEPER, CASHIER):
			with as_user(user), self.assertRaises(frappe.PermissionError):
				trip_service.reopen_trip(trip.name)

		# no settlement yet: the agent reopens, sells again, ends the day again
		with as_user(self.agent_a.user):
			self.assertEqual(mobile_api.reopen_trip(trip.name), "In Field")
			with self.assertRaisesRegex(frappe.ValidationError, "needs status"):
				trip_service.reopen_trip(trip.name)
		self.sell(trip.name, [(self.plain_item, 1)])
		with as_user(self.agent_a.user):
			trip_service.end_day(trip.name)

		# draft settlement: deleted on reopen
		draft = self.draft(trip, returned={self.plain_item: 3})
		with as_user(self.agent_a.user):
			self.assertEqual(trip_service.reopen_trip(trip.name), "In Field")
			self.assertFalse(frappe.db.exists("Mobile Settlement", draft.name))
			self.assertIn("reopened", frappe.get_all("Comment", filters={"reference_name": trip.name, "comment_type": "Info"}, pluck="content")[0])
			trip_service.end_day(trip.name)

		# Pending Store: refused for everyone until a supervisor rejects it to Draft
		draft = self.draft(trip, returned={self.plain_item: 3})
		self.act(draft.name, "Submit for Verification", self.agent_a.user)
		for user in (self.agent_a.user, SUPERVISOR):
			with as_user(user), self.assertRaisesRegex(frappe.ValidationError, "reject it to Draft"):
				trip_service.reopen_trip(trip.name)
		self.assertEqual(frappe.db.get_value("Mobile Trip", trip.name, "status"), "Settling")
		self.act(draft.name, "Reject", SUPERVISOR)
		with as_user(SUPERVISOR):
			self.assertEqual(trip_service.reopen_trip(trip.name), "In Field")
		self.assertFalse(frappe.db.exists("Mobile Settlement", draft.name))

		# settled: never
		with as_user(self.agent_a.user):
			trip_service.end_day(trip.name)
		done = self.approve_flow(self.draft(trip, returned={self.plain_item: 3}).name)
		self.assertEqual(done.docstatus, 1)
		with as_user(SUPERVISOR), self.assertRaisesRegex(frappe.ValidationError, "needs status"):
			trip_service.reopen_trip(trip.name)

	# Customer returns received (Phase 5b)

	def test_customer_returns_received_damage_and_shortage(self):
		trip = self.run_trip([(self.plain_item, 5)], sales=[[(self.plain_item, 2)]], end_day=False)
		with as_user(self.agent_a.user):
			visit = frappe.get_doc({
				"doctype": "Customer Visit", "mobile_trip": trip.name, "customer": self.customer, "visit_datetime": now_datetime(),
				"outcome": "Return Only", "return_items": [
					{"item_code": self.plain_item, "qty": 2, "return_reason": "Unsold / Slow-moving", "condition": "Resaleable"},
					{"item_code": self.plain_item, "qty": 1, "return_reason": "Damaged", "condition": "Damaged"},
				],
			}).insert()  # fmt: skip
			visit.submit()
			trip_service.end_day(trip.name)
		returns_wh = self.customer_returns

		def returns_qty():
			return flt(frappe.db.get_value("Bin", {"warehouse": returns_wh, "item_code": self.plain_item}, "actual_qty"))

		self.assertEqual(returns_qty(), 3)
		draft = self.draft(trip, returned={self.plain_item: 3})
		(line,) = draft.return_lines
		self.assertEqual((line.credited_qty, line.credited_damaged_qty, line.received_qty, line.damaged_qty, line.missing_qty), (3, 1, 3, 1, 0))
		self.assertEqual(draft.invoice_count, 1)  # the credit note is not a sale

		# the agent cannot change return counts; the store keeper counts at Pending Store
		frappe.set_user(self.agent_a.user)
		doc = frappe.get_doc("Mobile Settlement", draft.name)
		doc.return_lines[0].received_qty = 1
		with self.assertRaisesRegex(frappe.PermissionError, "customer return counts"):
			doc.save()
		frappe.set_user("Administrator")
		self.act(draft.name, "Submit for Verification", self.agent_a.user)
		with as_user(STORE_KEEPER):
			doc = frappe.get_doc("Mobile Settlement", draft.name)
			doc.return_lines[0].received_qty = 2
			doc.return_lines[0].damaged_qty = 3
			doc.save()  # counts may be entered in any order; submit checks them
			doc.reload()
			doc.workflow_state = "Approved"
			with self.assertRaisesRegex(frappe.ValidationError, "damaged 3.0 is more than received 2.0"):
				settlement.before_submit(doc)
			doc.reload()
			doc.return_lines[0].received_qty = 2
			doc.return_lines[0].damaged_qty = 1
			doc.save()
		doc.reload()
		self.assertEqual((doc.return_lines[0].missing_qty, doc.return_lines[0].missing_value > 0), (1, True))
		self.act(draft.name, "Verify Stock", STORE_KEEPER)
		done = self.act(draft.name, "Verify Cash", CASHIER)
		self.assertEqual(done.docstatus, 1)

		self.assertEqual(self.se_rows(done.return_damage_entry), [(self.plain_item, 1, None)])
		self.assertEqual(self.se_rows(done.return_shortage_entry), [(self.plain_item, 1, None)])
		damage = frappe.get_doc("Stock Entry", done.return_damage_entry)
		self.assertEqual((damage.mobile_purpose, damage.items[0].s_warehouse, damage.items[0].t_warehouse), ("Return Damage", returns_wh, self.damage_wh))
		self.assertEqual(frappe.db.get_value("Stock Entry", done.return_shortage_entry, "mobile_purpose"), "Return Shortage")
		self.assertEqual(returns_qty(), 1)  # the good return stays for the store
		sheet = frappe.get_print("Mobile Settlement", done.name, print_format="Mobile Settlement Sheet")
		self.assertIn("Customer Returns Received", sheet)
		self.assertIn(done.return_shortage_entry, sheet)
		purposes = [r.purpose for r in frappe.get_doc("Mobile Trip", trip.name).stock_entries]
		self.assertIn("Return Damage", purposes)
		self.assertIn("Return Shortage", purposes)

		with as_user(SUPERVISOR):
			frappe.get_doc("Mobile Settlement", done.name).cancel()
		for name in (done.return_damage_entry, done.return_shortage_entry):
			self.assertEqual(frappe.db.get_value("Stock Entry", name, "docstatus"), 2)
		self.assertEqual(returns_qty(), 3)
		self.assertEqual(frappe.db.get_value("Mobile Trip", trip.name, "status"), "Settling")
