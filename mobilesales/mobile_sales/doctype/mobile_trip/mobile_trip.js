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
		if (frm.doc.status === "Settling" && (is_agent || is_supervisor)) {
			frm.add_custom_button(__("Reopen Trip"), () =>
				frappe.confirm(
					__("Reopen this trip (back to In Field)? A draft settlement is deleted."),
					() => run_action(frm, "reopen_trip")
				)
			);
		}
		if (["Loaded", "In Field"].includes(frm.doc.status) && can_top_up) {
			frm.add_custom_button(__("Top-up Load"), () => show_top_up_dialog(frm));
		}
		frm.add_custom_button(__("Van Stock"), () => show_van_stock(frm));
		const can_settle =
			is_agent || is_supervisor || frappe.user.has_role("Mobile Sales Store Keeper");
		if (frm.doc.status === "Settling" && can_settle) {
			frm.add_custom_button(__("Create Settlement"), () =>
				frappe.call({
					method: "mobilesales.services.settlement.make_settlement",
					args: { trip: frm.doc.name },
					freeze: true,
					callback(r) {
						if (r.message) frappe.set_route("Form", "Mobile Settlement", r.message);
					},
				})
			);
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

frappe.ui.form.on("Mobile Trip Load Item", {
	item_code(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.item_code) return;
		frappe.db.get_value("Item", row.item_code, "stock_uom").then((r) => {
			const stock_uom = r.message && r.message.stock_uom;
			if (!stock_uom) return;
			frappe.model.set_value(cdt, cdn, { uom: stock_uom, conversion_factor: 1 });
		});
	},
	uom(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.item_code || !row.uom) return;
		frappe.call({
			method: "erpnext.stock.get_item_details.get_conversion_factor",
			args: { item_code: row.item_code, uom: row.uom },
			callback(r) {
				if (r.message) frappe.model.set_value(cdt, cdn, "conversion_factor", r.message.conversion_factor);
			},
		});
	},
	conversion_factor(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		frappe.model.set_value(cdt, cdn, "stock_qty", flt(row.qty) * flt(row.conversion_factor));
	},
	qty(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		frappe.model.set_value(cdt, cdn, "stock_qty", flt(row.qty) * flt(row.conversion_factor));
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

function show_van_stock(frm) {
	frappe.call({
		method: "mobilesales.api.mobile.get_van_stock",
		args: { trip: frm.doc.name },
		callback(r) {
			const rows = r.message || [];
			const esc = frappe.utils.escape_html;
			const body = rows.length
				? rows
						.map((row) => {
							const batches = (row.batches || [])
								.map((b) => `${esc(b.batch_no)}: ${format_number(b.qty)}`)
								.join("<br>");
							return `<tr>
								<td>${esc(row.item_code)}<br><small class="text-muted">${esc(row.item_name || "")}</small></td>
								<td class="text-right">${format_number(row.actual_qty)} ${esc(row.stock_uom)}</td>
								<td>${batches}</td>
							</tr>`;
						})
						.join("")
				: `<tr><td colspan="3" class="text-muted">${__("Van is empty")}</td></tr>`;
			frappe.msgprint({
				title: __("Van Stock: {0}", [frm.doc.van_warehouse]),
				wide: true,
				message: `<table class="table table-bordered">
					<thead><tr><th>${__("Item")}</th><th class="text-right">${__("Qty")}</th><th>${__("Batches")}</th></tr></thead>
					<tbody>${body}</tbody>
				</table>`,
			});
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
						onchange: function () {
							const item_code = this.get_value();
							const uom_field = this.grid_row.on_grid_fields_dict.uom;
							if (!item_code || !uom_field) return;
							frappe.db.get_value("Item", item_code, "stock_uom").then((r) => {
								if (r.message && r.message.stock_uom) uom_field.set_value(r.message.stock_uom);
							});
						},
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
