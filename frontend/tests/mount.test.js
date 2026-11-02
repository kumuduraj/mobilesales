// SPA mount test (CLAUDE.md rule 18): the real App + router mounted with a realistic window.ms_boot, every
// route rendered once per scenario. Any app/router error, unhandled rejection or Vue warning fails the build.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { createMemoryHistory } from "vue-router"
import { createMobileApp, routes } from "../src/app"

const AGENT = {
	name: "MSA-0001",
	agent_name: "Van Agent 1",
	is_active: 1,
	van_warehouse: "Van Agent 1 Van - ARL",
	mode_of_payment: "Mobile Cash - Van Agent 1",
	selling_price_list: "Standard Selling",
	default_route: "Pilot Route 1",
	max_discount_pct: 0,
	credit_limit_per_invoice: 0,
}
const trip = (status) => ({
	name: "MTRIP-26-00003",
	status,
	trip_date: "2026-11-01",
	route: "Pilot Route 1",
	van_warehouse: AGENT.van_warehouse,
	docstatus: 1,
	visits: 0,
	sales_visits: 0,
	no_sale_visits: 0,
	invoices: 0,
	invoiced_amount: 0,
	collected_amount: 0,
})
const boot = (agent, openTrip) => ({
	csrf_token: "token",
	site_name: "agrosys.evonet.lk",
	lang: "en",
	translations: {},
	context: {
		user: agent ? "van1@evonet.lk" : "pilot.supervisor@evonet.lk",
		full_name: agent ? "Van Agent 1" : "Pilot Supervisor",
		agent,
		trip: openTrip,
		settings: {
			company: "Agro Republic (Pvt) Ltd",
			allow_credit_sales: 1,
			require_geolocation: 0,
			apply_customer_updates_directly: 1,
			selling_price_list: "Standard Selling",
			currency: "LKR",
		},
		no_sale_reasons: [{ name: "Stock Sufficient", category: "Stock", requires_remark: 0 }],
		denominations: [5000, 1000, 500, 100, 50, 20, 10, 5, 2, 1],
	},
})

// Shapes as returned by mobilesales.api.mobile (spec §6.2).
const API = {
	get_van_stock: [
		{
			item_code: "ARCP003",
			item_name: "Kochchi Chicken Meat",
			stock_uom: "Kg",
			actual_qty: 2,
			valuation_rate: 847.05,
			image: null,
			has_batch_no: 1,
			batches: [{ batch_no: "ARCP003-261016-01", qty: 2 }],
		},
	],
	get_route_plan: [
		{ customer: "Pilot Customer 1", customer_name: "Pilot Customer 1", sequence: 1, visit_frequency: "Daily", visit_day: "", visited: false, outstanding: 0 },
		{ customer: "test1", customer_name: "test1", sequence: 2, visit_frequency: "Daily", visit_day: "", visited: true, outstanding: 1325 },
	],
	get_visits: [
		{
			name: "CV-26-000001",
			docstatus: 1,
			visit_datetime: "2026-11-01 10:00:00",
			customer: "Pilot Customer 1",
			customer_name: "Pilot Customer 1",
			off_route: 0,
			outcome: "Sale",
			no_sale_reason: null,
			sales_invoice: "MB-SINV-26-00001",
			payment_entry: "ACC-PAY-2026-00001",
			grand_total: 1325,
			rounded_total: 1325,
			total_collected: 1325,
		},
		{
			name: "CV-26-000002",
			docstatus: 1,
			visit_datetime: "2026-11-01 11:00:00",
			customer: "Walk-in Shop",
			customer_name: "Walk-in Shop",
			off_route: 1,
			outcome: "Shop Closed",
			no_sale_reason: null,
			sales_invoice: null,
			payment_entry: null,
			grand_total: 0,
			rounded_total: 0,
			total_collected: 0,
		},
	],
	get_customer_form_options: {
		customer_groups: ["Commercial", "Retail"],
		territories: ["Colombo", "Sri Lanka"],
		routes: ["Pilot Route 1", "Pilot Route 2"],
		default_customer_group: "Retail",
		default_territory: "Colombo",
	},
	get_customer: {
		name: "Pilot Customer 1",
		customer_name: "Pilot Customer 1",
		customer_group: "Commercial",
		territory: "Sri Lanka",
		tax_id: null,
		mobile_no: "0771234567",
		email_id: null,
		contact: { name: "Pilot Contact", first_name: "Pilot", last_name: null, mobile_no: "0771234567", email_id: null },
		address: { name: "Pilot Address", address_line1: "1 Main Street", city: "Colombo", country: "Sri Lanka" },
		outstanding_invoices: [{ name: "MB-SINV-26-00000", posting_date: "2026-10-31", grand_total: 1325, outstanding_amount: 1325 }],
		outstanding: 1325,
		shelf_stock: [{ item_code: "ARCP003", qty_on_shelf: 1, uom: "Kg", expiry_date: null, competitor_item: null }],
	},
	get_settlement_draft: {
		name: null,
		workflow_state: "Draft",
		docstatus: 0,
		editable: true,
		opening_cash_float: 0,
		invoiced_amount: 1325,
		total_collected: 1325,
		total_visits: 2,
		expected_cash: 1325,
		stock_lines: [
			{ item_code: "ARCP003", item_name: "Kochchi Chicken Meat", uom: "Kg", has_batch_no: 1, expected_balance: 1, returned_qty: 0, damaged_qty: 0, damaged_batch_no: null },
		],
		batch_lines: [{ item_code: "ARCP003", batch_no: "ARCP003-261016-01", expected: 1 }],
		denominations: [5000, 1000, 500, 100, 50, 20, 10, 5, 2, 1].map((denomination) => ({ denomination, count: 0, value: 0 })),
	},
	search_customers: [],
}

