"""v0.6.0 (spec §3.6): the van belongs to a Mobile Vehicle. For every agent with a (legacy) van warehouse,
create Mobile Vehicle VAN-01, VAN-02, … on that same warehouse (no stock or warehouse moved; active only if
the agent is), set it as the agent's default vehicle and on the agent's historic trips. Agent.van_warehouse
stays as data.

Refuses to run while any Mobile Trip is open: an open trip would change vans mid-trip. Idempotent: a
warehouse already linked to a vehicle is not linked again."""

import frappe
from frappe.utils import cint

CLOSED_STATUSES = ("Settled", "Cancelled")


def execute():
	open_trips = frappe.get_all(
		"Mobile Trip",
		filters={"docstatus": ["<", 2], "status": ["not in", CLOSED_STATUSES]},
		fields=["name", "status"],
		order_by="name asc",
	)
	if open_trips:
		frappe.throw(
			"mobilesales v0.6.0 vehicle patch: settle or cancel every Mobile Trip first. Open: "
			+ ", ".join(f"{t.name} ({t.status})" for t in open_trips)
		)

	for agent in frappe.get_all(
		"Mobile Sales Agent",
		filters={"van_warehouse": ["is", "set"]},
		fields=["name", "agent_name", "is_active", "van_warehouse", "default_vehicle"],
		order_by="name asc",
	):
		vehicle = frappe.db.get_value("Mobile Vehicle", {"van_warehouse": agent.van_warehouse}, "name")
		if not vehicle:
			vehicle = frappe.get_doc(
				{
					"doctype": "Mobile Vehicle",
					"vehicle_no": next_vehicle_no(),
					"description": f"Van of {agent.agent_name} (before v0.6.0)",
					"van_warehouse": agent.van_warehouse,
					"is_active": cint(agent.is_active),
				}
			).insert(ignore_permissions=True).name
		if not agent.default_vehicle:
			frappe.db.set_value("Mobile Sales Agent", agent.name, "default_vehicle", vehicle, update_modified=False)
		frappe.db.sql(
			"""update `tabMobile Trip` set vehicle = %s
			where agent = %s and van_warehouse = %s and (vehicle is null or vehicle = '')""",
			(vehicle, agent.name, agent.van_warehouse),
		)


def next_vehicle_no() -> str:
	used = {
		cint(name[4:])
		for name in frappe.get_all("Mobile Vehicle", filters={"name": ["like", "VAN-%"]}, pluck="name")
		if name[4:].isdigit()
	}
	number = 1
	while number in used:
		number += 1
	return f"VAN-{number:02d}"
