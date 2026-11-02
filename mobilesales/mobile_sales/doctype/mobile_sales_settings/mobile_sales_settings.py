# Copyright (c) 2026, Evonet and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from mobilesales.overrides.guards import clear_guard_cache
from mobilesales.services import vehicles

WAREHOUSE_FIELDS = (
	"source_warehouse",
	"return_warehouse",
	"damage_warehouse",
	"van_warehouse_group",
	"customer_return_warehouse",
)
ACCOUNT_FIELDS = (
	"agent_cash_parent_account",
	"main_cash_account",
	"stock_shortage_account",
	"cash_shortage_account",
	"employee_recovery_account",
)
EXPENSE_ACCOUNT_FIELDS = ("stock_shortage_account", "cash_shortage_account")
BATCH_PICK_METHODS = ("FIFO", "Expiry")


class MobileSalesSettings(Document):
	def validate(self):
		if self.source_warehouse and not self.return_warehouse:
			self.return_warehouse = self.source_warehouse

		self.validate_company_links()
		self.validate_warehouses()
		self.validate_accounts()
		self.validate_sales_person_parent()
		self.validate_price_list()
		self.validate_customer_defaults()
		self.validate_naming_series()
		self.warn_stock_settings()

	def validate_naming_series(self):
		options = frappe.get_meta("Sales Invoice").get_naming_series_options()
		for series in (self.sinv_naming_series, self.sret_naming_series):
			if series and series not in options:
				frappe.throw(
					_("Naming series {0} is not an option on Sales Invoice. Run migrate or add it first.").format(
						frappe.bold(series)
					)
				)

	def on_update(self):
		clear_guard_cache()

	def validate_company_links(self):
		linked = [
			f
			for f in (*WAREHOUSE_FIELDS, *ACCOUNT_FIELDS, "default_tax_template")
			if self.get(f)
		]
		if linked and not self.company:
			frappe.throw(_("Set Company before warehouses, accounts or tax template."))

		for fieldname in WAREHOUSE_FIELDS:
			self._check_company("Warehouse", fieldname)
		for fieldname in ACCOUNT_FIELDS:
			self._check_company("Account", fieldname)
		self._check_company("Sales Taxes and Charges Template", "default_tax_template")

	def _check_company(self, doctype, fieldname):
		value = self.get(fieldname)
		if value and frappe.db.get_value(doctype, value, "company") != self.company:
			frappe.throw(
				_("{0} {1} does not belong to company {2}.").format(
					_(self.meta.get_label(fieldname)), frappe.bold(value), frappe.bold(self.company)
				)
			)

	def validate_warehouses(self):
		if self.van_warehouse_group:
			self.validate_van_warehouse_group()

		if self.returns_enabled and not self.customer_return_warehouse:
			frappe.throw(_("Set Customer Return Warehouse to enable returns."))
		if self.customer_return_warehouse and self.customer_return_warehouse in (
			self.source_warehouse,
			self.return_warehouse,
			self.damage_warehouse,
		):
			frappe.throw(
				_("Customer Return Warehouse {0} must be its own warehouse (not the source, return or damage one).").format(
					frappe.bold(self.customer_return_warehouse)
				)
			)
		for fieldname in ("source_warehouse", "return_warehouse", "damage_warehouse", "customer_return_warehouse"):
			value = self.get(fieldname)
			if value and frappe.db.get_value("Warehouse", value, "is_group"):
				frappe.throw(
					_("{0} {1} must not be a group warehouse.").format(
						_(self.meta.get_label(fieldname)), frappe.bold(value)
					)
				)

	def validate_van_warehouse_group(self):
		"""Everything under the van group is guarded, so the group must not swallow real stores."""
		group = frappe.db.get_value(
			"Warehouse", self.van_warehouse_group, ["is_group", "parent_warehouse", "lft", "rgt"], as_dict=True
		)
		bold_group = frappe.bold(self.van_warehouse_group)
		if not group.is_group:
			frappe.throw(_("Van Warehouse Group {0} must be a group warehouse.").format(bold_group))
		if not group.parent_warehouse:
			frappe.throw(
				_("Van Warehouse Group {0} is a root warehouse. Create a dedicated group under it.").format(
					bold_group
				)
			)

		for fieldname in ("source_warehouse", "return_warehouse", "damage_warehouse", "customer_return_warehouse"):
			value = self.get(fieldname)
			if not value:
				continue
			lft, rgt = frappe.db.get_value("Warehouse", value, ["lft", "rgt"])
			if group.lft <= lft and rgt <= group.rgt:
				frappe.throw(
					_("{0} {1} must not be inside Van Warehouse Group {2}.").format(
						_(self.meta.get_label(fieldname)), frappe.bold(value), bold_group
					)
				)

		agent_vans = vehicles.vehicle_vans()
		warehouse = frappe.qb.DocType("Warehouse")
		bin = frappe.qb.DocType("Bin")
		query = (
			frappe.qb.from_(bin)
			.join(warehouse)
			.on(bin.warehouse == warehouse.name)
			.select(bin.warehouse)
			.distinct()
			.where((warehouse.lft > group.lft) & (warehouse.rgt < group.rgt) & (bin.actual_qty != 0))
		)
		if agent_vans:
			query = query.where(bin.warehouse.notin(agent_vans))
		stocked = query.run(pluck=True)
		if stocked:
			frappe.throw(
				_(
					"Van Warehouse Group {0} contains warehouses with stock that are not agent vans: {1}. "
					"Move them out of the group or empty them first."
				).format(bold_group, ", ".join(frappe.bold(w) for w in stocked))
			)

	def validate_accounts(self):
		if self.agent_cash_parent_account:
			is_group, account_type = frappe.db.get_value(
				"Account", self.agent_cash_parent_account, ["is_group", "account_type"]
			)
			if not is_group or account_type != "Cash":
				frappe.throw(
					_("Agent Cash Parent Account {0} must be a group account of type Cash.").format(
						frappe.bold(self.agent_cash_parent_account)
					)
				)

		if self.main_cash_account:
			is_group, account_type = frappe.db.get_value(
				"Account", self.main_cash_account, ["is_group", "account_type"]
			)
			if is_group or account_type != "Cash":
				frappe.throw(
					_("Main Cash Account {0} must be a ledger (not group) of type Cash.").format(
						frappe.bold(self.main_cash_account)
					)
				)

		for fieldname in EXPENSE_ACCOUNT_FIELDS:
			value = self.get(fieldname)
			if not value:
				continue
			is_group, root_type = frappe.db.get_value("Account", value, ["is_group", "root_type"])
			if is_group or root_type != "Expense":
				frappe.throw(
					_("{0} {1} must be an Expense ledger (not group).").format(
						_(self.meta.get_label(fieldname)), frappe.bold(value)
					)
				)

		if self.employee_recovery_account:
			is_group, account_type = frappe.db.get_value(
				"Account", self.employee_recovery_account, ["is_group", "account_type"]
			)
			if is_group or account_type not in ("Receivable", "Payable"):
				frappe.throw(
					_("Employee Recovery Account {0} must be a Receivable or Payable ledger.").format(
						frappe.bold(self.employee_recovery_account)
					)
				)

	def validate_sales_person_parent(self):
		if self.sales_person_parent and not frappe.db.get_value(
			"Sales Person", self.sales_person_parent, "is_group"
		):
			frappe.throw(
				_("Sales Person Parent {0} must be a group Sales Person.").format(
					frappe.bold(self.sales_person_parent)
				)
			)

	def validate_customer_defaults(self):
		for doctype, fieldname in (("Customer Group", "default_customer_group"), ("Territory", "default_territory")):
			value = self.get(fieldname)
			if value and frappe.db.get_value(doctype, value, "is_group"):
				frappe.throw(
					_("{0} {1} must not be a group.").format(_(self.meta.get_label(fieldname)), frappe.bold(value))
				)

	def validate_price_list(self):
		if self.selling_price_list and not frappe.db.get_value(
			"Price List", self.selling_price_list, "selling"
		):
			frappe.throw(
				_("Price List {0} is not a selling price list.").format(frappe.bold(self.selling_price_list))
			)

	def warn_stock_settings(self):
		"""Spec §5.6: batches rely on automatic outward bundles. Warn only, never block."""
		auto_bundle, pick_method = frappe.db.get_value(
			"Stock Settings",
			None,
			["auto_create_serial_and_batch_bundle_for_outward", "pick_serial_and_batch_based_on"],
		)
		if not int(auto_bundle or 0) or pick_method not in BATCH_PICK_METHODS:
			frappe.msgprint(
				_(
					"Stock Settings should have 'Auto Create Serial and Batch Bundle For Outward' enabled "
					"and pick batches by FIFO (or Expiry). Batch-tracked mobile sales may fail otherwise."
				),
				title=_("Check Stock Settings"),
				indicator="orange",
			)