const SCENARIOS = [
	{ title: "agent with a Loaded trip", boot: boot(AGENT, trip("Loaded")), expect: "MTRIP-26-00003" },
	{ title: "agent with an In Field trip", boot: boot(AGENT, trip("In Field")), expect: "MTRIP-26-00003" },
	{ title: "agent with a Settling trip", boot: boot(AGENT, trip("Settling")), expect: "MTRIP-26-00003" },
	{ title: "agent without an open trip", boot: boot(AGENT, null), expect: "Van Agent 1" },
	{ title: "logged-in user without an agent record", boot: boot(null, null), expect: "not set up as a Mobile Sales Agent" },
]
const PATHS = routes.filter((r) => !r.path.includes("pathMatch")).map((r) => r.path.replace(":customer", "Pilot%20Customer%201"))

let problems
beforeEach(() => {
	problems = []
	globalThis.fetch = vi.fn(async (url) => {
		const method = String(url).split(".").pop()
		if (!(method in API)) problems.push(`unexpected API call ${url}`)
		return { ok: true, status: 200, json: async () => ({ message: structuredClone(API[method] ?? null) }) }
	})
	vi.spyOn(console, "warn").mockImplementation((...a) => problems.push(`console.warn: ${a.join(" ")}`))
	vi.spyOn(console, "error").mockImplementation((...a) => problems.push(`console.error: ${a.join(" ")}`))
})
afterEach(() => vi.restoreAllMocks())

const settle = () => new Promise((resolve) => setTimeout(resolve, 30))

async function render(bootData, path, interact) {
	window.ms_boot = bootData
	window.csrf_token = bootData.csrf_token
	document.body.innerHTML = '<div id="app"></div>'
	const onRejection = (event) => problems.push(`unhandledrejection: ${event.reason?.stack || event.reason}`)
	window.addEventListener("unhandledrejection", onRejection)
	const { app, router } = createMobileApp(createMemoryHistory(), (err, info) => problems.push(`${info}: ${err?.stack || err}`))
	await router.push(path)
	app.mount("#app")
	await router.isReady()
	for (let i = 0; i < 5; i++) await settle()
	if (interact) {
		await interact(document.getElementById("app"))
		for (let i = 0; i < 5; i++) await settle()
	}
	const text = document.getElementById("app").textContent.replace(/\s+/g, " ")
	app.unmount()
	window.removeEventListener("unhandledrejection", onRejection)
	return text
}

describe("SPA mounts and renders every route", () => {
	for (const scenario of SCENARIOS) {
		for (const path of PATHS) {
			it(`${scenario.title}: ${decodeURIComponent(path)}`, async () => {
				const text = await render(scenario.boot, path)
				expect(problems).toEqual([])
				expect(text).toContain("Mobile Sales")
				expect(text).toContain(scenario.expect)
				expect(text).not.toContain("App failed to load")
			})
		}
	}
})

describe("screens", () => {
	const clickButton = (root, label) => [...root.querySelectorAll("button")].find((b) => b.textContent.includes(label)).click()

	it("Today offers Reopen Trip while Settling", async () => {
		const text = await render(boot(AGENT, trip("Settling")), "/")
		expect(problems).toEqual([])
		expect(text).toContain("Reopen Trip")
		expect(text).toContain("Go to Settlement")
	})

	it("History tags off-route visits", async () => {
		const text = await render(boot(AGENT, trip("In Field")), "/history")
		expect(problems).toEqual([])
		expect(text.match(/Off route/g)?.length).toBe(1)
	})

	it("New customer form has group, territory and route pickers with Settings defaults", async () => {
		let selects
		const text = await render(boot(AGENT, trip("In Field")), "/route", async (root) => {
			clickButton(root, "New customer")
			await settle()
			selects = [...root.querySelectorAll("form select")].map((s) => ({
				value: s.value,
				options: [...s.options].map((o) => o.value),
			}))
		})
		expect(problems).toEqual([])
		expect(text).toContain("Customer group")
		expect(selects).toEqual([
			{ value: "Retail", options: ["Commercial", "Retail"] },
			{ value: "Colombo", options: ["Colombo", "Sri Lanka"] },
			{ value: "", options: ["", "Pilot Route 1", "Pilot Route 2"] },
		])
	})
})
