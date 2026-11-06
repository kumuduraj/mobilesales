"""v1.0.2: one route order everywhere, customer identification and search, out-of-sequence visits, name changes
that wait for a supervisor, and an optional batch per load / top-up row. Flows run as the real role users
(rule 13); Administrator only sets up data."""

from datetime import timedelta
from unittest.mock import patch

import frappe
from frappe.utils import add_days, flt, now_datetime, nowdate

from erpnext.stock.doctype.batch.batch import get_batch_qty

from mobilesales.api import mobile as api
from mobilesales.patches.v1_0 import renumber_route_sequence
from mobilesales.services import customer_update, customers, reports, stock
from mobilesales.services import trip as trip_service
from mobilesales.tests.test_settlement import SUPERVISOR, SettlementTestBase
from mobilesales.tests.utils import PREFIX, as_user, leaf, make_receipt


class TestV102(SettlementTestBase):
	# helpers

	def make_customer(self, name, line1=None, city=None, mobile=None):
		doc = frappe.get_doc({"doctype": "Customer", "customer_name": f"{PREFIX} {name}", "customer_group": leaf("Customer Group"),
			"territory": leaf("Territory")}).insert()  # fmt: skip
		if line1 or city:
			address = frappe.get_doc({"doctype": "Address", "address_title": doc.customer_name, "address_type": "Billing",
				"address_line1": line1 or "-", "city": city or "-", "country": "Sri Lanka", "is_primary_address": 1,
				"links": [{"link_doctype": "Customer", "link_name": doc.name}]}).insert()  # fmt: skip
			doc.db_set("customer_primary_address", address.name)
		if mobile:
			doc.db_set("mobile_no", mobile)
		return doc.name

	def make_route(self, rows, user=SUPERVISOR):
		with as_user(user):
			return frappe.get_doc({"doctype": "Mobile Route", "route_name": f"{PREFIX} Route {frappe.generate_hash(length=6)}",
				"customers": [{"customer": c, "sequence": s} for c, s in rows]}).insert()  # fmt: skip

	def route_order(self, route):
		return [(r.customer, r.sequence) for r in frappe.get_doc("Mobile Route", route).customers]

	def load(self, rows, agent=None):
		"""A trip loaded by the store keeper: rows (item, qty, batch or None)."""
		agent = agent or self.agent_a
		trip = frappe.get_doc({"doctype": "Mobile Trip", "agent": agent.name, "trip_date": nowdate(),
			"load_items": [{"item_code": i, "qty": q, "batch_no": b} for i, q, b in rows]})  # fmt: skip
		with as_user(self.users.store):
			trip.insert()
			trip.submit()
		return frappe.get_doc("Mobile Trip", trip.name)

	def van_batches(self, agent=None):
		van = (agent or self.agent_a).van_warehouse
		return {b["batch_no"]: flt(b["qty"]) for b in get_batch_qty(warehouse=van, item_code=self.batch_item) if flt(b["qty"])}

	def issue_batches(self, trip):
		"""{batch: qty} of the trip's Issue entry (its Serial and Batch Entries)."""
		se = frappe.db.get_value("Mobile Trip Stock Entry", {"parent": trip.name, "purpose": "Issue"}, "stock_entry")
		out = {}
		for row in frappe.get_all("Stock Entry Detail", filters={"parent": se, "item_code": self.batch_item}, pluck="serial_and_batch_bundle"):
			for e in frappe.get_all("Serial and Batch Entry", filters={"parent": row}, fields=["batch_no", "qty"]):
				out[e.batch_no] = out.get(e.batch_no, 0) + abs(flt(e.qty))
		return out

	def visit(self, trip, customer, minutes, user=None, **fields):
		with as_user(user or self.agent_a.user):
			doc = frappe.get_doc({"doctype": "Customer Visit", "mobile_trip": trip.name, "customer": customer,
				"visit_datetime": now_datetime() + timedelta(minutes=minutes), "outcome": "Shop Closed", **fields}).insert()  # fmt: skip
			doc.submit()
		return frappe.get_doc("Customer Visit", doc.name)

	# 2. route order

	def test_route_rows_sorted_by_sequence_and_numbered_on_save(self):
		c1, c2, c3, c4 = (self.make_customer(n) for n in ("R1", "R2", "R3", "R4"))
		route = self.make_route([(c1, 3), (c2, 1), (c3, None), (c4, 1)])
		# by Sequence, the tie (c2, c4) in row order, the empty one last; then 1, 2, 3, 4
		self.assertEqual(self.route_order(route.name), [(c2, 1), (c4, 2), (c1, 3), (c3, 4)])

		# a drag in Desk: the JS sets Sequence = row order, the save keeps it
		with as_user(SUPERVISOR):
			doc = frappe.get_doc("Mobile Route", route.name)
			doc.customers.reverse()
			for idx, row in enumerate(doc.customers, start=1):
				row.idx = row.sequence = idx
			doc.save()
		self.assertEqual(self.route_order(route.name), [(c3, 1), (c1, 2), (c4, 3), (c2, 4)])

		# the phone shows the same order
		frappe.db.set_value("Mobile Sales Agent", self.agent_a.name, "default_route", route.name)
		trip = self.run_trip([(self.plain_item, 1)], end_day=False)
		with as_user(self.agent_a.user):
			plan = api.get_route_plan(trip.name)
		self.assertEqual([(r.customer, r.sequence) for r in plan], self.route_order(route.name))

	def test_renumber_patch_once_and_idempotent(self):
		c1, c2, c3 = (self.make_customer(n) for n in ("P1", "P2", "P3"))
		route = self.make_route([(c1, 1), (c2, 2), (c3, 3)])
		rows = {r.customer: r.name for r in route.customers}
		# an existing route from before v1.0.2: gaps, a tie and an empty sequence
		for customer, (idx, sequence) in {c1: (1, 7), c2: (2, 0), c3: (3, 2)}.items():  # 0: no sequence
			frappe.db.set_value("Mobile Route Customer", rows[customer], {"idx": idx, "sequence": sequence}, update_modified=False)
		renumber_route_sequence.execute()
		self.assertEqual(self.route_order(route.name), [(c3, 1), (c1, 2), (c2, 3)])
		with patch.object(frappe.db, "set_value", wraps=frappe.db.set_value) as writes:
			renumber_route_sequence.execute()
		self.assertEqual([c for c in writes.call_args_list if c.args and c.args[0] == "Mobile Route Customer"], [])

	def test_route_coverage_flags_visits_out_of_sequence(self):
		c1, c2, c3 = (self.make_customer(n) for n in ("S1", "S2", "S3"))
		route = self.make_route([(c1, 1), (c2, 2), (c3, 3)])
		frappe.db.set_value("Mobile Sales Agent", self.agent_a.name, "default_route", route.name)
		trip = self.run_trip([(self.plain_item, 1)], end_day=False)
		for minutes, customer in enumerate((c1, c3, c2)):  # c2 after c3: out of sequence (allowed)
			self.visit(trip, customer, minutes)
		with as_user(self.agent_a.user):
			plan = api.get_route_plan(trip.name)
		self.assertEqual([(r.customer, r.visited, r.outcome) for r in plan], [(c1, True, "Shop Closed"), (c2, True, "Shop Closed"), (c3, True, "Shop Closed")])
		with as_user(SUPERVISOR):
			rows = reports.coverage_rows({"mobile_trip": trip.name})
		self.assertEqual({r.customer: r.out_of_sequence for r in rows}, {c1: 0, c2: 1, c3: 0})
		self.assertEqual({r.trip_out_of_sequence for r in rows}, {1})

	# 1. identification and search

	def test_search_by_address_city_and_mobile_with_the_identification_line(self):
		shop = self.make_customer("Lake Shop", line1="12 Lake Road", city="Kandy", mobile="077 123 9876")
		self.make_customer("Other Shop", line1="5 Hill Street", city="Galle")
		with as_user(self.agent_a.user):
			for text in ("Lake Road", "kandy", "9876", "0771239876", "Lake Shop"):
				found = api.search_customers(text)
				self.assertEqual([r.name for r in found], [shop], text)
			(row,) = api.search_customers("Kandy")
			card = api.get_customer(shop)
		self.assertEqual((row.address_line1, row.city, row.mobile_no), ("12 Lake Road", "Kandy", "077 123 9876"))
		self.assertEqual(customers.identification(row), "12 Lake Road, Kandy · …9876")
		self.assertEqual((card["address_line1"], card["city"], card["mobile_no"]), ("12 Lake Road", "Kandy", "077 123 9876"))
		# Desk link search on Customer Visit / Mobile Route
		with as_user(SUPERVISOR):
			result = customers.customer_query("Customer", "Lake", "name", 0, 20, {})
		self.assertEqual(result, [(shop, f"{PREFIX} Lake Shop", "12 Lake Road, Kandy · …9876")])

	# 4. credit

	def test_card_balance_is_the_net_and_shows_credit(self):
		with as_user(self.agent_a.user):
			card = api.get_customer(self.customer)
		self.assertEqual(card["balance"], card["outstanding"] - card["credit_available"])

	# 5. name change

	def name_visit(self, trip, minutes, **changes):
		return self.visit(trip, self.customer, minutes, update_customer=1, **changes)

	def test_name_change_waits_for_approval_other_fields_follow_settings(self):
		self.set_setting("apply_customer_updates_directly", 1)
		trip = self.run_trip([(self.plain_item, 1)], end_day=False)
		old_name = frappe.db.get_value("Customer", self.customer, "customer_name")
		visit = self.name_visit(trip, 0, new_customer_name=f"{PREFIX} Renamed Shop", new_address_line1="7 New Lane", new_city="Negombo", new_mobile_no="0779990000")
		status = {r.field_key: r.status for r in visit.changes}
		self.assertEqual(status.pop("customer.customer_name"), "Pending Approval")
		self.assertEqual(set(status.values()), {"Applied"})
		self.assertEqual(visit.customer_update_status, "Pending Approval")
		self.assertEqual(frappe.db.get_value("Customer", self.customer, "customer_name"), old_name)
		with as_user(self.agent_a.user):
			card = api.get_customer(self.customer)
		self.assertEqual((card["pending_name"], card["city"], card["mobile_no"]), (f"{PREFIX} Renamed Shop", "Negombo", "0779990000"))

		with as_user(SUPERVISOR):
			self.assertEqual(customer_update.approve_customer_update(visit.name), "Applied")
		self.assertEqual(frappe.db.get_value("Customer", self.customer, "customer_name"), f"{PREFIX} Renamed Shop")
		with as_user(self.agent_a.user):
			self.assertIsNone(api.get_customer(self.customer)["pending_name"])

	def test_name_change_rejected_and_direct_when_allowed(self):
		self.set_setting("apply_customer_updates_directly", 1)
		trip = self.run_trip([(self.plain_item, 1)], end_day=False)
		old_name = frappe.db.get_value("Customer", self.customer, "customer_name")
		visit = self.name_visit(trip, 0, new_customer_name=f"{PREFIX} Wrong Name")
		with as_user(SUPERVISOR):
			self.assertEqual(customer_update.reject_customer_update(visit.name), "Rejected")
		self.assertEqual(frappe.db.get_value("Customer", self.customer, "customer_name"), old_name)

		self.set_setting("allow_direct_name_change", 1)
		visit = self.name_visit(trip, 1, new_customer_name=f"{PREFIX} Direct Name")
		self.assertEqual((visit.customer_update_status, [r.status for r in visit.changes]), ("Applied", ["Applied"]))
		self.assertEqual(frappe.db.get_value("Customer", self.customer, "customer_name"), f"{PREFIX} Direct Name")

		# without direct updates everything waits, the name too
		self.set_setting("apply_customer_updates_directly", 0)
		visit = self.name_visit(trip, 2, new_customer_name=f"{PREFIX} Later Name", new_tax_id="TX-1")
		self.assertEqual({r.status for r in visit.changes}, {"Pending Approval"})

	# 6. batch on load

	def test_chosen_batch_lands_in_the_van_and_the_picker_lists_unexpired_batches_oldest_first(self):
		with as_user(self.users.store):
			options = stock.load_batch_query("Batch", "", "name", 0, 20, {"item_code": self.batch_item, "warehouse": self.store})
		self.assertEqual([o[0] for o in options], [self.batch_a, self.batch_b])
		self.assertTrue(options[0][1].startswith("5 Nos available"), options)
		trip = self.load([(self.batch_item, 3, self.batch_b)])
		self.assertEqual(self.van_batches(), {self.batch_b: 3})
		self.assertEqual((trip.load_items[0].batch_no, trip.load_items[0].available_at_source), (self.batch_b, 10))

	def test_mixed_rows_chosen_and_fifo_in_one_entry(self):
		trip = self.load([(self.batch_item, 2, self.batch_b), (self.batch_item, 4, None)])
		# the FIFO row takes the oldest batch, never the units the chosen row already took
		self.assertEqual(self.issue_batches(trip), {self.batch_b: 2, self.batch_a: 4})
		self.assertEqual(self.van_batches(), {self.batch_a: 4, self.batch_b: 2})
		self.assertEqual(len(trip.stock_entries), 1)

	def test_mixed_rows_fifo_spills_over_what_the_chosen_batch_leaves(self):
		trip = self.load([(self.batch_item, 4, self.batch_a), (self.batch_item, 3, None)])
		self.assertEqual(self.issue_batches(trip), {self.batch_a: 5, self.batch_b: 2})

	def test_two_rows_same_item_different_batches(self):
		self.load([(self.batch_item, 2, self.batch_a), (self.batch_item, 3, self.batch_b)])
		self.assertEqual(self.van_batches(), {self.batch_a: 2, self.batch_b: 3})

	def test_qty_above_the_batch_refused_counting_every_row_of_that_batch(self):
		for rows in ([(self.batch_item, 6, self.batch_a)], [(self.batch_item, 3, self.batch_a), (self.batch_item, 3, self.batch_a)]):
			with self.assertRaisesRegex(frappe.ValidationError, rf"Batch .*{self.batch_a}.*: 5\.?0? Nos available.*need 6"):
				self.load(rows)

	def test_expired_or_foreign_batch_not_offered_and_refused(self):
		expired = frappe.get_doc({"doctype": "Batch", "batch_id": f"{PREFIX} Batch Old", "item": self.batch_item}).insert().name
		make_receipt(self.company, self.batch_item, 4, self.store, batch_no=expired, posting_date=add_days(nowdate(), -3))
		frappe.db.set_value("Batch", expired, "expiry_date", add_days(nowdate(), -1))
		with as_user(self.users.store):
			options = stock.load_batch_query("Batch", "", "name", 0, 20, {"item_code": self.batch_item, "warehouse": self.store})
		self.assertNotIn(expired, [o[0] for o in options])
		with self.assertRaisesRegex(frappe.ValidationError, "expired"):
			self.load([(self.batch_item, 1, expired)])

	def test_top_up_with_a_batch(self):
		trip = self.load([(self.plain_item, 1, None)])
		with as_user(self.users.store):
			trip_service.top_up(trip.name, [{"item_code": self.batch_item, "qty": 2, "batch_no": self.batch_b}])
			with self.assertRaisesRegex(frappe.ValidationError, "need 11"):
				trip_service.top_up(trip.name, [{"item_code": self.batch_item, "qty": 11, "batch_no": self.batch_b}])
		self.assertEqual(self.van_batches(), {self.batch_b: 2})

	def test_non_batch_item_ignores_the_batch_field(self):
		trip = self.load([(self.plain_item, 2, self.batch_a)])
		self.assertIsNone(trip.load_items[0].batch_no)
		self.assertEqual(flt(frappe.db.get_value("Bin", {"warehouse": self.agent_a.van_warehouse, "item_code": self.plain_item}, "actual_qty")), 2)

	def test_sale_from_the_van_stays_fifo_among_the_van_batches(self):
		trip = self.load([(self.batch_item, 2, self.batch_b), (self.batch_item, 2, self.batch_a)])
		with as_user(self.agent_a.user):
			trip_service.start_trip(trip.name)
		visit = self.sell(trip.name, [(self.batch_item, 1)])
		bundle = frappe.db.get_value("Sales Invoice Item", {"parent": visit.sales_invoice}, "serial_and_batch_bundle")
		self.assertEqual(frappe.get_all("Serial and Batch Entry", filters={"parent": bundle}, pluck="batch_no"), [self.batch_a])
		self.assertEqual(self.van_batches(), {self.batch_a: 1, self.batch_b: 2})
