# Copyright (c) 2026, Evonet and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from mobilesales.overrides.guards import clear_guard_cache


class MobileVehicle(Document):
	def validate(self):
		self.vehicle_no = (self.vehicle_no or "").strip()
		if self.van_warehouse:
			other = frappe.db.get_value(
				"Mobile Vehicle", {"van_warehouse": self.van_warehouse, "name": ["!=", self.name]}, "name"
			)
			if other:
				frappe.throw(
					_("Van warehouse {0} already belongs to vehicle {1}.").format(
						frappe.bold(self.van_warehouse), frappe.bold(other)
					)
				)

	def on_update(self):
		clear_guard_cache()

	def on_trash(self):
		clear_guard_cache()
