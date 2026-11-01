# Copyright (c) 2026, Evonet and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from mobilesales.services import trip as trip_service


class MobileTrip(Document):
	def validate(self):
		trip_service.validate_trip(self)

	def before_submit(self):
		trip_service.before_submit(self)

	def on_submit(self):
		trip_service.on_submit(self)

	def before_cancel(self):
		trip_service.before_cancel(self)

	def on_cancel(self):
		trip_service.on_cancel(self)
