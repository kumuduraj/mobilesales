// Copyright (c) 2026, Evonet and contributors
// For license information, please see license.txt

frappe.ui.form.on("Mobile Settlement", {
	setup(frm) {
		frm.set_query("mobile_trip", () => ({ filters: { status: "Settling", docstatus: 1 } }));
		frm.set_query("damaged_batch_no", "stock_lines", (doc, cdt, cdn) => ({
			filters: { item: locals[cdt][cdn].item_code },
		}));
	},

	refresh(frm) {
		if (frm.doc.docstatus === 0 && !frm.is_new()) {
			frm.add_custom_button(__("Refresh"), () => frm.save());
		}
	},
});

frappe.ui.form.on("Mobile Cash Denomination", {
	count(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		frappe.model.set_value(cdt, cdn, "amount", flt(row.denomination) * cint(row.count));
		const total = (frm.doc.denominations || []).reduce((sum, d) => sum + flt(d.amount), 0);
		if ((frm.doc.denominations || []).some((d) => cint(d.count) > 0)) {
			frm.set_value("cash_handed_over", total);
		}
	},
});
