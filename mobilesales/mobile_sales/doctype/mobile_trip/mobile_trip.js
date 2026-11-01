// Copyright (c) 2026, Evonet and contributors
// For license information, please see license.txt

const TRIP_METHOD = "mobilesales.services.trip.";

frappe.ui.form.on("Mobile Trip", {
	setup(frm) {
		frm.set_query("agent", () => ({ filters: { is_active: 1 } }));
		frm.set_query("source_warehouse", () => ({
			filters: { company: frm.doc.company, is_group: 0 },
		}));
		frm.set_query("item_code", "load_items", () => ({
			filters: { is_stock_item: 1, disabled: 0 },
		}));
	},

	refresh(frm) {
		frm.trigger("set_status_indicator");
		if (frm.doc.docstatus !== 1) return;

		const is_agent = frm.doc.agent_user === frappe.session.user;
		const is_supervisor =
			frappe.user.has_role("Mobile Sales Supervisor") || frappe.user.has_role("System Manager");
		const can_top_up = is_supervisor || frappe.user.has_role("Mobile Sales Store Keeper");

		if (frm.doc.status === "Loaded" && (is_agent || is_supervisor)) {
			frm.add_custom_button(__("Start Trip"), () => run_action(frm, "start_trip"));
		}
		if (frm.doc.status === "In Field" && (is_agent || is_supervisor)) {
			frm.add_custom_button(__("End Day"), () =>
				frappe.confirm(__("End the day and move this trip to Settling?"), () =>
					run_action(frm, "end_day")
				)
			);
		}
		if (["Loaded", "In Field"].includes(frm.doc.status) && can_top_up) {
			frm.add_custom_button(__("Top-up Load"), () => show_top_up_dialog(frm));
		}
	},

	set_status_indicator(frm) {
		const colors = {
			Draft: "gray",
			Loaded: "blue",
			"In Field": "orange",
			Settling: "yellow",
			Settled: "green",
			Cancelled: "red",
		};
		if (frm.doc.status && frm.doc.docstatus > 0) {
			frm.page.set_indicator(__(frm.doc.status), colors[frm.doc.status] || "gray");
		}
	},
});

function run_action(frm, method, args = {}) {
	return frappe.call({
		method: TRIP_METHOD + method,
		args: Object.assign({ trip: frm.doc.name }, args),
		freeze: true,
		callback(r) {
			if (!r.exc) frm.reload_doc();
		},
	});
}

function show_top_up_dialog(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Top-up Load"),
		size: "large",
		fields: [
			{
				fieldname: "items",
				fieldtype: "Table",
				label: __("Items"),
				cannot_add_rows: false,
				in_place_edit: true,
				reqd: 1,
				data: [],
				fields: [
					{
						fieldname: "item_code",
						fieldtype: "Link",
						options: "Item",
						label: __("Item"),
						in_list_view: 1,
						reqd: 1,
						get_query: () => ({ filters: { is_stock_item: 1, disabled: 0 } }),
					},
					{
						fieldname: "uom",
						fieldtype: "Link",
						options: "UOM",
						label: __("UOM"),
						in_list_view: 1,
					},
					{
						fieldname: "qty",
						fieldtype: "Float",
						label: __("Qty"),
						in_list_view: 1,
						reqd: 1,
					},
				],
			},
		],
		primary_action_label: __("Create Top-up"),
		primary_action(values) {
			const items = (values.items || []).filter((row) => row.item_code && row.qty);
			if (!items.length) {
				frappe.msgprint(__("Add at least one item."));
				return;
			}
			run_action(frm, "top_up", { items }).then((r) => {
				if (!r.exc) dialog.hide();
			});
		},
	});
	dialog.show();
}
