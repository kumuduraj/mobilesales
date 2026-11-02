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
	max_discount_pct: 10,
	credit_limit_per_invoice: 0,
}
const trip = (status) => ({
	name: "MTRIP-26-00003",
	status,
	trip_date: "2026-11-01",
	route: "Pilot Route 1",
	vehicle: "VAN-01",
	helper: "Kamal",
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
			returns_enabled: 1,
			currency: "LKR",
		},
		no_sale_reasons: [{ name: "Stock Sufficient", category: "Stock", requires_remark: 0 }],
		return_reasons: [{ name: "Damaged", requires_remark: 0 }, { name: "Other", requires_remark: 1 }],
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
		{
			name: "CV-26-000003",
			docstatus: 1,
			visit_datetime: "2026-11-01 12:00:00",
			customer: "Pilot Customer 1",
			customer_name: "Pilot Customer 1",
			off_route: 0,
			outcome: "Return Only",
			no_sale_reason: null,
			sales_invoice: null,
			payment_entry: null,
			credit_notes: "MB-SRET-26-00001",
			return_total: 100,
			credit_applied: 100,
			grand_total: 0,
			rounded_total: 0,
			total_collected: 0,
		},
	],
	get_customer_invoices: [{ name: "MB-SINV-26-00002", posting_date: "2026-11-01", grand_total: 1325 }],
	get_returnable_lines: [
		{ sales_invoice_item: "row-1", item_code: "ARCP003", item_name: "Kochchi Chicken Meat", uom: "Kg", returnable_qty: 1, rate: 1325, batches: [{ batch_no: "ARCP003-261016-01", qty: 1 }] },
	],
	search_items: [],
	price_cart: {
		lines: [],
		net_total: 0,
		total_taxes: 0,
		grand_total: 0,
		rounded_total: 0,
		taxes: [],
		discount_amount: 0,
		manual_discount_pct: 0,
		max_discount_pct: 10,
		returns: [{ item_code: "ARCP003", qty: 1, uom: "Kg", rate: 1325, amount: 1325, against_invoice: "MB-SINV-26-00002" }],
		return_total: 1325,
		credit_applied: 1325,
		credit_on_sale: 0,
		credit_on_previous: { "MB-SINV-26-00000": 1325 },
		due_on_sale: 0,
		credit_left: 0,
	},
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
		credit_available: 250,
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
	save_settlement: null, // set below: the draft as saved, with the server's warnings
	submit_settlement_for_verification: null,
}
API.save_settlement = {
	...API.get_settlement_draft,
	name: "MSET-26-00003",
	warnings: ["10 Kg Kochchi Chicken Meat will be recorded as MISSING", "Cash is SHORT by LKR 25.00"],
}
API.submit_settlement_for_verification = { ...API.save_settlement, workflow_state: "Pending Store", editable: false }

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

	it("Today shows the vehicle and helper", async () => {
		const text = await render(boot(AGENT, trip("In Field")), "/")
		expect(problems).toEqual([])
		expect(text).toContain("VAN-01")
		expect(text).toContain("Helper: Kamal")
	})

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

