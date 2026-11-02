<template>
	<div class="space-y-3">
		<div class="card">
			<div class="text-sm text-gray-500">{{ __("Visit") }}</div>
			<div class="text-lg font-semibold">{{ card?.customer_name || customer }}</div>
			<div v-if="!done" class="mt-2 flex gap-1">
				<div v-for="(s, i) in steps" :key="s" class="h-1.5 flex-1 rounded-full" :class="i <= stepIndex ? 'bg-gray-900' : 'bg-gray-200'"></div>
			</div>
			<div v-if="!done" class="mt-1 text-xs text-gray-500">{{ stepLabels[step] }}</div>
		</div>

		<div v-if="loadError" class="card text-red-700">{{ loadError }}</div>

		<!-- 1. Check-in -->
		<div v-else-if="step === 'checkin'" class="card space-y-3">
			<div>
				<div class="label">{{ __("Location") }}{{ requireGeo ? " *" : "" }}</div>
				<div v-if="form.latitude" class="text-sm text-gray-700">{{ form.latitude.toFixed(5) }}, {{ form.longitude.toFixed(5) }}</div>
				<div v-else class="text-sm text-gray-500">{{ geoMessage || __("Not captured yet") }}</div>
				<button class="btn-secondary mt-2 w-full" :disabled="geoBusy" @click="captureLocation">{{ __("Capture location") }}</button>
			</div>
			<div>
				<div class="label">{{ __("Check-in photo (optional)") }}</div>
				<input type="file" accept="image/*" capture="environment" class="text-sm" @change="takePhoto" />
				<img v-if="photo" :src="photo" class="mt-2 max-h-40 rounded-lg" />
			</div>
		</div>

		<!-- 2. Customer details -->
		<div v-else-if="step === 'details'" class="card space-y-3">
			<div class="grid grid-cols-2 gap-x-3 gap-y-1 text-sm">
				<div class="text-gray-500">{{ __("Mobile") }}</div><div>{{ card.contact?.mobile_no || card.mobile_no || "—" }}</div>
				<div class="text-gray-500">{{ __("Contact") }}</div><div>{{ contactName || "—" }}</div>
				<div class="text-gray-500">{{ __("Address") }}</div><div>{{ card.address ? `${card.address.address_line1}, ${card.address.city}` : "—" }}</div>
				<div class="text-gray-500">{{ __("Tax ID") }}</div><div>{{ card.tax_id || "—" }}</div>
				<div class="text-gray-500">{{ __("Outstanding") }}</div><div class="font-semibold">{{ money(card.outstanding) }}</div>
				<template v-if="card.credit_available">
					<div class="text-gray-500">{{ __("Credit available") }}</div><div class="font-semibold text-green-700">{{ money(card.credit_available) }}</div>
				</template>
			</div>
			<label class="flex min-h-[44px] items-center gap-2">
				<input v-model="form.update_customer" type="checkbox" class="h-5 w-5" />
				<span>{{ __("Details changed — update them") }}</span>
			</label>
			<div v-if="form.update_customer" class="space-y-2">
				<div v-for="f in changeFields" :key="f.key">
					<label class="label">{{ f.label }}</label>
					<input v-model.trim="form[f.key]" class="field" :type="f.type || 'text'" :placeholder="f.current || ''" />
				</div>
				<p class="text-xs text-gray-500">{{ __("Leave a field empty to keep the current value.") }}</p>
			</div>
		</div>

		<!-- 3. Shelf stock -->
		<div v-else-if="step === 'shelf'" class="card space-y-3">
			<div v-if="card.shelf_stock?.length" class="text-xs text-gray-500">
				{{ __("Last count") }}: <span v-for="s in card.shelf_stock" :key="s.item_code">{{ s.item_code }} {{ qty(s.qty_on_shelf) }}; </span>
			</div>
			<div v-for="(row, i) in shelf" :key="i" class="space-y-2 rounded-lg border border-gray-200 p-3">
				<select v-model="row.item_code" class="field">
					<option value="">{{ __("Item…") }}</option>
					<option v-for="it in vanItems" :key="it.item_code" :value="it.item_code">{{ it.item_name }}</option>
				</select>
				<div class="grid grid-cols-2 gap-2">
					<input v-model.number="row.qty_on_shelf" class="field" type="number" inputmode="decimal" min="0" :placeholder="__('Qty on shelf')" />
					<input v-model="row.expiry_date" class="field" type="date" />
				</div>
				<input v-model.trim="row.competitor_item" class="field" :placeholder="__('Competitor item (optional)')" />
				<button class="text-sm text-red-700" @click="shelf.splice(i, 1)">{{ __("Remove") }}</button>
			</div>
			<button class="btn-secondary w-full" @click="shelf.push({ item_code: '', qty_on_shelf: null, expiry_date: '', competitor_item: '' })">
				+ {{ __("Add shelf item") }}
			</button>
		</div>

		<!-- 4. Outcome -->
		<div v-else-if="step === 'outcome'" class="space-y-3">
			<div class="grid grid-cols-2 gap-2">
				<button
					v-for="o in outcomes"
					:key="o"
					class="btn"
					:class="form.outcome === o ? 'bg-gray-900 text-white' : 'border border-gray-300 bg-white'"
					@click="form.outcome = o"
				>{{ __(o) }}</button>
			</div>
			<div v-if="isNoSale" class="card space-y-3">
				<div v-if="form.outcome === 'No Sale'">
					<label class="label">{{ __("Reason") }} *</label>
					<select v-model="form.no_sale_reason" class="field">
						<option value="">{{ __("Choose…") }}</option>
						<option v-for="r in reasons" :key="r.name" :value="r.name">{{ r.name }}</option>
					</select>
				</div>
				<div>
					<label class="label">{{ __("Remarks") }}{{ remarkRequired ? " *" : "" }}</label>
					<textarea v-model.trim="form.remarks" class="field min-h-[80px] py-2"></textarea>
				</div>
			</div>
			<div v-if="form.outcome === 'Sale'" class="card space-y-2">
				<div class="font-semibold">{{ __("Cart (from van stock)") }}</div>
				<div v-for="it in vanItems" :key="it.item_code" class="border-t border-gray-100 py-2">
					<div class="flex items-center justify-between">
						<div>
							<div class="font-medium">{{ it.item_name }}</div>
							<div class="text-xs text-gray-500">{{ __("In van") }}: {{ qty(it.actual_qty) }} {{ it.stock_uom }}</div>
						</div>
						<div class="flex items-center gap-1">
							<button class="btn-secondary h-11 w-11 min-h-0 px-0" @click="bump(it, -1)">−</button>
							<input v-model.number="cart[it.item_code]" class="field w-20 text-center" type="number" inputmode="decimal" min="0" @input="schedulePrice" />
							<button class="btn-secondary h-11 w-11 min-h-0 px-0" @click="bump(it, 1)">+</button>
						</div>
					</div>
					<div v-if="maxDiscount > 0 && cart[it.item_code] > 0" class="mt-1 flex items-center gap-2 text-sm">
						<select v-model="discountMode[it.item_code]" class="field w-24" @change="schedulePrice">
							<option value="pct">{{ __("Disc. %") }}</option>
							<option value="amt">{{ __("Disc. amt") }}</option>
						</select>
						<input v-model.number="discounts[it.item_code]" class="field w-24" type="number" inputmode="decimal" min="0" @input="schedulePrice" />
					</div>
					<div v-if="lineFor(it.item_code)" class="mt-1 text-sm text-gray-600">
						{{ qty(lineFor(it.item_code).qty) }} × {{ money(lineFor(it.item_code).rate) }} = {{ money(lineFor(it.item_code).amount) }}
						<span v-if="!lineFor(it.item_code).enough_stock" class="ml-1 font-medium text-red-700">{{ __("not enough in van") }}</span>
					</div>
				</div>
				<div v-if="maxDiscount > 0 && cartItems.length" class="flex items-center gap-2 border-t border-gray-100 pt-2 text-sm">
					<span class="text-gray-500">{{ __("Invoice discount") }}</span>
					<select v-model="invoiceDiscount.mode" class="field w-24" @change="schedulePrice">
						<option value="pct">%</option>
						<option value="amt">{{ __("amount") }}</option>
					</select>
					<input v-model.number="invoiceDiscount.value" class="field w-24" type="number" inputmode="decimal" min="0" @input="schedulePrice" />
				</div>
				<div v-if="priced && cartItems.length" class="border-t border-gray-200 pt-2 text-sm">
					<div v-if="priced.discount_amount" class="flex justify-between text-gray-600"><span>{{ __("Invoice discount") }}</span><span>− {{ money(priced.discount_amount) }}</span></div>
					<div v-if="priced.manual_discount_pct" class="flex justify-between text-xs text-gray-500"><span>{{ __("Your discounts") }}</span><span>{{ priced.manual_discount_pct }}% (≤ {{ maxDiscount }}%)</span></div>
					<div class="flex justify-between"><span>{{ __("Net total") }}</span><span>{{ money(priced.net_total) }}</span></div>
					<div v-for="t in priced.taxes" :key="t.description" class="flex justify-between text-gray-600"><span>{{ t.description }}</span><span>{{ money(t.amount) }}</span></div>
					<div class="flex justify-between text-base font-semibold"><span>{{ __("Total") }}</span><span>{{ money(priced.rounded_total) }}</span></div>
				</div>
				<p v-if="priceError" class="text-sm text-red-700">{{ priceError }}</p>
			</div>
		</div>

		<!-- 4b. Returns -->
		<div v-else-if="step === 'returns'" class="card space-y-3">
			<div class="font-semibold">{{ __("Returns from the customer") }}</div>
			<div v-for="(r, i) in returnRows" :key="i" class="flex items-start justify-between border-t border-gray-100 py-2 text-sm">
				<div>
					<div class="font-medium">{{ r.item_name || r.item_code }} × {{ qty(r.qty) }} {{ r.uom }}</div>
					<div class="text-xs text-gray-500">{{ r.against_invoice || __("No invoice") }} · {{ r.return_reason }} · {{ __(r.condition) }}</div>
					<div v-if="returnLine(i)" class="text-xs text-gray-600">{{ money(returnLine(i).rate) }} = {{ money(returnLine(i).amount) }}</div>
				</div>
				<button class="text-sm text-red-700" @click="removeReturn(i)">{{ __("Remove") }}</button>
			</div>
			<div class="space-y-2 rounded-lg border border-gray-200 p-3">
				<select v-model="newReturn.against_invoice" class="field" @change="loadReturnLines">
					<option value="">{{ __("No invoice (item without batches)") }}</option>
					<option v-for="inv in customerInvoices" :key="inv.name" :value="inv.name">{{ inv.name }} · {{ inv.posting_date }}</option>
				</select>
				<select v-if="newReturn.against_invoice" v-model="newReturn.sales_invoice_item" class="field">
					<option value="">{{ __("Item…") }}</option>
					<option v-for="l in returnLines" :key="l.sales_invoice_item" :value="l.sales_invoice_item">
						{{ l.item_name }} · {{ __("up to") }} {{ qty(l.returnable_qty) }} {{ l.uom }} · {{ money(l.rate) }}
					</option>
				</select>
				<template v-else>
					<input v-model.trim="itemQuery" class="field" type="search" :placeholder="__('Search item')" @input="searchReturnItems" />
					<select v-if="itemResults.length" v-model="newReturn.item_code" class="field">
						<option value="">{{ __("Item…") }}</option>
						<option v-for="it in itemResults" :key="it.item_code" :value="it.item_code">{{ it.item_name }}</option>
					</select>
				</template>
				<div class="grid grid-cols-2 gap-2">
					<input v-model.number="newReturn.qty" class="field" type="number" inputmode="decimal" min="0" :placeholder="__('Qty')" />
					<select v-model="newReturn.condition" class="field">
						<option value="Resaleable">{{ __("Resaleable") }}</option>
						<option value="Damaged">{{ __("Damaged") }}</option>
					</select>
				</div>
				<select v-model="newReturn.return_reason" class="field">
					<option value="">{{ __("Reason…") }}</option>
					<option v-for="r in returnReasons" :key="r.name" :value="r.name">{{ r.name }}</option>
				</select>
				<input v-model.trim="newReturn.remarks" class="field" :placeholder="returnRemarkRequired ? __('Remarks *') : __('Remarks (optional)')" />
				<button class="btn-secondary w-full" :disabled="!canAddReturn" @click="addReturn">+ {{ __("Add return") }}</button>
			</div>
			<div v-if="priced && returnRows.length" class="border-t border-gray-200 pt-2 text-sm">
				<div class="flex justify-between font-semibold"><span>{{ __("Return credit") }}</span><span>{{ money(priced.return_total) }}</span></div>
				<p class="text-xs text-gray-500">{{ __("No cash is paid out: the credit is set off against the invoices of this visit; the rest stays on the customer account.") }}</p>
			</div>
			<p v-if="priceError" class="text-sm text-red-700">{{ priceError }}</p>
		</div>

		<!-- 5. Collection -->
		<div v-else-if="step === 'collection'" class="card space-y-3">
			<div v-if="priced?.credit_applied" class="rounded-lg bg-green-50 p-2 text-sm text-green-800">
				{{ __("Return credit applied") }}: {{ money(priced.credit_applied) }}<span v-if="priced.credit_left > 0"> · {{ __("left on account") }} {{ money(priced.credit_left) }}</span>
			</div>
			<div v-if="form.outcome === 'Sale'">
				<label class="label">{{ __("Collect now for this invoice") }} ({{ __("due") }} {{ money(dueOnSale) }})</label>
				<input v-model.number="form.collect_amount" class="field" type="number" inputmode="decimal" min="0" :readonly="!allowCredit" />
				<p v-if="!allowCredit" class="mt-1 text-xs text-gray-500">{{ __("Cash sales only: the full total is collected.") }}</p>
			</div>
			<div>
				<div class="label">{{ __("Previous outstanding invoices") }}</div>
				<div v-if="!card.outstanding_invoices.length" class="text-sm text-gray-500">{{ __("None") }}</div>
				<div v-for="inv in card.outstanding_invoices" :key="inv.name" class="flex items-center justify-between border-t border-gray-100 py-2">
					<label class="flex items-center gap-2 text-sm">
						<input v-model="selected[inv.name]" type="checkbox" class="h-5 w-5" @change="price" />
						<span>
							<span class="block font-medium">{{ inv.name }}</span>
							<span class="block text-xs text-gray-500">
								{{ inv.posting_date }} · {{ __("due") }} {{ money(inv.outstanding_amount) }}
								<template v-if="creditOn(inv.name)"> · {{ __("credit") }} − {{ money(creditOn(inv.name)) }}</template>
							</span>
						</span>
					</label>
					<input v-if="selected[inv.name]" v-model.number="previous[inv.name]" class="field w-28" type="number" inputmode="decimal" min="0" placeholder="0" />
				</div>
			</div>
			<div class="flex justify-between border-t border-gray-200 pt-2 font-semibold">
				<span>{{ __("Total collected") }}</span><span>{{ money(totalCollected) }}</span>
			</div>
		</div>

		<!-- Review -->
		<div v-else-if="step === 'review'" class="card space-y-2 text-sm">
			<div class="flex justify-between"><span class="text-gray-500">{{ __("Outcome") }}</span><span class="font-semibold">{{ __(form.outcome) }}</span></div>
			<div v-if="form.outcome === 'No Sale'" class="flex justify-between"><span class="text-gray-500">{{ __("Reason") }}</span><span>{{ form.no_sale_reason }}</span></div>
			<div v-if="form.outcome === 'Sale'" class="flex justify-between"><span class="text-gray-500">{{ __("Invoice total") }}</span><span>{{ money(priced?.rounded_total) }}</span></div>
			<div v-if="returnRows.length" class="flex justify-between"><span class="text-gray-500">{{ __("Return credit") }}</span><span>{{ money(priced?.return_total) }}</span></div>
			<div v-if="priced?.credit_applied" class="flex justify-between"><span class="text-gray-500">{{ __("Credit applied") }}</span><span>{{ money(priced.credit_applied) }}</span></div>
			<div class="flex justify-between"><span class="text-gray-500">{{ __("Collected") }}</span><span>{{ money(totalCollected) }}</span></div>
			<div v-if="form.update_customer" class="text-gray-600">{{ __("Customer details will be updated.") }}</div>
			<div v-if="shelfRows.length" class="text-gray-600">{{ __("Shelf items counted") }}: {{ shelfRows.length }}</div>
			<div class="text-gray-600">{{ form.latitude ? __("Location captured") : __("No location") }}{{ photo ? " · " + __("photo attached") : "" }}</div>
		</div>

		<!-- Success -->
		<div v-else-if="done" class="card space-y-3 text-center">
			<div class="text-3xl">✅</div>
			<div class="text-lg font-semibold">{{ __("Visit saved") }} — {{ done.name }}</div>
			<div class="text-sm text-gray-600">{{ __(done.outcome) }} · {{ __("collected") }} {{ money(done.total_collected) }}</div>
			<a v-if="done.sales_invoice" class="btn-primary w-full" :href="printUrl('Sales Invoice', done.sales_invoice, 'Mobile Invoice 4in')" target="_blank">
				{{ __("Print invoice") }} {{ done.sales_invoice }}
			</a>
			<a
				v-for="note in creditNotes"
				:key="note"
				class="btn-secondary w-full"
				:href="printUrl('Sales Invoice', note, 'Mobile Invoice 4in')"
				target="_blank"
			>{{ __("Print credit note") }} {{ note }}</a>
			<a v-if="done.payment_entry" class="btn-secondary w-full" :href="printUrl('Payment Entry', done.payment_entry, 'Mobile Collection Receipt')" target="_blank">
				{{ __("Print receipt") }} {{ done.payment_entry }}
			</a>
			<p v-if="photoMessage" class="text-sm text-amber-700">{{ photoMessage }}</p>
			<router-link to="/route" class="btn-secondary w-full">{{ __("Back to route") }}</router-link>
		</div>

		<p v-if="message" class="card border-red-300 text-sm text-red-700">{{ message }}</p>

		<div v-if="!done && !loadError && card" class="flex gap-2">
			<button v-if="stepIndex > 0" class="btn-secondary flex-1" :disabled="busy" @click="go(-1)">{{ __("Back") }}</button>
			<button v-if="step !== 'review'" class="btn-primary flex-1" :disabled="!canNext" @click="go(1)">{{ __("Next") }}</button>
			<button v-else class="btn-primary flex-1" :disabled="busy || !online" @click="submit">
				{{ busy ? __("Saving…") : __("Submit visit") }}
			</button>
		</div>
	</div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from "vue"
