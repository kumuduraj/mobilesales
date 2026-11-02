"""Phase 3: Customer Visit outcomes, customer updates, invoicing, collection, cancel chain,
mobile voucher guards, agent permissions on standard DocTypes and naming series."""

import frappe
from frappe.utils import flt, now_datetime, nowdate

from mobilesales.overrides import guards, permissions
from mobilesales.services import customer_update, invoicing
from mobilesales.services import trip as trip_service
from mobilesales.setup.permissions import (
	AGENT_ROLE,
	ROLE_PERMISSIONS,
	check_standard_permission_drift,
)
from mobilesales.api import mobile as mobile_api
from mobilesales.tests.utils import PREFIX, MobileSalesTestCase, as_user, leaf

RIGHTS = (
	"permlevel", "if_owner", "select", "read", "write", "create", "delete", "submit", "cancel", "amend",
	"report", "export", "import", "share", "print", "email",
)  # fmt: skip


class TestCustomerVisit(MobileSalesTestCase):
	def setUp(self):
		super().setUp()
		self.trip_a = self.start_trip(self.agent_a)
		self.reason = frappe.get_doc(
			{"doctype": "Visit No Sale Reason", "reason": f"{PREFIX} Reason", "category": "Price"}
		).insert().name

	# helpers

	def start_trip(self, agent, start=True):
		trip = frappe.get_doc(
			{
				"doctype": "Mobile Trip",
				"agent": agent.name,
				"trip_date": nowdate(),
				"load_items": [
					{"item_code": self.plain_item, "qty": 10},
					{"item_code": self.batch_item, "qty": 7},
				],
			}
		)
		with as_user(self.users.store):
			trip.insert()
			trip.submit()
		if start:
			with as_user(agent.user):
				trip_service.start_trip(trip.name)
		return frappe.get_doc("Mobile Trip", trip.name)

	def visit(self, outcome="Sale", items=None, trip=None, collect="full", submit=True, user=None, **fields):
		"""Record a visit as the trip's own agent (or `user`), like the agent does on the road."""
		trip = trip or self.trip_a
		user = user or frappe.db.get_value("Mobile Sales Agent", trip.agent, "user")
		with as_user(user):
			return self._visit(outcome, items, trip, collect, submit, **fields)

	def _visit(self, outcome, items, trip, collect, submit, **fields):
		doc = frappe.get_doc(
			{
				"doctype": "Customer Visit",
				"mobile_trip": trip.name,
				"customer": self.customer,
				"visit_datetime": now_datetime(),
				"outcome": outcome,
				"sale_items": items or [],
				**fields,
			}
		)
		if outcome == "Sale" and collect == "full":
			doc.collect_amount = invoicing.payable_amount(invoicing.build_invoice(doc))
		elif outcome == "Sale":
			doc.collect_amount = collect
		doc.insert()
		if submit:
			doc.submit()
			doc.reload()
		return doc

	def set_setting(self, fieldname, value):
		old = self.settings.get(fieldname)
		self.settings.set(fieldname, value)
		self.addCleanup(self.settings.set, fieldname, old)

	def van_qty(self, item_code, agent=None):
		van = (agent or self.agent_a).van_warehouse
		return flt(frappe.db.get_value("Bin", {"warehouse": van, "item_code": item_code}, "actual_qty"))

	def standard_invoice(self, rate):
		si = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"company": self.company,
				"customer": self.customer,
				"items": [{"item_code": self.plain_item, "qty": 1, "rate": rate, "warehouse": self.store}],
			}
		)
		si.insert()
		si.submit()
		return si

	def other_customer(self):
		return frappe.get_doc(
			{"doctype": "Customer", "customer_name": f"{PREFIX} Other Customer", "customer_group": leaf("Customer Group"), "territory": leaf("Territory")}
		).insert().name

	# 1
	def test_no_sale_updates_customer_directly(self):
		self.set_setting("apply_customer_updates_directly", 1)
		with self.assertRaisesRegex(frappe.ValidationError, "No Sale Reason is required"):
			self.visit("No Sale", submit=False)

		visit = self.visit(
			"No Sale", no_sale_reason=self.reason, update_customer=1, new_mobile_no="0771234567"
		)
		self.assertFalse(visit.sales_invoice or visit.payment_entry)
		self.assertFalse(frappe.db.exists("Sales Invoice", {"customer_visit": visit.name}))
		self.assertEqual(visit.customer_update_status, "Applied")
		(change,) = visit.changes
		self.assertEqual((change.field_label, change.old_value, change.new_value, change.status), ("Mobile No", "", "0771234567", "Applied"))
		self.assertEqual(frappe.db.get_value("Customer", self.customer, "mobile_no"), "0771234567")

	def test_no_sale_rejects_items_and_requires_remark(self):
		frappe.db.set_value("Visit No Sale Reason", self.reason, "requires_remark", 1)
		with self.assertRaisesRegex(frappe.ValidationError, "Remarks are required"):
			self.visit("No Sale", no_sale_reason=self.reason, submit=False)
		with self.assertRaisesRegex(frappe.ValidationError, "Remove the sale items"):
			self.visit(
				"No Sale", no_sale_reason=self.reason, remarks="x",
				items=[{"item_code": self.plain_item, "qty": 1}], submit=False,
			)  # fmt: skip

	def test_shop_closed_needs_no_reason(self):
		visit = self.visit("Shop Closed")
		self.assertEqual((visit.docstatus, visit.no_sale_reason, visit.remarks), (1, None, None))
		self.assertFalse(visit.sales_invoice or visit.payment_entry)
		# a reason sent anyway is dropped (the field is hidden for Shop Closed), remarks are kept
		frappe.db.set_value("Visit No Sale Reason", self.reason, "requires_remark", 1)
		visit = self.visit("Shop Closed", no_sale_reason=self.reason, remarks="Back at 3 pm")
		self.assertEqual((visit.no_sale_reason, visit.remarks), (None, "Back at 3 pm"))
		with self.assertRaisesRegex(frappe.ValidationError, "Remove the sale items"):
			self.visit("Shop Closed", items=[{"item_code": self.plain_item, "qty": 1}], submit=False)
		self.assertEqual(frappe.db.get_value("Mobile Trip", self.trip_a.name, "no_sale_visits"), 2)

	def test_off_route_visits(self):
		on_route = frappe.get_doc(
			{"doctype": "Mobile Route", "route_name": f"{PREFIX} Visit Route", "customers": [{"customer": self.customer}]}
		).insert().name
		frappe.db.set_value("Mobile Trip", self.trip_a.name, "route", on_route)
		self.trip_a.reload()
		visit = self.visit("Shop Closed")
		self.assertEqual(visit.off_route, 0)

		# any customer may be visited and invoiced, as the agent, through the API
		other = self.other_customer()
		with as_user(self.agent_a.user):
			self.assertIn(other, [c.name for c in mobile_api.search_customers(f"{PREFIX} Other")])
			result = mobile_api.submit_visit(
				{
					"client_ref": "off-1", "mobile_trip": self.trip_a.name, "customer": other, "outcome": "Sale",
					"sale_items": [{"item_code": self.plain_item, "qty": 1}], "collect_amount": 100,
				}
			)  # fmt: skip
			history = {v.name: v.off_route for v in mobile_api.get_visits(self.trip_a.name)}
		self.assertTrue(result["sales_invoice"])
		self.assertEqual(frappe.db.get_value("Customer Visit", result["name"], "off_route"), 1)
		self.assertEqual(history, {visit.name: 0, result["name"]: 1})

		# a trip without a route: every visit is off route
		frappe.db.set_value("Mobile Trip", self.trip_a.name, "route", None)
		self.trip_a.reload()
		self.assertEqual(self.visit("Shop Closed").off_route, 1)

	# 2
	def test_pending_approval_then_approve_or_reject(self):
		self.set_setting("apply_customer_updates_directly", 0)
		visit = self.visit("No Sale", no_sale_reason=self.reason, update_customer=1, new_tax_id="TAX-1", new_city="Kandy", new_address_line1="1 Main St")
		self.assertEqual(visit.customer_update_status, "Pending Approval")
		self.assertEqual({r.status for r in visit.changes}, {"Pending Approval"})
		self.assertFalse(frappe.db.get_value("Customer", self.customer, "tax_id"))

		with as_user(self.users.supervisor):
			self.assertEqual(customer_update.approve_customer_update(visit.name), "Applied")
		self.assertEqual(frappe.db.get_value("Customer", self.customer, "tax_id"), "TAX-1")
		address = frappe.db.get_value("Customer", self.customer, "customer_primary_address")
		self.assertEqual(frappe.db.get_value("Address", address, "city"), "Kandy")

		rejected = self.visit("No Sale", no_sale_reason=self.reason, update_customer=1, new_tax_id="TAX-2")
		with as_user(self.users.supervisor):
			self.assertEqual(customer_update.reject_customer_update(rejected.name), "Rejected")
		self.assertEqual(frappe.db.get_value("Customer", self.customer, "tax_id"), "TAX-1")
		rejected.reload()
		self.assertEqual({r.status for r in rejected.changes}, {"Rejected"})

		with as_user(self.agent_a.user), self.assertRaises(frappe.PermissionError):
			customer_update.approve_customer_update(rejected.name)

	# 3
	def test_cash_sale_creates_invoice_and_payment(self):
		visit = self.visit(items=[{"item_code": self.plain_item, "qty": 2}, {"item_code": self.batch_item, "qty": 6}])
		si = frappe.get_doc("Sales Invoice", visit.sales_invoice)
		self.assertTrue(si.name.startswith("MB-SINV-"))
		self.assertEqual((si.docstatus, si.update_stock, si.is_mobile_sale), (1, 1, 1))
		self.assertEqual((si.mobile_trip, si.customer_visit, si.set_warehouse), (self.trip_a.name, visit.name, self.agent_a.van_warehouse))
		self.assertEqual({i.warehouse for i in si.items}, {self.agent_a.van_warehouse})
		self.assertEqual([(t.sales_person, t.allocated_percentage) for t in si.sales_team], [(self.agent_a.sales_person, 100)])
		self.assertEqual(si.outstanding_amount, 0)

		pe = frappe.get_doc("Payment Entry", visit.payment_entry)
		self.assertEqual((pe.docstatus, pe.paid_to, pe.mode_of_payment), (1, self.agent_a.cash_account, self.agent_a.mode_of_payment))
		self.assertEqual((pe.paid_amount, pe.reference_no, pe.mobile_trip, pe.customer_visit), (visit.rounded_total, visit.name, self.trip_a.name, visit.name))
		self.assertEqual([(r.reference_name, r.allocated_amount) for r in pe.references], [(si.name, visit.rounded_total)])

		self.assertEqual(self.van_qty(self.plain_item), 8)
		self.assertEqual(self.van_qty(self.batch_item), 1)
		batch_row = next(r for r in visit.sale_items if r.item_code == self.batch_item)
		self.assertIn(f"{self.batch_a}: 5", batch_row.batch_info)
		self.assertIn(f"{self.batch_b}: 1", batch_row.batch_info)

		trip = frappe.get_doc("Mobile Trip", self.trip_a.name)
		self.assertEqual((trip.visits, trip.sales_visits, trip.invoices), (1, 1, 1))
		self.assertEqual((flt(trip.invoiced_amount), flt(trip.collected_amount)), (si.grand_total, pe.paid_amount))

		self.assertIn(si.name, frappe.get_print("Sales Invoice", si.name, print_format="Mobile Invoice 4in"))
		self.assertIn(pe.name, frappe.get_print("Payment Entry", pe.name, print_format="Mobile Collection Receipt"))

	# 4
	def test_pricing_rule_totals_match_invoice(self):
		frappe.get_doc(
			{
				"doctype": "Pricing Rule",
				"title": f"{PREFIX} 10 pct",
				"apply_on": "Item Code",
				"items": [{"item_code": self.plain_item}],
				"selling": 1,
				"company": self.company,
				"rate_or_discount": "Discount Percentage",
				"discount_percentage": 10,
			}
		).insert()
		visit = self.visit(items=[{"item_code": self.plain_item, "qty": 3}])
		si = frappe.get_doc("Sales Invoice", visit.sales_invoice)
		self.assertEqual(visit.sale_items[0].rate, 90)
		self.assertEqual((visit.net_total, visit.grand_total), (si.net_total, si.grand_total))
		self.assertEqual(visit.rounded_total, invoicing.payable_amount(si))
		self.assertTrue(si.items[0].pricing_rules)

	def test_manual_discount_limited_by_agent(self):
		with self.assertRaisesRegex(frappe.ValidationError, "above your limit"):
			self.visit(items=[{"item_code": self.plain_item, "qty": 1, "discount_percentage": 5}], submit=False)
		frappe.db.set_value("Mobile Sales Agent", self.agent_a.name, "max_discount_pct", 5)
		visit = self.visit(items=[{"item_code": self.plain_item, "qty": 1, "discount_percentage": 5}])
		self.assertEqual(visit.sale_items[0].rate, 95)

	# 5
	def test_oversell_rejected(self):
		with self.assertRaisesRegex(frappe.ValidationError, "Not enough"):
			self.visit(items=[{"item_code": self.plain_item, "qty": 11}], submit=False)

		first_draft = self.visit(items=[{"item_code": self.plain_item, "qty": 6}], submit=False)
		second_draft = self.visit(items=[{"item_code": self.plain_item, "qty": 6}], submit=False)
		first_draft.submit()
		with self.assertRaisesRegex(frappe.ValidationError, "Not enough"):
			second_draft.submit()
		self.assertEqual(self.van_qty(self.plain_item), 4)

	# 6
	def test_credit_rules(self):
		self.set_setting("allow_credit_sales", 0)
		with self.assertRaisesRegex(frappe.ValidationError, "Credit sales are not allowed"):
			self.visit(items=[{"item_code": self.plain_item, "qty": 1}], collect=50, submit=False)

		self.set_setting("allow_credit_sales", 1)
		frappe.db.set_value("Mobile Sales Agent", self.agent_a.name, "credit_limit_per_invoice", 100)
		within = self.visit(items=[{"item_code": self.plain_item, "qty": 1}], collect=0)
		self.assertFalse(within.payment_entry)
		self.assertEqual(frappe.db.get_value("Sales Invoice", within.sales_invoice, "outstanding_amount"), 100)

		with self.assertRaisesRegex(frappe.ValidationError, "above your per-invoice credit limit"):
			self.visit(items=[{"item_code": self.plain_item, "qty": 2}], collect=50, submit=False)

	# 7
	def test_collection_only_allocates_previous_invoices(self):
		first, second = self.standard_invoice(100), self.standard_invoice(200)
		visit = self.visit(
			"Collection Only",
			collect_previous=[{"sales_invoice": first.name, "allocated": 100}, {"sales_invoice": second.name, "allocated": 50}],
		)
		self.assertEqual(visit.total_collected, 150)
		pe = frappe.get_doc("Payment Entry", visit.payment_entry)
		self.assertEqual({(r.reference_name, r.allocated_amount) for r in pe.references}, {(first.name, 100), (second.name, 50)})
		self.assertEqual(frappe.db.get_value("Sales Invoice", first.name, "outstanding_amount"), 0)
		self.assertEqual(frappe.db.get_value("Sales Invoice", second.name, "outstanding_amount"), 150)

		with self.assertRaisesRegex(frappe.ValidationError, "more than the outstanding"):
			self.visit("Collection Only", collect_previous=[{"sales_invoice": second.name, "allocated": 151}], submit=False)
		with self.assertRaisesRegex(frappe.ValidationError, "at least one previous invoice"):
			self.visit("Collection Only", submit=False)

	# 8
	def test_trip_not_in_field_or_other_agent_rejected(self):
		loaded_b = self.start_trip(self.agent_b, start=False)
		with self.assertRaisesRegex(frappe.ValidationError, "only possible while it is In Field"):
			self.visit("No Sale", no_sale_reason=self.reason, trip=loaded_b, submit=False)

		with self.assertRaises((frappe.PermissionError, frappe.ValidationError)):
			self.visit("No Sale", no_sale_reason=self.reason, submit=False, user=self.agent_b.user)

	def test_agent_can_record_own_visit(self):
		visit = self.visit(items=[{"item_code": self.plain_item, "qty": 1}])
		self.assertEqual((visit.docstatus, visit.owner), (1, self.agent_a.user))
		self.assertTrue(visit.sales_invoice and visit.payment_entry)

	# 9
	def test_cancel_chain(self):
		visit = self.visit(items=[{"item_code": self.plain_item, "qty": 3}])
		with as_user(self.agent_a.user), self.assertRaises(frappe.PermissionError):
			frappe.get_doc("Customer Visit", visit.name).cancel()

		with as_user(self.users.supervisor):
			frappe.get_doc("Customer Visit", visit.name).cancel()
		self.assertEqual(frappe.db.get_value("Payment Entry", visit.payment_entry, "docstatus"), 2)
		self.assertEqual(frappe.db.get_value("Sales Invoice", visit.sales_invoice, "docstatus"), 2)
		self.assertEqual(self.van_qty(self.plain_item), 10)
		trip = frappe.get_doc("Mobile Trip", self.trip_a.name)
		self.assertEqual((trip.visits, trip.invoices, flt(trip.collected_amount)), (0, 0, 0))

	def test_cancel_rejected_on_settled_trip(self):
		visit = self.visit(items=[{"item_code": self.plain_item, "qty": 1}])
		frappe.db.set_value("Mobile Trip", self.trip_a.name, "status", "Settled")
		with as_user(self.users.supervisor), self.assertRaisesRegex(frappe.ValidationError, "is Settled"):
			frappe.get_doc("Customer Visit", visit.name).cancel()

	# 10
	def test_manual_mobile_invoice_and_payment_rejected(self):
		si = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"company": self.company,
				"customer": self.customer,
				"update_stock": 1,
				"mobile_trip": self.trip_a.name,
				"items": [{"item_code": self.plain_item, "qty": 1, "rate": 100, "warehouse": self.agent_a.van_warehouse}],
			}
		)
		with as_user(self.users.office), self.assertRaisesRegex(
			frappe.ValidationError, "can only be created by the Mobile Sales app"
		):
			si.insert()

		def payment(paid_to):
			return frappe.get_doc(
				{
					"doctype": "Payment Entry",
					"payment_type": "Receive",
					"company": self.company,
					"party_type": "Customer",
					"party": self.customer,
					"paid_from": frappe.get_cached_value("Company", self.company, "default_receivable_account"),
					"paid_to": paid_to,
					"paid_amount": 10,
					"received_amount": 10,
					"source_exchange_rate": 1,
					"target_exchange_rate": 1,
					"mobile_trip": self.trip_a.name,
				}
			)

		with as_user(self.users.office):
			with self.assertRaisesRegex(frappe.ValidationError, "can only be created by the Mobile Sales app"):
				payment(self.agent_a.cash_account).insert()
			flagged = payment(self.main_cash)
			flagged.flags[guards.INTERNAL_FLAG] = True
			with self.assertRaisesRegex(frappe.ValidationError, "must be paid to the agent cash account"):
				flagged.insert()

	# 11
	def test_agents_see_only_own_visits_invoices_payments(self):
		trip_b = self.start_trip(self.agent_b)
		visit_a = self.visit(items=[{"item_code": self.plain_item, "qty": 1}])
		visit_b = self.visit(items=[{"item_code": self.plain_item, "qty": 1}], trip=trip_b)

		frappe.set_user(self.agent_a.user)
		for doctype, field in (("Customer Visit", "name"), ("Sales Invoice", "sales_invoice"), ("Payment Entry", "payment_entry")):
			own, other = visit_a.get(field), visit_b.get(field)
			self.assertEqual(frappe.get_list(doctype, filters={"name": ["in", [own, other]]}, pluck="name"), [own], doctype)
			self.assertTrue(frappe.has_permission(doctype, "read", doc=own))
			self.assertFalse(frappe.has_permission(doctype, "read", doc=other))
			with self.assertRaises(frappe.PermissionError):
				frappe.get_doc(doctype, other).check_permission("read")
		self.assertFalse(frappe.has_permission("Sales Invoice", "create"))

		frappe.set_user(self.users.office)
		invoices = [visit_a.sales_invoice, visit_b.sales_invoice]
		self.assertEqual(sorted(frappe.get_list("Sales Invoice", filters={"name": ["in", invoices]}, pluck="name")), sorted(invoices))
		self.assertTrue(all(frappe.has_permission("Sales Invoice", "read", doc=name) for name in invoices))

	def test_agent_with_accounts_or_sales_role_keeps_standard_scope(self):
		trip_b = self.start_trip(self.agent_b)
		visit_b = self.visit(items=[{"item_code": self.plain_item, "qty": 1}], trip=trip_b)
		user_a = self.agent_a.user
		self.addCleanup(frappe.clear_cache, user=user_a)  # role cache must not outlive the savepoint
		for role in ("Accounts Manager", "Accounts User", "Sales Manager", "Sales User"):
			user = frappe.get_doc("User", user_a)
			user.flags.ignore_permissions = True
			user.add_roles(role)
			frappe.set_user(user_a)
			for doctype, field in (("Sales Invoice", "sales_invoice"), ("Payment Entry", "payment_entry")):
				name = visit_b.get(field)
				self.assertEqual(frappe.get_list(doctype, filters={"name": name}, pluck="name"), [name], (role, doctype))
				self.assertTrue(frappe.has_permission(doctype, "read", doc=name), (role, doctype))
			# Customer Visit role scope is lifted too (its User Permission from agent setup still applies).
			self.assertEqual(permissions.visit_query_conditions(user_a), "", role)
			self.assertTrue(permissions.visit_has_permission(visit_b, "read", user_a), role)
			# Mobile Trip scope is unchanged: still own trips only.
			self.assertNotEqual(permissions.trip_query_conditions(user_a), "", role)
			frappe.set_user("Administrator")
			user.reload()
			user.flags.ignore_permissions = True
			user.remove_roles(role)

	# 12
	def test_permission_integrity_for_existing_roles(self):
		for doctype, managed in ROLE_PERMISSIONS.items():
			standard = sorted(tuple(p.get(r) for r in ("role", *RIGHTS)) for p in frappe.get_all("DocPerm", filters={"parent": doctype}, fields=["role", *RIGHTS]))
			custom = frappe.get_all("Custom DocPerm", filters={"parent": doctype}, fields=["role", *RIGHTS])
			kept = sorted(tuple(p.get(r) for r in ("role", *RIGHTS)) for p in custom if p.role not in managed)
			self.assertEqual(kept, standard, doctype)
			for role, rights in managed.items():
				rules = [p for p in custom if p.role == role]
				self.assertEqual(len(rules), 1, (doctype, role))
				granted = {r for r in RIGHTS[2:] if rules[0].get(r)}
				self.assertEqual(granted, set(rights), (doctype, role))

	def test_permission_drift_is_reported_not_fixed(self):
		self.assertEqual(check_standard_permission_drift(), [])
		title = "mobilesales: standard permissions changed for Customer, review Custom DocPerm"
		# Error Log is MyISAM (survives rollback by design): remove what this test writes.
		since = now_datetime()
		self.addCleanup(
			lambda: frappe.db.delete("Error Log", {"method": title, "creation": [">=", since]})
		)

		rule = frappe.get_all(
			"Custom DocPerm", filters={"parent": "Customer", "role": ["!=", AGENT_ROLE]}, fields=["name", "role", "write"], limit=1
		)[0]
		frappe.db.set_value("Custom DocPerm", rule.name, "write", 0 if rule.write else 1)
		self.assertEqual(check_standard_permission_drift(), ["Customer"])
		log = frappe.get_last_doc("Error Log", filters={"method": title})
		self.assertIn(rule.role, log.error)
		self.assertEqual(frappe.db.get_value("Custom DocPerm", rule.name, "write"), 0 if rule.write else 1)

	# 13
	def test_standard_invoice_keeps_default_series(self):
		options = frappe.get_meta("Sales Invoice").get_naming_series_options()
		standard_options = frappe.db.get_value("DocField", {"parent": "Sales Invoice", "fieldname": "naming_series"}, "options").split("\n")
		self.assertEqual(options[: len(standard_options)], standard_options)
		self.assertIn("MB-SINV-.YY.-.#####", options)
		with as_user(self.users.office):
			si = self.standard_invoice(100)
		self.assertEqual(si.naming_series, standard_options[0])
		self.assertFalse(si.is_mobile_sale)

	# Collections of previous invoices by the agent (pilot finding, fix option 1)

	def test_agent_collects_standard_invoice_but_cannot_read_it_otherwise(self):
		standard = self.standard_invoice(300)  # test data: an office invoice, not from any trip
		visit = self.visit("Collection Only", collect_previous=[{"sales_invoice": standard.name, "allocated": 120}])
		pe = frappe.get_doc("Payment Entry", visit.payment_entry)
		self.assertEqual((pe.owner, [(r.reference_name, r.allocated_amount) for r in pe.references]), (self.agent_a.user, [(standard.name, 120)]))
		self.assertEqual(frappe.db.get_value("Sales Invoice", standard.name, "outstanding_amount"), 180)
		self.assertFalse(frappe.flags.get(permissions.COLLECTABLE_FLAG))

		with as_user(self.agent_a.user):
			self.assertEqual(frappe.get_list("Sales Invoice", filters={"name": standard.name}, pluck="name"), [])
			self.assertFalse(frappe.has_permission("Sales Invoice", "read", doc=standard.name))
			with self.assertRaises(frappe.PermissionError):
				frappe.get_doc("Sales Invoice", standard.name).check_permission("read")
			from frappe.desk.search import search_widget

			found = search_widget("Sales Invoice", txt=standard.name, as_dict=False) or []
			self.assertNotIn(standard.name, [row[0] for row in found])

	def test_collection_of_other_customers_invoice_rejected(self):
		foreign = frappe.get_doc(
			{"doctype": "Sales Invoice", "company": self.company, "customer": self.other_customer(),
			 "items": [{"item_code": self.plain_item, "qty": 1, "rate": 100, "warehouse": self.store}]}
		).insert()  # fmt: skip
		foreign.submit()
		with self.assertRaisesRegex(frappe.ValidationError, "does not belong to customer"):
			self.visit("Collection Only", collect_previous=[{"sales_invoice": foreign.name, "allocated": 10}], submit=False)

	def test_previous_outstanding_picker(self):
		first, second = self.standard_invoice(100), self.standard_invoice(200)
		paid = self.standard_invoice(50)
		self.visit("Collection Only", collect_previous=[{"sales_invoice": paid.name, "allocated": 50}])
		foreign = frappe.get_doc(
			{"doctype": "Sales Invoice", "company": self.company, "customer": self.other_customer(),
			 "items": [{"item_code": self.plain_item, "qty": 1, "rate": 70, "warehouse": self.store}]}
		).insert()  # fmt: skip
		foreign.submit()

		with as_user(self.agent_a.user):
			rows = mobile_api.outstanding_invoice_query(
				"Sales Invoice", "", "name", 0, 50, {"customer": self.customer, "company": self.company}
			)
			self.assertEqual({row[0] for row in rows}, {first.name, second.name})
			self.assertEqual(mobile_api.outstanding_invoice_query("Sales Invoice", "", "name", 0, 50, {}), [])

	def test_sale_and_previous_collection_in_one_visit(self):
		standard = self.standard_invoice(200)
		visit = self.visit(
			items=[{"item_code": self.plain_item, "qty": 1}],
			collect_previous=[{"sales_invoice": standard.name, "allocated": 80}],
		)
		pe = frappe.get_doc("Payment Entry", visit.payment_entry)
		self.assertEqual(visit.total_collected, visit.rounded_total + 80)
		self.assertEqual(
			{(r.reference_name, r.allocated_amount) for r in pe.references},
			{(visit.sales_invoice, visit.rounded_total), (standard.name, 80)},
		)
		self.assertEqual(frappe.db.get_value("Sales Invoice", standard.name, "outstanding_amount"), 120)

	def test_agent_deletes_only_own_draft_visits(self):
		own_draft = self.visit("No Sale", no_sale_reason=self.reason, submit=False)
		trip_b = self.start_trip(self.agent_b)
		other_draft = self.visit("No Sale", no_sale_reason=self.reason, trip=trip_b, submit=False)
		own_submitted = self.visit("No Sale", no_sale_reason=self.reason)
		own_cancelled = self.visit("No Sale", no_sale_reason=self.reason)
		with as_user(self.users.supervisor):
			frappe.get_doc("Customer Visit", own_cancelled.name).cancel()

		with as_user(self.agent_a.user):
			frappe.delete_doc("Customer Visit", own_draft.name)
			for name in (other_draft.name, own_submitted.name, own_cancelled.name):
				with self.assertRaises(frappe.PermissionError, msg=name):
					frappe.delete_doc("Customer Visit", name)
		self.assertFalse(frappe.db.exists("Customer Visit", own_draft.name))
		self.assertTrue(all(frappe.db.exists("Customer Visit", n) for n in (other_draft.name, own_submitted.name, own_cancelled.name)))
