# Copyright (c) 2026, Evonet and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class MobileRoute(Document):
	def validate(self):
		seen = set()
		for row in self.customers:
			if row.customer in seen:
				frappe.throw(
					_("Row {0}: Customer {1} is already on this route.").format(
						row.idx, frappe.bold(row.customer)
					)
				)
			seen.add(row.customer)
			if not row.sequence:
				row.sequence = row.idx