import { call, m } from "../api"
import { loadContext } from "../context"
import { money, newClientRef, online, printUrl, qty, session } from "../state"
import { __ } from "../translation"

const props = defineProps({ customer: { type: String, required: true } })
const clientRef = newClientRef() // once per wizard session: re-submitting returns the same visit
const RETURN_OUTCOMES = ["Sale", "Collection Only", "Return Only"]
const stepLabels = {
	checkin: __("1. Check-in"),
	details: __("2. Customer details"),
	shelf: __("3. Shelf stock"),
	outcome: __("4. Outcome"),
	returns: __("4b. Returns"),
	collection: __("5. Collection"),
	review: __("Review"),
}

const trip = computed(() => session.ctx.trip)
const agent = computed(() => session.ctx.agent)
const reasons = computed(() => session.ctx.no_sale_reasons || [])
const requireGeo = computed(() => !!session.ctx.settings.require_geolocation)
const allowCredit = computed(() => !!session.ctx.settings.allow_credit_sales)
const maxDiscount = computed(() => Number(agent.value?.max_discount_pct || 0))
const returnsEnabled = computed(() => !!session.ctx.settings.returns_enabled)
const returnReasons = computed(() => session.ctx.return_reasons || [])
const outcomes = computed(() => ["Sale", "No Sale", "Collection Only", "Shop Closed", ...(returnsEnabled.value ? ["Return Only"] : [])])

