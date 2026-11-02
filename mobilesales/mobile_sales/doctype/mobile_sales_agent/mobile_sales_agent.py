# Copyright (c) 2026, Evonet and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from mobilesales.overrides.guards import clear_guard_cache
from mobilesales.services import settings as ms_settings


class MobileSalesAgent(Document):
	def validate(self):
		self.validate_unique_user()
		if not self.selling_price_list:
			self.selling_price_list = ms_settings.get_settings().selling_price_list

		if not 0 <= flt(self.max_discount_pct) <= 100:
			frappe.throw(_("Max Discount % must be between 0 and 100."))
		if flt(self.credit_limit_per_invoice) < 0:
			frappe.throw(_("Credit Limit per Invoice cannot be negative."))
		if flt(self.max_return_value_per_visit) < 0:
			frappe.throw(_("Max Return Value per Visit cannot be negative."))

	def on_update(self):
		clear_guard_cache()

	def on_trash(self):
		clear_guard_cache()

	def validate_unique_user(self):
		other = frappe.db.get_value(
			"Mobile Sales Agent", {"user": self.user, "name": ["!=", self.name]}, "name"
		)
		if other:
			frappe.throw(
				_("User {0} is already linked to Mobile Sales Agent {1}.").format(
					frappe.bold(self.user), frappe.bold(other)
				)
			)
