"""Customer Visit.off_route (v0.5.0) for visits recorded before the field existed. Idempotent."""

import frappe


def execute():
	frappe.db.sql(
		"""update `tabCustomer Visit` v
		join `tabMobile Trip` t on t.name = v.mobile_trip
		set v.off_route = if(
			exists(select 1 from `tabMobile Route Customer` rc
				where rc.parenttype = 'Mobile Route' and rc.parent = t.route and rc.customer = v.customer),
			0, 1)"""
	)
