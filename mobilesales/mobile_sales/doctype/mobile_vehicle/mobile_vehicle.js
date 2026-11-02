// Copyright (c) 2026, Evonet and contributors
// For license information, please see license.txt

frappe.ui.form.on("Mobile Vehicle", {
	refresh(frm) {
		const can_setup =
			frappe.user.has_role("Mobile Sales Supervisor") || frappe.user.has_role("System Manager");
		if (frm.is_new() || !can_setup || frm.doc.van_warehouse) return;

		frm.add_custom_button(__("Create Van Warehouse"), () => {
			frappe.call({
				method: "mobilesales.services.vehicles.setup_vehicle",
				args: { vehicle: frm.doc.name },
				freeze: true,
				callback(r) {
					if (r.exc) return;
					frm.reload_doc();
					frappe.show_alert({ message: __("Van warehouse {0} created", [r.message]), indicator: "green" });
				},
			});
		});
	},
});