const card = ref(null)
const vanItems = ref([])
const loadError = ref("")
const step = ref("checkin")
const busy = ref(false)
const message = ref("")
const done = ref(null)
const photo = ref(null)
const photoMessage = ref("")
const geoBusy = ref(false)
const geoMessage = ref("")
const shelf = ref([])
const cart = reactive({})
const discounts = reactive({})
const discountMode = reactive({})
const invoiceDiscount = reactive({ mode: "pct", value: null })
const previous = reactive({})
const selected = reactive({})
const returnRows = ref([])
const customerInvoices = ref([])
const returnLines = ref([])
const itemQuery = ref("")
const itemResults = ref([])
const newReturn = reactive({ against_invoice: "", sales_invoice_item: "", item_code: "", qty: null, condition: "Resaleable", return_reason: "", remarks: "" })
const priced = ref(null)
const priceError = ref("")
const form = reactive({
	latitude: null,
	longitude: null,
	update_customer: false,
	new_customer_name: "",
	new_contact_person: "",
	new_mobile_no: "",
	new_email: "",
	new_address_line1: "",
	new_city: "",
	new_tax_id: "",
	outcome: "",
	no_sale_reason: "",
	remarks: "",
	collect_amount: 0,
})

const isNoSale = computed(() => ["No Sale", "Shop Closed"].includes(form.outcome))
// Shop Closed needs no reason and its remarks are optional; No Sale needs a reason (and remarks if the reason says so).
const remarkRequired = computed(
	() => form.outcome === "No Sale" && !!reasons.value.find((r) => r.name === form.no_sale_reason)?.requires_remark
)
const steps = computed(() => {
	const list = ["checkin", "details", "shelf", "outcome"]
	if (returnsEnabled.value && RETURN_OUTCOMES.includes(form.outcome)) list.push("returns")
	if (RETURN_OUTCOMES.includes(form.outcome)) list.push("collection")
	return [...list, "review"]
})
const stepIndex = computed(() => steps.value.indexOf(step.value))
const contactName = computed(() => [card.value?.contact?.first_name, card.value?.contact?.last_name].filter(Boolean).join(" "))
const changeFields = computed(() => [
	{ key: "new_customer_name", label: __("Customer name"), current: card.value?.customer_name },
	{ key: "new_contact_person", label: __("Contact person"), current: contactName.value },
	{ key: "new_mobile_no", label: __("Mobile number"), current: card.value?.contact?.mobile_no, type: "tel" },
	{ key: "new_email", label: __("Email"), current: card.value?.contact?.email_id, type: "email" },
	{ key: "new_address_line1", label: __("Address line 1"), current: card.value?.address?.address_line1 },
	{ key: "new_city", label: __("City"), current: card.value?.address?.city },
	{ key: "new_tax_id", label: __("Tax ID"), current: card.value?.tax_id },
])
const cartItems = computed(() =>
	Object.entries(cart)
		.filter(([, q]) => Number(q) > 0)
		.map(([item_code, q]) => {
			const value = Number(discounts[item_code] || 0)
			const byAmount = discountMode[item_code] === "amt"
			return { item_code, qty: Number(q), discount_percentage: byAmount ? 0 : value, discount_amount: byAmount ? value : 0 }
		})
)
// Selected previous invoices: return credit is set off against them first, then the cash entered.
const previousRows = computed(() =>
	Object.entries(selected)
		.filter(([, on]) => on)
		.map(([sales_invoice]) => ({ sales_invoice, allocated: Number(previous[sales_invoice] || 0) }))
)
const returnPayload = computed(() =>
	RETURN_OUTCOMES.includes(form.outcome)
		? returnRows.value.map((r) => ({
				item_code: r.item_code,
				qty: r.qty,
				uom: r.uom,
				against_invoice: r.against_invoice || null,
				sales_invoice_item: r.sales_invoice_item || null,
				return_reason: r.return_reason,
				condition: r.condition,
				remarks: r.remarks || null,
			}))
		: []
)
const discountPayload = computed(() => {
	const value = Number(invoiceDiscount.value || 0)
	return invoiceDiscount.mode === "amt" ? { discount_amount: value } : { additional_discount_percentage: value }
})
const dueOnSale = computed(() => Number(priced.value?.due_on_sale ?? priced.value?.rounded_total ?? 0))
const creditNotes = computed(() => (done.value?.credit_notes || "").split(",").map((n) => n.trim()).filter(Boolean))
const returnRemarkRequired = computed(() => !!returnReasons.value.find((r) => r.name === newReturn.return_reason)?.requires_remark)
const canAddReturn = computed(
	() =>
		Number(newReturn.qty) > 0 &&
		!!newReturn.return_reason &&
		(!returnRemarkRequired.value || !!newReturn.remarks) &&
		(newReturn.against_invoice ? !!newReturn.sales_invoice_item : !!newReturn.item_code)
)
const shelfRows = computed(() => shelf.value.filter((r) => r.item_code))
const totalCollected = computed(
	() => (form.outcome === "Sale" ? Number(form.collect_amount || 0) : 0) + previousRows.value.reduce((s, r) => s + r.allocated, 0)
)
const canNext = computed(() => {
	if (step.value === "checkin") return !requireGeo.value || !!form.latitude
	if (step.value === "outcome") {
		if (!form.outcome) return false
		if (form.outcome === "Shop Closed") return true
		if (isNoSale.value) return !!form.no_sale_reason && (!remarkRequired.value || !!form.remarks)
		if (form.outcome === "Sale") return !!priced.value && cartItems.value.length > 0 && !priceError.value && priced.value.lines.every((l) => l.enough_stock)
		return true
	}
	if (step.value === "returns") return !priceError.value && (form.outcome !== "Return Only" || returnRows.value.length > 0)
	if (step.value === "collection" && form.outcome === "Collection Only")
		return previousRows.value.some((r) => r.allocated > 0) || Number(priced.value?.credit_applied || 0) > 0
	return true
})

