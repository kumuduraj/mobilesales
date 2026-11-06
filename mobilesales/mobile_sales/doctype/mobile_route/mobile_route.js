// Copyright (c) 2026, Evonet and contributors
// For license information, please see license.txt

frappe.ui.form.on("Mobile Route", {
	setup(frm) {
		// name, customer name and "<address line 1>, <city> · …<last 4 of mobile>" in the link search
		frm.set_query("customer", "customers", () => ({ query: "mobilesales.services.customers.customer_query" }));
	},
});

frappe.ui.form.on("Mobile Route Customer", {
	// a drag in the table is the new order: Sequence follows the rows (the server keeps it 1, 2, 3… on save)
	customers_move(frm) {
		(frm.doc.customers || []).forEach((row) => (row.sequence = row.idx));
		frm.refresh_field("customers");
	},
});
