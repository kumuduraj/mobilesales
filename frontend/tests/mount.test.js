// SPA mount test (CLAUDE.md rule 18): the real App + router mounted with a realistic window.ms_boot, every
// route rendered once per scenario. Any app/router error, unhandled rejection or Vue warning fails the build.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { createMemoryHistory } from "vue-router"
import { cancelEndSession, nav, timing as accountTiming } from "../src/account"
import { createMobileApp, routes } from "../src/app"
import { timing as connectionTiming } from "../src/connection"
import { connection, customerLine, LOGIN_URL, online, session, unsaved, visitPrints } from "../src/state"

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
		app_version: "1.0.1",
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
	get_my_day: { visits: 3, planned_visits: 5, sales_visits: 3, invoices: 3, sales_total: 6360, cash_collected: 4536, credit_given: 0,
		return_value: 2650, credit_applied: 2650 },
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
		{
			name: "CV-26-000004",
			docstatus: 1,
			visit_datetime: "2026-11-01 13:00:00",
			customer: "Pilot Customer 1",
			customer_name: "Pilot Customer 1",
			off_route: 0,
			outcome: "Sale",
			no_sale_reason: null,
			sales_invoice: "MB-SINV-26-00004",
			payment_entry: "ACC-PAY-2026-00007",
			credit_notes: "MB-SRET-26-00002",
			return_total: 1325,
			credit_applied: 1325,
			grand_total: 2517.5,
			rounded_total: 2518,
			total_collected: 1193,
		},
	],
	get_customer_invoices: [
		{ name: "MB-SINV-26-00002", posting_date: "2026-11-02", grand_total: 1325, rounded_total: 1325, outstanding_amount: 0,
			returnable: [{ item_code: "ARCP003", item_name: "Kochchi Chicken Meat", uom: "Kg", qty: 1 }] },
		{ name: "ACC-SINV-2026-00001", posting_date: "2026-11-01", grand_total: 1325, rounded_total: 1325, outstanding_amount: 825,
			returnable: [{ item_code: "ARCP003", item_name: "Kochchi Chicken Meat", uom: "Kg", qty: 1 }] },
		{ name: "MB-SINV-26-00001", posting_date: "2026-11-01", grand_total: 2650, rounded_total: 2650, outstanding_amount: 0, returnable: [] },
	],
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
API.submit_visit = {
	name: "CV-26-000008", docstatus: 1, outcome: "Sale", customer: "Pilot Customer 1", customer_name: "Pilot Customer 1",
	sales_invoice: "MB-SINV-26-00004", payment_entry: null, grand_total: 1325, rounded_total: 1325, total_collected: 0,
	return_total: 1325, credit_applied: 1325, credit_notes: "MB-SRET-26-00001", credit_journal: "ACC-JV-2026-00010", duplicate: false,
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
// server(url, init) → a response, or undefined for the default answers below (tests set it per case)
let server = null
const answer = (status, body) => ({ ok: status >= 200 && status < 300, status, json: async () => body })
beforeEach(() => {
	problems = []
	server = null
	globalThis.fetch = vi.fn(async (url, init) => {
		const special = server?.(String(url), init)
		if (special) return special
		if (String(url).endsWith("/api/method/ping")) return answer(200, { message: "pong" })
		if (String(url).endsWith("/api/method/logout")) return answer(200, {})
		if (String(url).endsWith("frappe.auth.get_logged_user")) return answer(200, { message: window.ms_boot?.context?.user })
		const method = String(url).split(".").pop()
		if (!(method in API)) problems.push(`unexpected API call ${url}`)
		return answer(200, { message: structuredClone(API[method] ?? null) })
	})
	vi.spyOn(console, "warn").mockImplementation((...a) => problems.push(`console.warn: ${a.join(" ")}`))
	vi.spyOn(console, "error").mockImplementation((...a) => problems.push(`console.error: ${a.join(" ")}`))
})
afterEach(() => vi.restoreAllMocks())

const settle = () => new Promise((resolve) => setTimeout(resolve, 30))

async function render(bootData, path, interact) {
	Object.assign(session, { ctx: null, loading: false, error: null }) // module state: no context from an earlier render
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

	it("Today shows My day from get_my_day (the Day Report figures)", async () => {
		const seen = {}
		await render(boot(AGENT, trip("In Field")), "/", async (root) => {
			const card = root.querySelector("[data-my-day]")
			seen.text = card?.textContent.replace(/\s+/g, " ")
		})
		expect(problems).toEqual([])
		const calls = globalThis.fetch.mock.calls.filter(([url]) => String(url).endsWith("get_my_day"))
		expect(calls.length).toBe(1)
		expect(seen.text).toContain("My day")
		expect(seen.text).toContain("3 / 5")
		expect(seen.text).toContain("6,360.00")
		expect(seen.text).toContain("3 invoices")
		expect(seen.text).toContain("4,536.00")
		expect(seen.text).toContain("Returns (credit)")
		expect(seen.text).toContain("2,650.00")
		expect(seen.text).not.toContain("Credit given")
	})

	it("Today keeps the trip's own figures until get_my_day answers", async () => {
		const original = API.get_my_day
		delete API.get_my_day
		const seen = {}
		try {
			await render(boot(AGENT, { ...trip("In Field"), visits: 2, invoices: 1, invoiced_amount: 1325, collected_amount: 825 }), "/", async (root) => {
				seen.text = root.querySelector("[data-my-day]")?.textContent.replace(/\s+/g, " ")
			})
		} finally {
			API.get_my_day = original
		}
		expect(problems.filter((p) => !p.includes("unexpected API call") || !p.includes("get_my_day"))).toEqual([])
		expect(seen.text).toContain("1,325.00")
		expect(seen.text).toContain("825.00")
	})

	it("Today without a trip: what to do, and the last trip's summary", async () => {
		const noTrip = boot(AGENT, null)
		noTrip.context.last_trip = { name: "MTRIP-26-00005", status: "Settled", trip_date: "2026-11-02", invoiced_amount: 4536 }
		const text = await render(noTrip, "/")
		expect(problems).toEqual([])
		expect(text.match(/No trip loaded/g)).toHaveLength(1)
		expect(text).toContain("Ask the store keeper to load your van.")
		expect(text).toContain("Last trip MTRIP-26-00005 · Settled · sales LKR 4,536.00")

		const first = await render(boot(AGENT, null), "/") // a new agent: no last trip line
		expect(problems).toEqual([])
		expect(first).toContain("Ask the store keeper to load your van.")
		expect(first).not.toContain("Last trip")
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

	it("Sale shows line and invoice discount inputs; the line row is labelled and starts at %", async () => {
		const row = {}
		const text = await render(boot(AGENT, trip("In Field")), "/visit/Pilot%20Customer%201", async (root) => {
			await toOutcome(root)
			click(root, "Sale")
			await settle()
			click(root, "+")
			await settle()
			const line = root.querySelector(".line-discount")
			row.labels = line.textContent.replace(/\s+/g, " ")
			row.mode = line.querySelector("select").value
			row.options = [...line.querySelector("select").options].map((o) => o.textContent.trim())
			row.placeholder = line.querySelector("input").getAttribute("placeholder")
		})
		expect(problems).toEqual([])
		expect(row.labels).toContain("Disc. type: % / Amount")
		expect(row.labels).toContain("Discount")
		expect(row.mode).toBe("pct") // never blank (live run 2026-11-04)
		expect(row.options).toEqual(["%", "Amount"])
		expect(row.placeholder).toBe("Discount")
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
			choose(card.querySelectorAll("select")[2], "Damaged")
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

	it("History shows each visit's prints only when the document exists, Print All in order", async () => {
		const cards = {}
		const text = await render(boot(AGENT, trip("In Field")), "/history", async (root) => {
			for (const card of root.querySelectorAll(".card")) {
				const name = (card.textContent.match(/CV-26-\d+/) || [])[0]
				if (name) cards[name] = [...card.querySelectorAll("a[data-print]")].map((a) => [a.dataset.print, a.textContent.trim(), a.getAttribute("href")])
			}
		})
		expect(problems).toEqual([])
		expect(text).toContain("returns")
		const keys = (name) => cards[name].map(([key]) => key)
		// sale only (invoice + receipt): bill, invoice, all, receipt
		expect(keys("CV-26-000001")).toEqual(["bill", "invoice", "all", "receipt"])
		// shop closed: nothing to print
		expect(keys("CV-26-000002")).toEqual([])
		// return only: bill, return note, all
		expect(keys("CV-26-000003")).toEqual(["bill", "note:MB-SRET-26-00001", "all"])
		// sale + return: bill (primary), invoice, return note, all, receipt
		expect(keys("CV-26-000004")).toEqual(["bill", "invoice", "note:MB-SRET-26-00002", "all", "receipt"])
		const [bill, invoice, note, all] = cards["CV-26-000004"]
		expect(bill[1]).toBe("Print Bill")
		expect(bill[2]).toContain("doctype=Customer+Visit&name=CV-26-000004&format=Mobile+Visit+Bill")
		expect(invoice[1]).toBe("Print Invoice")
		expect(invoice[2]).toContain("name=MB-SINV-26-00004&format=Mobile+Invoice+4in")
		expect(note[1]).toBe("Print Return Note")
		expect(note[2]).toContain("name=MB-SRET-26-00002&format=Mobile+Return+Note")
		expect(all).toEqual(["all", "Print All", "/mobile-sales-print?visit=CV-26-000004"])
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

describe("returns step never drops a return (live run MTRIP-26-00005)", () => {
	const settleMore = async () => {
		for (let i = 0; i < 4; i++) await settle()
	}
	const button = (root, label) => {
		const found = [...root.querySelectorAll("button")].find((b) => b.textContent.trim().startsWith(label))
		if (!found) throw new Error(`no button "${label}" in: ${root.textContent.replace(/\s+/g, " ").slice(0, 400)}`)
		return found
	}
	const choose = (el, value) => {
		el.value = value
		el.dispatchEvent(new Event("change"))
	}

	it("blocks Next while a return is filled in but not added, then submits it", async () => {
		const originalContext = API.get_context
		API.get_context = boot(AGENT, trip("In Field")).context
		const seen = {}
		try {
			await render(boot(AGENT, trip("In Field")), "/visit/Pilot%20Customer%201", async (root) => {
				for (let i = 0; i < 3; i++) {
					button(root, "Next").click()
					await settle()
				}
				button(root, "Sale").click()
				await settle()
				button(root, "+").click() // 1 Kg in the cart
				await new Promise((resolve) => setTimeout(resolve, 400)) // price_cart is debounced (350 ms)
				await settleMore()
				button(root, "Next").click()
				await settleMore()
				const form = root.querySelector(".rounded-lg.border")
				if (!form) throw new Error(`no return form in: ${root.textContent.replace(/\s+/g, " ").slice(0, 600)}`)
				choose(form.querySelectorAll("select")[0], "MB-SINV-26-00002")
				await settleMore()
				choose(form.querySelectorAll("select")[1], "row-1")
				const qtyInput = form.querySelector("input[type=number]")
				qtyInput.value = "1"
				qtyInput.dispatchEvent(new Event("input"))
				choose(form.querySelectorAll("select")[2], "Damaged") // condition
				choose(form.querySelectorAll("select")[3], "Damaged") // reason
				await settle()
				seen.nextDisabled = button(root, "Next").disabled
				seen.hint = root.textContent.includes("This return is not added yet")
				button(root, "Next").click() // must not move on
				await settle()
				seen.stillOnReturns = root.textContent.includes("Returns from the customer")
				button(root, "+ Add return").click()
				await settleMore()
				seen.nextAfterAdd = button(root, "Next").disabled
				button(root, "Next").click()
				await settleMore()
				button(root, "Next").click()
				await settleMore()
				seen.review = root.textContent.replace(/\s+/g, " ")
				button(root, "Submit visit").click()
				await settleMore()
				seen.submitsBeforeConfirm = globalThis.fetch.mock.calls.filter(([url]) => String(url).endsWith("submit_visit")).length
				button(root.querySelector("[role=dialog]"), "Confirm and submit").click()
				await settleMore()
				seen.done = root.textContent.replace(/\s+/g, " ")
			})
		} finally {
			API.get_context = originalContext
		}
		const submit = globalThis.fetch.mock.calls.find(([url]) => String(url).endsWith("submit_visit"))
		const payload = JSON.parse(submit[1].body.get("payload"))
		expect(problems).toEqual([])
		expect(seen).toMatchObject({ nextDisabled: true, hint: true, stillOnReturns: true, nextAfterAdd: false, submitsBeforeConfirm: 0 })
		expect(seen.review).toContain("Return: Kochchi Chicken Meat × 1 Kg")
		expect(seen.review).toContain("Reason: Damaged · Condition: Damaged")
		expect(payload.return_items).toEqual([
			{ item_code: "ARCP003", qty: 1, uom: "Kg", against_invoice: "MB-SINV-26-00002", sales_invoice_item: "row-1",
				return_reason: "Damaged", condition: "Damaged", remarks: null },
		])
		expect(payload.sale_items).toEqual([{ item_code: "ARCP003", qty: 1, discount_percentage: 0, discount_amount: 0 }])
		expect(seen.done).toContain("Print Bill")
		expect(seen.done).toContain("Print Invoice")
		expect(seen.done).toContain("Print Return Note")
		expect(seen.done).toContain("Print All")
		expect(seen.done).toContain("Return credit")
	})
	const toReturns = async (root) => {
		for (let i = 0; i < 3; i++) {
			button(root, "Next").click()
			await settle()
		}
		button(root, "Sale").click()
		await settle()
		button(root, "+").click()
		await new Promise((resolve) => setTimeout(resolve, 400)) // price_cart is debounced (350 ms)
		await settleMore()
		button(root, "Next").click()
		await settleMore()
		return root.querySelector(".rounded-lg.border")
	}

	it("starts with an empty invoice picker and says what is missing before + Add return", async () => {
		const originalContext = API.get_context
		API.get_context = boot(AGENT, trip("In Field")).context
		const seen = {}
		try {
			await render(boot(AGENT, trip("In Field")), "/visit/Pilot%20Customer%201", async (root) => {
				const form = await toReturns(root)
				const text = () => root.textContent.replace(/\s+/g, " ")
				seen.picker = form.querySelectorAll("select")[0].value
				seen.start = text()
				choose(form.querySelectorAll("select")[0], "MB-SINV-26-00002")
				await settleMore()
				seen.afterInvoice = text()
				seen.nextAfterInvoice = button(root, "Next").disabled
				choose(form.querySelectorAll("select")[1], "row-1")
				const qtyInput = form.querySelector("input[type=number]")
				qtyInput.value = "2"
				qtyInput.dispatchEvent(new Event("input"))
				await settle()
				seen.tooMuch = text()
				qtyInput.value = "1"
				qtyInput.dispatchEvent(new Event("input"))
				choose(form.querySelectorAll("select")[2], "Resaleable")
				choose(form.querySelectorAll("select")[3], "Other")
				await settle()
				seen.other = text()
				seen.addDisabled = button(root, "+ Add return").disabled
				const remarks = form.querySelector("input:not([type=number]):not([type=search])")
				remarks.value = "torn pack"
				remarks.dispatchEvent(new Event("input"))
				await settle()
				seen.addEnabled = !button(root, "+ Add return").disabled
				button(root, "+ Add return").click()
				await settleMore()
				seen.card = text()
			})
		} finally {
			API.get_context = originalContext
		}
		expect(problems).toEqual([])
		expect(seen.picker).toBe("")
		expect(seen.start).toContain("Choose invoice…")
		expect(seen.start).not.toContain("This return is not added yet")
		expect(seen.afterInvoice).toContain("Choose the item.")
		expect(seen.afterInvoice).not.toContain("This return is not added yet")
		expect(seen.nextAfterInvoice).toBe(false)
		expect(seen.tooMuch).toContain("At most 1 Kg can be returned from this invoice.")
		expect(seen.tooMuch).toContain("This return is not added yet")
		expect(seen.other).toContain("Remarks required for reason Other.")
		expect(seen.addDisabled).toBe(true)
		expect(seen.addEnabled).toBe(true)
		expect(seen.card).toContain("Reason: Other")
		expect(seen.card).toContain("Condition: Resaleable")
		expect(seen.card).toContain("Remarks: torn pack")
	})

	it("confirm dialog summarises sale lines, discounts, returns and cash before submitting", async () => {
		const originalContext = API.get_context
		const originalPrice = API.price_cart
		API.get_context = boot(AGENT, trip("In Field")).context
		API.price_cart = {
			...originalPrice,
			lines: [{ item_code: "ARCP003", item_name: "Kochchi Chicken Meat", uom: "Kg", qty: 2, price_list_rate: 1325, pricing_rule_rate: 1325,
				discount_percentage: 0, discount_amount: 0, rate: 1325, amount: 2650, enough_stock: true }],
			net_total: 2517.5, grand_total: 2517.5, rounded_total: 2518, discount_amount: 132.5, additional_discount_percentage: 5,
			credit_on_sale: 1325, credit_on_previous: {}, due_on_sale: 1193,
		}
		const seen = {}
		try {
			await render(boot(AGENT, trip("In Field")), "/visit/Pilot%20Customer%201", async (root) => {
				const form = await toReturns(root)
				choose(form.querySelectorAll("select")[0], "MB-SINV-26-00002")
				await settleMore()
				choose(form.querySelectorAll("select")[1], "row-1")
				const qtyInput = form.querySelector("input[type=number]")
				qtyInput.value = "1"
				qtyInput.dispatchEvent(new Event("input"))
				choose(form.querySelectorAll("select")[2], "Damaged")
				choose(form.querySelectorAll("select")[3], "Damaged")
				await settle()
				button(root, "+ Add return").click()
				await settleMore()
				button(root, "Next").click() // collection: collect = due 1193
				await settleMore()
				button(root, "Next").click()
				await settleMore()
				button(root, "Submit visit").click()
				await settleMore()
				const dialog = root.querySelector("[role=dialog]")
				seen.dialog = dialog?.textContent.replace(/\s+/g, " ")
				seen.focused = document.activeElement?.textContent.trim()
				button(dialog, "Cancel").click()
				await settle()
				seen.afterCancel = { dialog: !!root.querySelector("[role=dialog]"), submits: globalThis.fetch.mock.calls.filter(([url]) => String(url).endsWith("submit_visit")).length }
			})
		} finally {
			API.get_context = originalContext
			API.price_cart = originalPrice
		}
		expect(problems).toEqual([])
		expect(seen.dialog).toContain("Kochchi Chicken Meat × 2 Kg")
		expect(seen.dialog).toContain("Invoice discount (5%)")
		expect(seen.dialog).toContain("132.50")
		expect(seen.dialog).toContain("Reason: Damaged · Condition: Damaged")
		expect(seen.dialog).toContain("Return credit applied")
		expect(seen.dialog).toContain("Cash to collect now")
		expect(seen.dialog).toContain("1,193.00")
		expect(seen.focused).toBe("Cancel")
		expect(seen.afterCancel).toEqual({ dialog: false, submits: 0 })
	})
})

describe("returns picker and credit-covered sale (live run MTRIP-26-00005)", () => {
	const settleMore = async () => {
		for (let i = 0; i < 4; i++) await settle()
	}
	const button = (root, label) => [...root.querySelectorAll("button")].find((b) => b.textContent.trim().startsWith(label))
	const choose = (el, value) => {
		el.value = value
		el.dispatchEvent(new Event("change"))
	}
	const toReturns = async (root) => {
		for (let i = 0; i < 3; i++) {
			button(root, "Next").click()
			await settle()
		}
		button(root, "Sale").click()
		await settle()
		button(root, "+").click()
		await new Promise((resolve) => setTimeout(resolve, 400))
		await settleMore()
		button(root, "Next").click()
		await settleMore()
		return root.querySelector(".rounded-lg.border")
	}

	it("labels each invoice with date, qty, total and what is owed, newest first", async () => {
		const originalContext = API.get_context
		API.get_context = boot(AGENT, trip("In Field")).context
		const seen = {}
		try {
			await render(boot(AGENT, trip("In Field")), "/visit/Pilot%20Customer%201", async (root) => {
				const form = await toReturns(root)
				seen.options = [...form.querySelectorAll("select")[0].options].map((o) => o.textContent.trim())
				seen.disabled = [...form.querySelectorAll("select")[0].options].map((o) => o.disabled)
			})
		} finally {
			API.get_context = originalContext
		}
		expect(problems).toEqual([])
		expect(seen.options).toEqual([
			"Choose invoice…",
			"No invoice (item without batches)",
			"MB-SINV-26-00002 · 02-11 · 1 Kg · 1,325 · paid",
			"ACC-SINV-2026-00001 · 01-11 · 1 Kg · 1,325 · owes 825",
			"MB-SINV-26-00001 · 01-11 · all returned · 2,650 · paid",
		])
		// the placeholder and an invoice with nothing left to return cannot be chosen (live run 2026-11-04)
		expect(seen.disabled).toEqual([true, false, false, false, true])
	})

	it("reason and condition start empty on every new return line; Add waits for both", async () => {
		const originalContext = API.get_context
		API.get_context = boot(AGENT, trip("In Field")).context
		const lines = []
		try {
			await render(boot(AGENT, trip("In Field")), "/visit/Pilot%20Customer%201", async (root) => {
				const form = await toReturns(root)
				const selects = () => form.querySelectorAll("select")
				const condition = () => form.querySelector('select[aria-label="Condition"]')
				const reason = () => form.querySelector('select[aria-label="Reason"]')
				const state = () => ({
					condition: [condition().value, condition().selectedOptions[0]?.textContent.trim()],
					reason: [reason().value, reason().selectedOptions[0]?.textContent.trim()],
					addDisabled: button(root, "+ Add return").disabled,
					text: root.textContent.replace(/\s+/g, " "),
				})
				const fillLine = async () => {
					choose(selects()[0], "MB-SINV-26-00002")
					await settleMore()
					choose(selects()[1], "row-1")
					const qtyInput = form.querySelector("input[type=number]")
					qtyInput.value = "1"
					qtyInput.dispatchEvent(new Event("input"))
					await settle()
				}
				for (let line = 0; line < 2; line++) {
					const seen = { start: state() }
					await fillLine()
					seen.filled = state() // item and qty only
					choose(condition(), "Damaged")
					await settle()
					seen.conditionOnly = state()
					choose(condition(), "")
					choose(reason(), "Damaged")
					await settle()
					seen.reasonOnly = state()
					choose(condition(), "Damaged")
					await settle()
					seen.both = state()
					button(root, "+ Add return").click()
					await settleMore()
					lines.push(seen)
				}
				lines.push({ after: state() })
			})
		} finally {
			API.get_context = originalContext
		}
		expect(problems).toEqual([])
		for (const seen of lines.slice(0, 2)) {
			expect(seen.start.condition).toEqual(["", "Choose condition…"])
			expect(seen.start.reason).toEqual(["", "Choose reason…"])
			expect(seen.filled.addDisabled).toBe(true)
			expect(seen.conditionOnly).toMatchObject({ addDisabled: true, reason: ["", "Choose reason…"] })
			expect(seen.conditionOnly.text).toContain("Choose a reason.")
			expect(seen.reasonOnly.addDisabled).toBe(true)
			expect(seen.reasonOnly.text).toContain("Choose the condition.")
			expect(seen.both.addDisabled).toBe(false)
		}
		// the second line did not inherit the first line's reason / condition, and neither does a third
		expect(lines[2].after.condition).toEqual(["", "Choose condition…"])
		expect(lines[2].after.reason).toEqual(["", "Choose reason…"])
		expect(lines[2].after.text.match(/Reason: Damaged/g)).toHaveLength(2)
	})

	it("sets Collect Now to 0 and says why when the return credit covers the sale", async () => {
		const originalContext = API.get_context
		const originalPrice = API.price_cart
		const credit = boot(AGENT, trip("In Field"))
		credit.context.settings = { ...credit.context.settings, allow_credit_sales: 1 }
		API.get_context = credit.context
		API.price_cart = { ...originalPrice, rounded_total: 1325, grand_total: 1325, credit_on_sale: 1325, due_on_sale: 0, credit_applied: 1325 }
		const seen = {}
		try {
			await render(credit, "/visit/Pilot%20Customer%201", async (root) => {
				const form = await toReturns(root)
				choose(form.querySelectorAll("select")[0], "MB-SINV-26-00002")
				await settleMore()
				choose(form.querySelectorAll("select")[1], "row-1")
				const qtyInput = form.querySelector("input[type=number]")
				qtyInput.value = "1"
				qtyInput.dispatchEvent(new Event("input"))
				choose(form.querySelectorAll("select")[2], "Damaged")
				choose(form.querySelectorAll("select")[3], "Damaged")
				await settle()
				button(root, "+ Add return").click()
				await settleMore()
				button(root, "Next").click()
				await settleMore()
				const collect = [...root.querySelectorAll("input[type=number]")][0]
				seen.value = collect.value
				seen.readonly = collect.readOnly
				seen.text = root.textContent.replace(/\s+/g, " ")
			})
		} finally {
			API.get_context = originalContext
			API.price_cart = originalPrice
		}
		expect(problems).toEqual([])
		expect(seen.value).toBe("0")
		expect(seen.readonly).toBe(true)
		expect(seen.text).toContain("Return credit covers this invoice — nothing to collect.")
	})
})

describe("visit prints (v0.6.1)", () => {
	it("lists bill → invoice → each return note, Print All only for more than one document", () => {
		const keys = (visit) => visitPrints(visit).map((p) => p.key)
		expect(keys({ name: "CV-1", outcome: "No Sale" })).toEqual([])
		expect(keys({ name: "CV-2", sales_invoice: "SI-1" })).toEqual(["bill", "invoice", "all"])
		expect(keys({ name: "CV-3", credit_notes: "RN-1" })).toEqual(["bill", "note:RN-1", "all"])
		expect(keys({ name: "CV-4", payment_entry: "PE-1" })).toEqual(["bill"]) // collection only: the bill alone
		const two = visitPrints({ name: "CV-5", sales_invoice: "SI-1", credit_notes: "RN-1, RN-2" })
		expect(two.map((p) => p.key)).toEqual(["bill", "invoice", "note:RN-1", "note:RN-2", "all"])
		expect(two.map((p) => p.label)).toEqual(["Print Bill", "Print Invoice", "Print Return Note RN-1", "Print Return Note RN-2", "Print All"])
		expect(two.filter((p) => p.primary).map((p) => p.key)).toEqual(["bill"])
		expect(two.at(-1).url).toBe("/mobile-sales-print?visit=CV-5")
	})
})

// ---- v1.0.1: account menu, log out, session end, connection status --------------------------------------

const buttonStarting = (root, label) => [...root.querySelectorAll("button")].find((b) => b.textContent.trim().startsWith(label))
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms))
const calls = (needle) => globalThis.fetch.mock.calls.filter(([url]) => String(url).includes(needle))
const setOnLine = (value) => Object.defineProperty(navigator, "onLine", { configurable: true, get: () => value })

async function openLogout(root) {
	root.querySelector(".account-button").click()
	await settle()
	buttonStarting(root.querySelector(".account-menu"), "Log out").click()
	await settle()
	return root.querySelector(".logout-dialog")
}

describe("account menu and log out (v1.0.1)", () => {
	let go
	beforeEach(() => {
		go = vi.spyOn(nav, "go").mockImplementation(() => {})
		globalThis.caches = {
			keys: vi.fn(async () => ["mobile-sales-shell-v4", "mobile-sales-precache-v4-/assets", "other-app"]),
			delete: vi.fn(async () => true),
		}
	})
	afterEach(() => delete globalThis.caches)

	it("the agent name opens a menu: full name, email, agent code, vehicle, app version and Log out", async () => {
		const seen = {}
		await render(boot(AGENT, trip("In Field")), "/", async (root) => {
			expect(root.querySelector(".account-menu")).toBeNull()
			root.querySelector(".account-button").click()
			await settle()
			seen.menu = root.querySelector(".account-menu").textContent.replace(/\s+/g, " ")
		})
		expect(problems).toEqual([])
		for (const part of ["Van Agent 1", "van1@evonet.lk", "MSA-0001", "VAN-01", "1.0.1", "Log out"]) expect(seen.menu).toContain(part)
	})

	it("log out: confirm, POST logout with the CSRF token, the cached host page dropped, memory cleared, login page", async () => {
		const seen = {}
		await render(boot(AGENT, trip("In Field")), "/", async (root) => {
			const dialog = await openLogout(root)
			seen.dialog = dialog.textContent.replace(/\s+/g, " ")
			seen.focused = document.activeElement?.textContent.trim()
			expect(calls("/api/method/logout")).toEqual([])
			buttonStarting(dialog, "Log out").click()
			await settle()
		})
		expect(problems).toEqual([])
		expect(seen.dialog).toContain("Log out? Unsaved visit data on this screen will be lost.")
		expect(seen.dialog).not.toContain("A visit is in progress")
		expect(seen.focused).toBe("Cancel")
		const [[, init]] = calls("/api/method/logout")
		expect(init.method).toBe("POST")
		expect(init.headers["X-Frappe-CSRF-Token"]).toBe("token")
		// only the shell (host page with the user's boot data) cache; static assets and other apps stay
		expect(globalThis.caches.delete.mock.calls).toEqual([["mobile-sales-shell-v4"]])
		expect(session.ctx).toBeNull()
		expect(window.ms_boot).toBeNull()
		expect(window.csrf_token).toBeNull()
		expect(go).toHaveBeenCalledWith(LOGIN_URL)
		expect(LOGIN_URL).toBe("/login?redirect-to=/mobile-sales")
	})

	it("the dialog says when a visit is in progress", async () => {
		const seen = {}
		await render(boot(AGENT, trip("In Field")), "/visit/Pilot%20Customer%201", async (root) => {
			for (let i = 0; i < 3; i++) {
				buttonStarting(root, "Next").click()
				await settle()
			}
			buttonStarting(root, "Sale").click()
			await settle()
			buttonStarting(root, "+").click()
			await settle()
			seen.unsaved = unsaved.visit
			seen.dialog = (await openLogout(root)).textContent
			buttonStarting(root.querySelector(".logout-dialog"), "Cancel").click()
			await settle()
			seen.closed = root.querySelector(".logout-dialog")
		})
		expect(problems).toEqual([])
		expect(seen.unsaved).toBe(true)
		expect(seen.dialog).toContain("A visit is in progress and has not been submitted.")
		expect(seen.closed).toBeNull()
		expect(calls("/api/method/logout")).toEqual([])
		expect(unsaved.visit).toBe(false) // the wizard left the screen
	})

	it("the dialog says when the settlement has changes not saved", async () => {
		const seen = {}
		await render(boot(AGENT, trip("Settling")), "/settlement", async (root) => {
			seen.before = unsaved.settlement
			const input = root.querySelector("input[type=number]")
			input.value = "1"
			input.dispatchEvent(new Event("input"))
			await settle()
			seen.after = unsaved.settlement
			seen.dialog = (await openLogout(root)).textContent
		})
		expect(problems).toEqual([])
		expect(seen.before).toBe(false)
		expect(seen.after).toBe(true)
		expect(seen.dialog).toContain("The settlement has changes that are not saved.")
	})

	it("log out without a connection is refused with a message; the user stays logged in", async () => {
		server = (url) => {
			if (url.endsWith("/api/method/logout")) throw new TypeError("Failed to fetch")
		}
		const seen = {}
		await render(boot(AGENT, trip("In Field")), "/", async (root) => {
			const dialog = await openLogout(root)
			buttonStarting(dialog, "Log out").click()
			await settle()
			seen.dialog = root.querySelector(".logout-dialog").textContent
			seen.ctx = session.ctx?.user
		})
		expect(problems).toEqual([])
		expect(seen.dialog).toContain("Could not log out")
		expect(seen.ctx).toBe("van1@evonet.lk")
		expect(go).not.toHaveBeenCalled()
		expect(globalThis.caches.delete).not.toHaveBeenCalled()
	})

	it("user switch: agent A logs out, agent B logs in on the same phone — nothing of A is visible", async () => {
		await render(boot(AGENT, trip("In Field")), "/", async (root) => {
			buttonStarting(await openLogout(root), "Log out").click()
			await settle()
		})
		expect(window.ms_boot).toBeNull()
		const agentB = { ...AGENT, name: "MSA-0009", agent_name: "Van Agent 9", van_warehouse: "Van Agent 9 Van - ARL" }
		const bootB = boot(agentB, { ...trip("In Field"), name: "MTRIP-26-00099", vehicle: "VAN-09", helper: null, van_warehouse: agentB.van_warehouse })
		Object.assign(bootB.context, { user: "van9@evonet.lk", full_name: "Van Agent 9" })
		const seen = {}
		for (const path of ["/", "/history", "/route"]) {
			seen[path] = await render(bootB, path, async (root) => {
				root.querySelector(".account-button").click()
				await settle()
			})
		}
		expect(problems).toEqual([])
		for (const text of Object.values(seen)) {
			expect(text).toContain("Van Agent 9")
			expect(text).toContain("van9@evonet.lk")
			for (const ofA of ["Van Agent 1", "van1@evonet.lk", "MSA-0001", "MTRIP-26-00003", "VAN-01", "Kamal"]) expect(text).not.toContain(ofA)
		}
	})
})

describe("session ended (v1.0.1)", () => {
	let go
	beforeEach(() => {
		go = vi.spyOn(nav, "go").mockImplementation(() => {})
		accountTiming.expiredRedirect = 20
	})
	afterEach(() => {
		cancelEndSession() // a redirect still pending would clear the session in a later test
		session.expired = false
		accountTiming.expiredRedirect = 2500
	})

	it("a call refused because the login ended: a plain message, then the login page", async () => {
		server = (url) => {
			if (url.endsWith("get_van_stock")) return answer(403, { exc_type: "PermissionError" })
			if (url.endsWith("frappe.auth.get_logged_user")) return answer(403, { exc_type: "PermissionError" })
		}
		const text = await render(boot(AGENT, trip("In Field")), "/", () => wait(60))
		expect(problems).toEqual([])
		expect(text).not.toContain("Something went wrong")
		expect(go).toHaveBeenCalledWith(LOGIN_URL)
		expect(session.ctx).toBeNull()
	})

	it("shows the session-ended message on screen instead of the raw error", async () => {
		accountTiming.expiredRedirect = 5000
		server = (url) => {
			if (url.endsWith("get_van_stock")) return answer(403, {})
			if (url.endsWith("frappe.auth.get_logged_user")) return answer(200, { message: "Guest" })
		}
		const text = await render(boot(AGENT, trip("In Field")), "/")
		expect(problems).toEqual([])
		expect(text).toContain("Your session has ended — please log in again")
		expect(text).not.toContain("403")
		expect(go).not.toHaveBeenCalled() // only after the delay
		session.expired = false
	})

	it("a real permission refusal is shown as it is and the session goes on", async () => {
		const refusal = JSON.stringify([JSON.stringify({ message: "You can only see your own trips." })])
		server = (url) => {
			if (url.endsWith("get_van_stock")) return answer(403, { exc_type: "PermissionError", _server_messages: refusal })
		}
		const text = await render(boot(AGENT, trip("In Field")), "/")
		expect(problems).toEqual([])
		expect(text).toContain("You can only see your own trips.")
		expect(text).not.toContain("session has ended")
		expect(session.expired).toBe(false)
		expect(go).not.toHaveBeenCalled()
	})
})

describe("online / offline status (v1.0.1)", () => {
	const state = (root) => root.querySelector(".connection").dataset.state
	const label = (root) => root.querySelector(".connection").textContent.trim()
	beforeEach(() => {
		setOnLine(true)
		connection.value = "reconnecting"
		online.value = true
		connectionTiming.retry = 3000
	})
	afterEach(() => {
		setOnLine(true)
		connectionTiming.retry = 3000
	})

	it("is Online only after /api/method/ping answers", async () => {
		const seen = {}
		await render(boot(AGENT, trip("In Field")), "/", async (root) => {
			seen.state = state(root)
			seen.label = label(root)
		})
		expect(problems).toEqual([])
		expect(calls("/api/method/ping").length).toBeGreaterThan(0)
		expect(seen).toEqual({ state: "online", label: "Online" })
	})

	it("navigator says online but the ping fails (captive Wi-Fi): Reconnecting…, then Offline and saving blocked", async () => {
		connectionTiming.retry = 250
		server = (url) => {
			if (url.endsWith("/api/method/ping")) return answer(200, {}) // a login portal's page, not "pong"
		}
		const seen = {}
		await render(boot(AGENT, trip("In Field")), "/", async (root) => {
			seen.first = [state(root), label(root)]
			await wait(400)
			await settle()
			seen.then = [state(root), label(root)]
			seen.banner = root.textContent
		})
		expect(problems).toEqual([])
		expect(seen.first).toEqual(["reconnecting", "Reconnecting…"])
		expect(seen.then).toEqual(["offline", "Offline"])
		expect(seen.banner).toContain("No connection — you can look around")
		expect(online.value).toBe(false)
	})

	it("goes Offline at once; back online: Reconnecting…, then Online, a 'Back online' toast and the screen reloads", async () => {
		let pingOk = true
		server = (url) => {
			if (url.endsWith("/api/method/ping")) return pingOk ? answer(200, { message: "pong" }) : answer(503, {})
		}
		const seen = {}
		await render(boot(AGENT, trip("In Field")), "/", async (root) => {
			seen.start = state(root)
			setOnLine(false)
			window.dispatchEvent(new Event("offline"))
			await settle()
			seen.offline = [state(root), label(root), root.textContent.includes("No connection")]
			const before = calls("get_my_day").length
			setOnLine(true)
			window.dispatchEvent(new Event("online"))
			seen.reconnecting = connection.value
			await settle()
			await settle()
			seen.back = [state(root), label(root), root.querySelector(".toast")?.textContent.trim()]
			seen.reloaded = calls("get_my_day").length - before
		})
		expect(problems).toEqual([])
		expect(seen.start).toBe("online")
		expect(seen.offline).toEqual(["offline", "Offline", true])
		expect(seen.reconnecting).toBe("reconnecting")
		expect(seen.back).toEqual(["online", "Online", "Back online"])
		expect(seen.reloaded).toBeGreaterThan(0)
	})
})

// ---- v1.0.2: customer identification, route order and NEXT, cart, credit, name change ---------------------

async function withApi(overrides, fn) {
	const saved = Object.fromEntries(Object.keys(overrides).map((k) => [k, API[k]]))
	Object.assign(API, structuredClone(overrides))
	try {
		return await fn()
	} finally {
		Object.assign(API, saved)
	}
}
const IDENT = { address_line1: "No 1, Main Road", city: "JA-ELA", mobile_no: "0700 000 002" }
const routeRow = (sequence, customer, extra = {}) => ({
	customer, customer_name: customer, sequence, visit_frequency: "Daily", visit_day: "", due: true, visited: false,
	outcome: null, outstanding: 0, address_line1: null, city: null, mobile_no: null, ...extra,
})  // fmt: skip
const rowsText = (root, selector) => [...root.querySelectorAll(selector)].map((el) => el.textContent.replace(/\s+/g, " ").trim())

describe("customer identification (v1.0.2)", () => {
	it("shows '<address line 1>, <city> · …<last 4 of mobile>' and skips missing parts", () => {
		expect(customerLine(IDENT)).toBe("No 1, Main Road, JA-ELA · …0002")
		expect(customerLine({ city: "JA-ELA" })).toBe("JA-ELA")
		expect(customerLine({ mobile_no: "+94 77 123 4567" })).toBe("…4567")
		expect(customerLine({ address: { address_line1: "1 Main Street", city: "Colombo" }, mobile_no: null })).toBe("1 Main Street, Colombo")
		expect(customerLine({})).toBe("")
	})

	it("Route list and search results carry the line under the name; search asks the server for address and mobile too", async () => {
		const seen = {}
		await withApi(
			{ get_route_plan: [routeRow(1, "Pilot Customer 1", IDENT), routeRow(2, "test1")], search_customers: [{ name: "Shop A", customer_name: "Shop A", outstanding: 0, ...IDENT }] },
			() =>
				render(boot(AGENT, trip("In Field")), "/route", async (root) => {
					seen.rows = rowsText(root, ".route-row .customer-line")
					const input = root.querySelector("input[type=search]")
					input.value = "JA-ELA"
					input.dispatchEvent(new Event("input"))
					await new Promise((resolve) => setTimeout(resolve, 400))
					await settle()
					seen.results = rowsText(root, ".search-result .customer-line")
					seen.placeholder = input.getAttribute("placeholder")
				})
		)
		expect(problems).toEqual([])
		expect(seen.rows).toEqual(["No 1, Main Road, JA-ELA · …0002"]) // test1 has none: no empty line
		expect(seen.results).toEqual(["No 1, Main Road, JA-ELA · …0002"])
		expect(seen.placeholder).toContain("address")
		const [[, init]] = calls("search_customers")
		expect(init.body.get("q")).toBe("JA-ELA")
	})

	it("visit header, previous-outstanding and return pickers, and History show the line", async () => {
		const seen = {}
		await withApi({ get_customer: { ...API.get_customer, ...IDENT }, get_visits: API.get_visits.map((v) => ({ ...v, ...IDENT })) }, async () => {
			await render(boot(AGENT, trip("In Field")), "/visit/Pilot%20Customer%201", async (root) => {
				seen.header = root.querySelector(".customer-line")?.textContent.trim()
				for (let i = 0; i < 3; i++) {
					buttonStarting(root, "Next").click()
					await settle()
				}
				buttonStarting(root, "Return Only").click()
				await settle()
				buttonStarting(root, "Next").click()
				await settle()
				seen.returns = [...root.querySelectorAll(".customer-line")].pop()?.textContent.trim()
			})
			seen.history = await render(boot(AGENT, trip("In Field")), "/history", async (root) => {
				seen.historyLines = rowsText(root, ".customer-line")
			})
		})
		expect(problems).toEqual([])
		expect(seen.header).toBe("No 1, Main Road, JA-ELA · …0002")
		expect(seen.returns).toBe("Pilot Customer 1 · No 1, Main Road, JA-ELA · …0002")
		expect(seen.historyLines.length).toBe(API.get_visits.length)
		expect(new Set(seen.historyLines)).toEqual(new Set(["No 1, Main Road, JA-ELA · …0002"]))
	})
})

describe("route order and NEXT (v1.0.2)", () => {
	const routeState = (root) => ({
		numbers: rowsText(root, ".route-number"),
		next: root.querySelector(".route-next")?.dataset.customer || null,
		badges: root.querySelectorAll(".next-badge").length,
		start: !!root.querySelector(".route-next .start-visit"),
		visited: rowsText(root, ".route-row .visited"),
	})
	const routeOf = (rows) => withApi({ get_route_plan: rows }, () => render(boot(AGENT, trip("In Field")), "/route", async (root) => (seenRoute = routeState(root))))
	let seenRoute

	it("numbers the customers in route order; NEXT is the first not visited, with Start visit", async () => {
		await routeOf([routeRow(1, "A"), routeRow(2, "B"), routeRow(3, "C")])
		expect(problems).toEqual([])
		expect(seenRoute).toEqual({ numbers: ["1.", "2.", "3."], next: "A", badges: 1, start: true, visited: [] })
	})

	it("after a visit NEXT moves on; visited ones show ✓ and the outcome", async () => {
		await routeOf([routeRow(1, "A", { visited: true, outcome: "Sale" }), routeRow(2, "B"), routeRow(3, "C")])
		expect(seenRoute.next).toBe("B")
		expect(seenRoute.visited).toEqual(["✓ Sale"])
	})

	it("out of order: the agent visited C first — NEXT stays on the first not visited (A), nothing is blocked", async () => {
		await routeOf([routeRow(1, "A"), routeRow(2, "B"), routeRow(3, "C", { visited: true, outcome: "No Sale" })])
		expect(seenRoute.next).toBe("A")
		expect(seenRoute.visited).toEqual(["✓ No Sale"])
	})

	it("skips customers not due today; when all are visited there is no NEXT", async () => {
		await routeOf([routeRow(1, "A", { due: false }), routeRow(2, "B")])
		expect(seenRoute.next).toBe("B")
		await routeOf([routeRow(1, "A", { visited: true, outcome: "Sale" }), routeRow(2, "B", { visited: true, outcome: "Shop Closed" })])
		expect(seenRoute).toMatchObject({ next: null, badges: 0, start: false })
	})
})

describe("credit display and name change on the card (v1.0.2)", () => {
	it("a negative balance is 'Credit: LKR x' in green on the Route list, search results and the card", async () => {
		const seen = {}
		await withApi(
			{
				get_route_plan: [routeRow(1, "Pilot Customer 1", { outstanding: -649 }), routeRow(2, "test1", { outstanding: 1325 })],
				search_customers: [{ name: "Pilot Customer 1", customer_name: "Pilot Customer 1", outstanding: -649 }],
				get_customer: { ...API.get_customer, outstanding: 0, balance: -649, pending_name: "Pilot Shop (New)" },
			},
			async () => {
				await render(boot(AGENT, trip("In Field")), "/route", async (root) => {
					seen.route = [...root.querySelectorAll(".route-row .balance")].map((el) => [el.textContent.replace(/\s+/g, " ").trim(), el.classList.contains("text-green-700")])
					const input = root.querySelector("input[type=search]")
					input.value = "Pilot"
					input.dispatchEvent(new Event("input"))
					await new Promise((resolve) => setTimeout(resolve, 400))
					await settle()
					seen.search = root.querySelector(".search-result .balance")?.textContent.replace(/\s+/g, " ").trim()
				})
				await render(boot(AGENT, trip("In Field")), "/visit/Pilot%20Customer%201", async (root) => {
					seen.pending = root.querySelector(".pending-name")?.textContent.trim()
					buttonStarting(root, "Next").click()
					await settle()
					const value = root.querySelector(".card-balance")
					seen.card = [value.previousElementSibling.textContent.trim(), value.textContent.trim(), value.classList.contains("text-green-700")]
				})
			}
		)
		expect(problems).toEqual([])
		expect(seen.route).toEqual([["Credit: LKR 649.00", true], ["Outstanding: LKR 1,325.00", false]])
		expect(seen.search).toBe("Credit: LKR 649.00")
		expect(seen.card).toEqual(["Credit", "LKR 649.00", true])
		expect(seen.pending).toBe("Name change pending: Pilot Shop (New)")
	})
})

describe("cart with many items (v1.0.2)", () => {
	const VAN = [
		{ item_code: "ARCP003", item_name: "Kochchi Chicken Meat", stock_uom: "Kg", actual_qty: 10, price_list_rate: 1325, image: "/files/chicken.jpg", has_batch_no: 1, batches: [] },
		{ item_code: "EGG01", item_name: "Farm Eggs", stock_uom: "Nos", actual_qty: 60, price_list_rate: 45, image: null, has_batch_no: 0, batches: [] },
		{ item_code: "SAU02", item_name: "Chicken Sausage", stock_uom: "Pack", actual_qty: 12, price_list_rate: 890, image: null, has_batch_no: 0, batches: [] },
	]
	const cartState = (root) => ({
		rows: [...root.querySelectorAll(".cart-row")].map((r) => r.dataset.item),
		chips: rowsText(root, ".cart-chip"),
		empty: root.querySelector(".cart-empty")?.textContent.trim() || null,
	})
	const toCart = async (root) => {
		for (let i = 0; i < 3; i++) {
			buttonStarting(root, "Next").click()
			await settle()
		}
		buttonStarting(root, "Sale").click()
		await settle()
	}
	const plus = async (root, item) => {
		buttonStarting(root.querySelector(`.cart-row[data-item="${item}"]`), "+").click()
		await new Promise((resolve) => setTimeout(resolve, 400))
		await settle()
	}

	it("each row: code, qty in van, price, thumbnail; qty > 0 rows go to the top with their line total", async () => {
		const seen = {}
		const priced = { ...API.price_cart, returns: [], return_total: 0, credit_applied: 0, credit_on_previous: {},
			lines: [{ item_code: "SAU02", qty: 1, rate: 890, amount: 890, enough_stock: true }], rounded_total: 890, due_on_sale: 890 }  // fmt: skip
		await withApi({ get_van_stock: VAN, price_cart: priced }, () =>
			render(boot(AGENT, trip("In Field")), "/visit/Pilot%20Customer%201", async (root) => {
				await toCart(root)
				seen.before = cartState(root)
				const first = root.querySelector('.cart-row[data-item="ARCP003"]')
				seen.firstText = first.textContent.replace(/\s+/g, " ")
				seen.thumb = first.querySelector(".cart-thumb")?.getAttribute("src")
				seen.noThumb = root.querySelector('.cart-row[data-item="EGG01"] .cart-thumb')
				await plus(root, "SAU02")
				seen.after = cartState(root)
				seen.total = root.querySelector('.cart-row[data-item="SAU02"] .cart-line-total')?.textContent.replace(/\s+/g, " ").trim()
			})
		)
		expect(problems).toEqual([])
		expect(seen.before).toEqual({ rows: ["ARCP003", "EGG01", "SAU02"], chips: ["In cart (0)", "All van items (3)"], empty: null })
		expect(seen.firstText).toContain("ARCP003 · In van: 10 Kg · LKR 1,325.00 / Kg")
		expect(seen.thumb).toBe("/files/chicken.jpg")
		expect(seen.noThumb).toBeNull()
		expect(seen.after.rows).toEqual(["SAU02", "ARCP003", "EGG01"]) // in cart first, the rest keep the van order
		expect(seen.after.chips).toEqual(["In cart (1)", "All van items (3)"])
		expect(seen.total).toBe("1 × LKR 890.00 = LKR 890.00")
	})

	it("search by name or code and the 'In cart' / 'All van items' chips", async () => {
		const seen = {}
		await withApi({ get_van_stock: VAN }, () =>
			render(boot(AGENT, trip("In Field")), "/visit/Pilot%20Customer%201", async (root) => {
				await toCart(root)
				const search = root.querySelector(".cart-search")
				const type = async (text) => {
					search.value = text
					search.dispatchEvent(new Event("input"))
					await settle()
				}
				await type("chicken")
				seen.byName = cartState(root).rows
				await type("egg01")
				seen.byCode = cartState(root).rows
				await type("zzz")
				seen.none = cartState(root).empty
				await type("")
				buttonStarting(root, "In cart").click()
				await settle()
				seen.emptyCart = cartState(root)
				buttonStarting(root, "All van items").click()
				await settle()
				await plus(root, "EGG01")
				buttonStarting(root, "In cart").click()
				await settle()
				seen.inCart = cartState(root).rows
				seen.pressed = [...root.querySelectorAll(".cart-chip")].map((b) => b.getAttribute("aria-pressed"))
			})
		)
		expect(problems).toEqual([])
		expect(seen.byName).toEqual(["ARCP003", "SAU02"])
		expect(seen.byCode).toEqual(["EGG01"])
		expect(seen.none).toBe("No van item matches.")
		expect(seen.emptyCart).toMatchObject({ rows: [], empty: "Nothing in the cart yet." })
		expect(seen.inCart).toEqual(["EGG01"])
		expect(seen.pressed).toEqual(["true", "false"])
	})
})