function lineFor(item_code) {
	return priced.value?.lines.find((l) => l.item_code === item_code)
}

function returnLine(index) {
	return priced.value?.returns?.[index]
}

function creditOn(invoice) {
	return Number(priced.value?.credit_on_previous?.[invoice] || 0)
}

async function loadReturnLines() {
	newReturn.sales_invoice_item = ""
	returnLines.value = []
	if (!newReturn.against_invoice) return
	try {
		returnLines.value = await call(m("get_returnable_lines"), { invoice: newReturn.against_invoice, customer: props.customer })
	} catch (e) {
		message.value = e.message
	}
}

let itemTimer = null
function searchReturnItems() {
	clearTimeout(itemTimer)
	itemTimer = setTimeout(async () => {
		try {
			itemResults.value = await call(m("search_items"), { q: itemQuery.value })
		} catch (e) {
			message.value = e.message
		}
	}, 300)
}

function addReturn() {
	const line = returnLines.value.find((l) => l.sales_invoice_item === newReturn.sales_invoice_item)
	const item = itemResults.value.find((it) => it.item_code === newReturn.item_code)
	returnRows.value.push({
		...newReturn,
		item_code: line ? line.item_code : newReturn.item_code,
		item_name: line ? line.item_name : item?.item_name,
		uom: line ? line.uom : item?.stock_uom,
		qty: Number(newReturn.qty),
	})
	Object.assign(newReturn, { sales_invoice_item: "", item_code: "", qty: null, condition: "Resaleable", return_reason: "", remarks: "" })
	price()
}

