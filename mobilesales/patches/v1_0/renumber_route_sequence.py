"""v1.0.2: number every route's customers 1, 2, 3… in Sequence order (ties in row order, empty last), the
order Mobile Route now keeps on every save. Idempotent: rows already numbered that way are not touched."""

import frappe

from mobilesales.mobile_sales.doctype.mobile_route.mobile_route import sequence_order


def execute():
	for route in frappe.get_all("Mobile Route", pluck="name"):
		rows = frappe.get_all(
			"Mobile Route Customer",
			filters={"parent": route, "parenttype": "Mobile Route", "parentfield": "customers"},
			fields=["name", "idx", "sequence"],
		)
		for position, row in enumerate(sequence_order(rows), start=1):
			if (row.idx, row.sequence) != (position, position):
				frappe.db.set_value("Mobile Route Customer", row.name, {"idx": position, "sequence": position}, update_modified=False)
