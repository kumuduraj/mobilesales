# Copyright (c) 2026, Evonet and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from mobilesales.services import day_report
from mobilesales.services import settlement as settlement_service


class MobileSettlement(Document):
	def validate(self):
		settlement_service.validate(self)

	def before_submit(self):
		settlement_service.before_submit(self)

	def on_submit(self):
		settlement_service.post_settlement(self)
		day_report.queue_attach(self)

	def before_cancel(self):
		settlement_service.before_cancel(self)

	def on_cancel(self):
		settlement_service.reverse_settlement(self)