function removeReturn(index) {
	returnRows.value.splice(index, 1)
	price()
}

function go(delta) {
	message.value = ""
	const next = steps.value[stepIndex.value + delta]
	if (!next) return
	step.value = next
	if (next === "collection") price().then(() => (form.collect_amount = form.outcome === "Sale" ? dueOnSale.value : 0))
}

function bump(item, delta) {
	cart[item.item_code] = Math.max(0, Number(cart[item.item_code] || 0) + delta)
	schedulePrice()
}

let priceTimer = null
function schedulePrice() {
	clearTimeout(priceTimer)
	priceTimer = setTimeout(price, 350)
}

async function price() {
	priceError.value = ""
	const items = form.outcome === "Sale" ? cartItems.value : []
	if (!items.length && !returnPayload.value.length) {
		priced.value = null
		return
	}
	try {
		priced.value = await call(m("price_cart"), {
			trip: trip.value.name,
			customer: props.customer,
			items,
			discount: discountPayload.value,
			returns_items: returnPayload.value,
			collect_previous: previousRows.value,
		})
	} catch (e) {
		priced.value = null
		priceError.value = e.message
	}
}

function captureLocation() {
	if (!navigator.geolocation) {
		geoMessage.value = __("This phone cannot share its location.")
		return
	}
	geoBusy.value = true
	navigator.geolocation.getCurrentPosition(
		(pos) => {
			form.latitude = pos.coords.latitude
			form.longitude = pos.coords.longitude
			geoBusy.value = false
		},
		(err) => {
			geoMessage.value = __("Location not available: {0}", [err.message])
			geoBusy.value = false
		},
		{ enableHighAccuracy: true, timeout: 15000 }
	)
}

