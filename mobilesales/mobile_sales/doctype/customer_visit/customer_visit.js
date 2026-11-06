// Copyright (c) 2026, Evonet and contributors
// For license information, please see license.txt

const CUSTOMER_UPDATE_METHOD = "mobilesales.services.customer_update.";

frappe.ui.form.on("Customer Visit", {
	setup(frm) {
		frm.set_query("mobile_trip", () => ({ filters: { status: "In Field", docstatus: 1 } }));
		// name, customer name and "<address line 1>, <city> · …<last 4 of mobile>" in the link search
		frm.set_query("customer", () => ({ query: "mobilesales.services.customers.customer_query" }));
		frm.set_query("item_code", "sale_items", () => ({ filters: { is_sales_item: 1, disabled: 0 } }));
		frm.set_query("sales_invoice", "collect_previous", () => ({
			query: "mobilesales.api.mobile.outstanding_invoice_query",
			filters: { customer: frm.doc.customer, company: frm.doc.company },
		}));
		frm.set_query("item_code", "return_items", () => ({ filters: { is_stock_item: 1, disabled: 0 } }));
		frm.set_query("against_invoice", "return_items", (doc, cdt, cdn) => ({
			query: "mobilesales.api.mobile.return_invoice_query",
			filters: { customer: frm.doc.customer, company: frm.doc.company, item_code: locals[cdt][cdn].item_code },
		}));
	},

	// enter one discount, the other is computed on save
	additional_discount_percentage(frm) {
		if (frm.doc.additional_discount_percentage) frm.set_value("discount_amount", 0);
	},
	discount_amount(frm) {
		if (frm.doc.discount_amount) frm.set_value("additional_discount_percentage", 0);
	},

	refresh(frm) {
		const is_supervisor =
			frappe.user.has_role("Mobile Sales Supervisor") || frappe.user.has_role("System Manager");
		if (frm.doc.docstatus === 1 && frm.doc.customer_update_status === "Pending Approval" && is_supervisor) {
			frm.add_custom_button(
				__("Approve Customer Update"),
				() => call_update(frm, "approve_customer_update"),
				__("Customer Update")
			);
			frm.add_custom_button(
				__("Reject Customer Update"),
				() => call_update(frm, "reject_customer_update"),
				__("Customer Update")
			);
		}
		if (frm.doc.docstatus === 0 && !frm.doc.latitude && navigator.geolocation) {
			frm.add_custom_button(__("Capture Location"), () => capture_location(frm));
		}
	},
});

frappe.ui.form.on("Customer Visit Item", {
	discount_percentage(frm, cdt, cdn) {
		if (locals[cdt][cdn].discount_percentage) frappe.model.set_value(cdt, cdn, "discount_amount", 0);
	},
	discount_amount(frm, cdt, cdn) {
		if (locals[cdt][cdn].discount_amount) frappe.model.set_value(cdt, cdn, "discount_percentage", 0);
	},
});

function call_update(frm, method) {
	frappe.call({
		method: CUSTOMER_UPDATE_METHOD + method,
		args: { visit: frm.doc.name },
		freeze: true,
		callback(r) {
			if (!r.exc) frm.reload_doc();
		},
	});
}

function capture_location(frm) {
	navigator.geolocation.getCurrentPosition(
		(pos) => {
			frm.set_value("latitude", pos.coords.latitude);
			frm.set_value("longitude", pos.coords.longitude);
		},
		(err) => frappe.msgprint(__("Could not read location: {0}", [err.message])),
		{ enableHighAccuracy: true, timeout: 15000 }
	);
}