describe("visit wizard (Phase 5b)", () => {
	const buttons = (root) => [...root.querySelectorAll("button")]
	const click = (root, label) => {
		const button = buttons(root).find((b) => b.textContent.trim().startsWith(label) && !b.disabled)
		if (!button) throw new Error(`no enabled button "${label}" in: ${root.textContent.replace(/\s+/g, " ").slice(0, 300)}`)
		button.click()
	}
	const choose = (el, value) => {
		el.value = value
		el.dispatchEvent(new Event("change"))
	}
	const type = (el, value) => {
		el.value = value
		el.dispatchEvent(new Event("input"))
	}
	const toOutcome = async (root) => {
		for (let i = 0; i < 3; i++) {
			click(root, "Next")
			await settle()
		}
	}

	it("details show the credit available; outcomes offer Return Only", async () => {
		let details = ""
		const text = await render(boot(AGENT, trip("In Field")), "/visit/Pilot%20Customer%201", async (root) => {
			click(root, "Next")
			await settle()
			details = root.textContent.replace(/\s+/g, " ")
			click(root, "Next")
			await settle()
			click(root, "Next")
			await settle()
		})
		expect(problems).toEqual([])
		expect(details).toContain("Credit available")
		expect(details).toContain("250.00")
		expect(text).toContain("Return Only")
	})

	it("Sale shows line and invoice discount inputs", async () => {
		const text = await render(boot(AGENT, trip("In Field")), "/visit/Pilot%20Customer%201", async (root) => {
			await toOutcome(root)
			click(root, "Sale")
			await settle()
			click(root, "+")
			await settle()
		})
		expect(problems).toEqual([])
		expect(text).toContain("Disc. %")
		expect(text).toContain("Invoice discount")
	})

	it("Return Only: returns step, credit, collection and review", async () => {
		const seen = {}
		const text = await render(boot(AGENT, trip("In Field")), "/visit/Pilot%20Customer%201", async (root) => {
			await toOutcome(root)
			click(root, "Return Only")
			await settle()
			click(root, "Next")
			await settle()
			seen.returns = root.textContent.replace(/\s+/g, " ")
			const card = root.querySelector(".rounded-lg.border")
			choose(card.querySelectorAll("select")[0], "MB-SINV-26-00002")
			for (let i = 0; i < 3; i++) await settle()
			choose(card.querySelectorAll("select")[1], "row-1")
			type(card.querySelector("input[type=number]"), "1")
			choose(card.querySelectorAll("select")[3], "Damaged")
			await settle()
			click(root, "+ Add return")
			for (let i = 0; i < 3; i++) await settle()
			seen.added = root.textContent.replace(/\s+/g, " ")
			click(root, "Next")
			for (let i = 0; i < 3; i++) await settle()
			seen.collection = root.textContent.replace(/\s+/g, " ")
			click(root, "Next")
			await settle()
		})
		expect(problems).toEqual([])
		expect(seen.returns).toContain("Returns from the customer")
		expect(seen.added).toContain("Kochchi Chicken Meat × 1 Kg")
		expect(seen.added).toContain("Return credit")
		expect(seen.collection).toContain("Return credit applied")
		expect(text).toContain("Review")
		expect(text).toContain("Credit applied")
		const priceCalls = globalThis.fetch.mock.calls.filter(([url]) => String(url).endsWith("price_cart"))
		expect(priceCalls.length).toBeGreaterThan(0)
	})

	it("History offers the credit note reprint and shows returns", async () => {
		const text = await render(boot(AGENT, trip("In Field")), "/history")
		expect(problems).toEqual([])
		expect(text).toContain("Credit note")
		expect(text).toContain("returns")
	})
})

describe("settlement screen", () => {
	const settling = () => boot(AGENT, trip("Settling"))
	const methodCalls = (method) => globalThis.fetch.mock.calls.filter(([url]) => String(url).endsWith(method)).length

	it("is read-only after Submit for Verification (any state but Draft)", async () => {
		const original = API.get_settlement_draft
		API.get_settlement_draft = { ...original, name: "MSET-26-00003", workflow_state: "Pending Approval", editable: false,
			stock_lines: [{ ...original.stock_lines[0], returned_qty: 0, damaged_qty: 0 }],
			denominations: original.denominations.map((d) => ({ ...d, count: d.denomination === 1000 ? 1 : 0 })) }
		let inputs = -1
		let buttons = []
		try {
			await render(settling(), "/settlement", async (root) => {
				inputs = root.querySelectorAll("main input, main select").length
				buttons = [...root.querySelectorAll("main button")].map((b) => b.textContent.trim())
			})
		} finally {
			API.get_settlement_draft = original
		}
		expect(problems).toEqual([])
		expect(inputs).toBe(0)
		expect(buttons).not.toContain("Submit for Verification")
	})

	it("confirms missing stock and cash variance before Submit for Verification, Cancel focused", async () => {
		const seen = {}
		await render(settling(), "/settlement", async (root) => {
			;[...root.querySelectorAll("button")].find((b) => b.textContent.includes("Submit for Verification")).click()
			for (let i = 0; i < 4; i++) await settle()
			const dialog = root.querySelector("[role=dialog]")
			seen.text = dialog?.textContent.replace(/\s+/g, " ")
			seen.focused = document.activeElement?.textContent.trim()
			;[...dialog.querySelectorAll("button")].find((b) => b.textContent.trim() === "Cancel").click()
			await settle()
			seen.afterCancel = { dialog: !!root.querySelector("[role=dialog]"), submits: methodCalls("submit_settlement_for_verification") }
			;[...root.querySelectorAll("button")].find((b) => b.textContent.includes("Submit for Verification")).click()
			for (let i = 0; i < 4; i++) await settle()
			;[...root.querySelector("[role=dialog]").querySelectorAll("button")].find((b) => b.textContent.trim() === "Continue").click()
			for (let i = 0; i < 4; i++) await settle()
			seen.afterContinue = { submits: methodCalls("submit_settlement_for_verification"), text: root.textContent }
		})
		expect(problems).toEqual([])
		expect(seen.text).toContain("10 Kg Kochchi Chicken Meat will be recorded as MISSING")
		expect(seen.text).toContain("Cash is SHORT by LKR 25.00")
		expect(seen.focused).toBe("Cancel")
		expect(seen.afterCancel).toEqual({ dialog: false, submits: 0 })
		expect(seen.afterContinue.submits).toBe(1)
		expect(seen.afterContinue.text).toContain("Submitted for verification")
	})
})
