// Copyright (c) 2026, Evonet and contributors
// For license information, please see license.txt

frappe.ui.form.on("Mobile Sales Agent", {
	setup(frm) {
		frm.set_query("selling_price_list", () => ({ filters: { selling: 1, enabled: 1 } }));
		frm.set_query("sales_person", () => ({ filters: { is_group: 0, enabled: 1 } }));
		frm.set_query("default_vehicle", () => ({ filters: { is_active: 1 } }));
	},

	refresh(frm) {
		const can_setup =
			frappe.user.has_role("Mobile Sales Supervisor") || frappe.user.has_role("System Manager");
		if (frm.is_new() || !can_setup) return;

		frm.add_custom_button(__("Create Cash Account"), () => {
			frappe.call({
				method: "mobilesales.services.agent_setup.setup_agent",
				args: { agent: frm.doc.name },
				freeze: true,
				freeze_message: __("Setting up agent..."),
				callback(r) {
					if (r.exc) return;
					frm.reload_doc();
					frappe.show_alert({ message: __("Agent setup complete"), indicator: "green" });
				},
			});
		});
	},
});
