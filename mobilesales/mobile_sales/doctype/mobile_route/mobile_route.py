# Copyright (c) 2026, Evonet and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


def sequence_order(rows) -> list:
	"""One order everywhere (Desk table, phone, reports): by Sequence, ties in row order, rows without a
	sequence at the end."""
	return sorted(rows, key=lambda r: (0 if cint(r.sequence) > 0 else 1, cint(r.sequence), cint(r.idx)))


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
		self.renumber()

	def renumber(self):
		"""Sort by Sequence and number the rows 1, 2, 3… (a drag in Desk renumbers by row order first)."""
		ordered = sequence_order(self.customers)
		for position, row in enumerate(ordered, start=1):
			row.idx = position
			row.sequence = position
		self.customers = ordered
