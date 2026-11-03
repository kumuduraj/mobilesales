# Copyright (c) 2026, Evonet and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from mobilesales.services import visit as visit_service
from mobilesales.services import vouchers


class CustomerVisit(Document):
	def validate(self):
		visit_service.validate_visit(self)

	def on_submit(self):
		visit_service.on_submit(self)

	def before_update_after_submit(self):
		vouchers.keep_system_fields(self, visit_service.VOUCHER_LINKS)

	def before_cancel(self):
		visit_service.before_cancel(self)

	def on_cancel(self):
		visit_service.on_cancel(self)