function takePhoto(event) {
	const file = event.target.files?.[0]
	if (!file) return
	const img = new Image()
	img.onload = () => {
		// Shrink to at most 1280 px and JPEG 0.8: well under the 5 MB server limit.
		const scale = Math.min(1, 1280 / Math.max(img.width, img.height))
		const canvas = document.createElement("canvas")
		canvas.width = Math.round(img.width * scale)
		canvas.height = Math.round(img.height * scale)
		canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height)
		photo.value = canvas.toDataURL("image/jpeg", 0.8)
		URL.revokeObjectURL(img.src)
	}
	img.src = URL.createObjectURL(file)
}

async function submit() {
	if (busy.value) return // double-tap protection
	busy.value = true
	message.value = ""
	const payload = {
		client_ref: clientRef,
		mobile_trip: trip.value.name,
		customer: props.customer,
		outcome: form.outcome,
		latitude: form.latitude,
		longitude: form.longitude,
		no_sale_reason: form.outcome === "No Sale" ? form.no_sale_reason : null,
		remarks: form.remarks || null,
		update_customer: form.update_customer ? 1 : 0,
		sale_items: form.outcome === "Sale" ? cartItems.value : [],
		...(form.outcome === "Sale" ? discountPayload.value : {}),
		return_items: returnPayload.value,
		collect_amount: form.outcome === "Sale" ? Number(form.collect_amount || 0) : 0,
		collect_previous: RETURN_OUTCOMES.includes(form.outcome) ? previousRows.value : [],
		shelf_stock: shelfRows.value,
	}
	if (form.update_customer) for (const f of changeFields.value) if (form[f.key]) payload[f.key] = form[f.key]
	try {
		const result = await call(m("submit_visit"), { payload })
		if (photo.value) {
			try {
				await call(m("upload_visit_photo"), { visit: result.name, filename: "check-in.jpg", filedata: photo.value })
			} catch (e) {
				photoMessage.value = __("Visit saved, but the photo could not be uploaded: {0}", [e.message])
			}
		}
		done.value = result
		step.value = "done"
		loadContext()
	} catch (e) {
		message.value = e.message
	} finally {
		busy.value = false
	}
}

onMounted(async () => {
	if (!trip.value || trip.value.status !== "In Field") {
		loadError.value = __("Visits can only be recorded while the trip is In Field.")
		return
	}
	try {
		;[card.value, vanItems.value, customerInvoices.value] = await Promise.all([
			call(m("get_customer"), { customer: props.customer }),
			call(m("get_van_stock"), { trip: trip.value.name }),
			returnsEnabled.value ? call(m("get_customer_invoices"), { customer: props.customer }) : Promise.resolve([]),
		])
		captureLocation()
	} catch (e) {
		loadError.value = e.message
	}
})
</script>
