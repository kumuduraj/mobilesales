// Copyright (c) 2026, Evonet and contributors
// For license information, please see license.txt

frappe.ui.form.on("Mobile Sales Settings", {
	setup(frm) {
		const by_company = (extra) => () => ({
			filters: Object.assign({ company: frm.doc.company }, extra),
		});

		frm.set_query("source_warehouse", by_company({ is_group: 0 }));
		frm.set_query("return_warehouse", by_company({ is_group: 0 }));
		frm.set_query("damage_warehouse", by_company({ is_group: 0 }));
		frm.set_query("van_warehouse_group", by_company({ is_group: 1 }));
		frm.set_query("agent_cash_parent_account", by_company({ is_group: 1, account_type: "Cash" }));
		frm.set_query("main_cash_account", by_company({ is_group: 0, account_type: "Cash" }));
		frm.set_query("stock_shortage_account", by_company({ is_group: 0, root_type: "Expense" }));
		frm.set_query("cash_shortage_account", by_company({ is_group: 0, root_type: "Expense" }));
		frm.set_query("default_tax_template", by_company({ disabled: 0 }));
		frm.set_query("sales_person_parent", () => ({ filters: { is_group: 1 } }));
		frm.set_query("selling_price_list", () => ({ filters: { selling: 1, enabled: 1 } }));
	},
});
