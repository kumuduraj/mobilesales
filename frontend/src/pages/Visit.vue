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
				<div>
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
						<span class="text-gray-500">{{ __("Discount %") }} (≤ {{ maxDiscount }})</span>
						<input v-model.number="discounts[it.item_code]" class="field w-20" type="number" inputmode="decimal" min="0" :max="maxDiscount" @input="schedulePrice" />
					</div>
					<div v-if="lineFor(it.item_code)" class="mt-1 text-sm text-gray-600">
						{{ qty(lineFor(it.item_code).qty) }} × {{ money(lineFor(it.item_code).rate) }} = {{ money(lineFor(it.item_code).amount) }}
						<span v-if="!lineFor(it.item_code).enough_stock" class="ml-1 font-medium text-red-700">{{ __("not enough in van") }}</span>
					</div>
				</div>
				<div v-if="priced" class="border-t border-gray-200 pt-2 text-sm">
					<div class="flex justify-between"><span>{{ __("Net total") }}</span><span>{{ money(priced.net_total) }}</span></div>
					<div v-for="t in priced.taxes" :key="t.description" class="flex justify-between text-gray-600"><span>{{ t.description }}</span><span>{{ money(t.amount) }}</span></div>
					<div class="flex justify-between text-base font-semibold"><span>{{ __("Total") }}</span><span>{{ money(priced.rounded_total) }}</span></div>
				</div>
				<p v-if="priceError" class="text-sm text-red-700">{{ priceError }}</p>
			</div>
		</div>

		<!-- 5. Collection -->
		<div v-else-if="step === 'collection'" class="card space-y-3">
			<div v-if="form.outcome === 'Sale'">
				<label class="label">{{ __("Collect now for this invoice") }} ({{ __("total") }} {{ money(priced?.rounded_total) }})</label>
				<input v-model.number="form.collect_amount" class="field" type="number" inputmode="decimal" min="0" :readonly="!allowCredit" />
				<p v-if="!allowCredit" class="mt-1 text-xs text-gray-500">{{ __("Cash sales only: the full total is collected.") }}</p>
			</div>
			<div>
				<div class="label">{{ __("Previous outstanding invoices") }}</div>
				<div v-if="!card.outstanding_invoices.length" class="text-sm text-gray-500">{{ __("None") }}</div>
				<div v-for="inv in card.outstanding_invoices" :key="inv.name" class="flex items-center justify-between border-t border-gray-100 py-2">
					<div class="text-sm">
						<div class="font-medium">{{ inv.name }}</div>
						<div class="text-xs text-gray-500">{{ inv.posting_date }} · {{ __("due") }} {{ money(inv.outstanding_amount) }}</div>
					</div>
					<input v-model.number="previous[inv.name]" class="field w-28" type="number" inputmode="decimal" min="0" :max="inv.outstanding_amount" placeholder="0" />
				</div>
			</div>
			<div class="flex justify-between border-t border-gray-200 pt-2 font-semibold">
				<span>{{ __("Total collected") }}</span><span>{{ money(totalCollected) }}</span>
			</div>
		</div>

		<!-- Review -->
		<div v-else-if="step === 'review'" class="card space-y-2 text-sm">
			<div class="flex justify-between"><span class="text-gray-500">{{ __("Outcome") }}</span><span class="font-semibold">{{ __(form.outcome) }}</span></div>
			<div v-if="isNoSale" class="flex justify-between"><span class="text-gray-500">{{ __("Reason") }}</span><span>{{ form.no_sale_reason }}</span></div>
			<div v-if="form.outcome === 'Sale'" class="flex justify-between"><span class="text-gray-500">{{ __("Invoice total") }}</span><span>{{ money(priced?.rounded_total) }}</span></div>
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
const outcomes = ["Sale", "No Sale", "Collection Only", "Shop Closed"]
const stepLabels = {
	checkin: __("1. Check-in"),
	details: __("2. Customer details"),
	shelf: __("3. Shelf stock"),
	outcome: __("4. Outcome"),
	collection: __("5. Collection"),
	review: __("Review"),
}

const trip = computed(() => session.ctx.trip)
const agent = computed(() => session.ctx.agent)
const reasons = computed(() => session.ctx.no_sale_reasons || [])
const requireGeo = computed(() => !!session.ctx.settings.require_geolocation)
const allowCredit = computed(() => !!session.ctx.settings.allow_credit_sales)
const maxDiscount = computed(() => Number(agent.value?.max_discount_pct || 0))

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
const previous = reactive({})
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
const remarkRequired = computed(() => reasons.value.find((r) => r.name === form.no_sale_reason)?.requires_remark)
const steps = computed(() => {
	const list = ["checkin", "details", "shelf", "outcome"]
	if (["Sale", "Collection Only"].includes(form.outcome)) list.push("collection")
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
		.map(([item_code, q]) => ({ item_code, qty: Number(q), discount_percentage: Number(discounts[item_code] || 0) }))
)
const previousRows = computed(() =>
	Object.entries(previous)
		.filter(([, a]) => Number(a) > 0)
		.map(([sales_invoice, a]) => ({ sales_invoice, allocated: Number(a) }))
)
const shelfRows = computed(() => shelf.value.filter((r) => r.item_code))
const totalCollected = computed(
	() => (form.outcome === "Sale" ? Number(form.collect_amount || 0) : 0) + previousRows.value.reduce((s, r) => s + r.allocated, 0)
)
const canNext = computed(() => {
	if (step.value === "checkin") return !requireGeo.value || !!form.latitude
	if (step.value === "outcome") {
		if (!form.outcome) return false
		if (isNoSale.value) return !!form.no_sale_reason && (!remarkRequired.value || !!form.remarks)
		if (form.outcome === "Sale") return !!priced.value && cartItems.value.length > 0 && !priceError.value && priced.value.lines.every((l) => l.enough_stock)
	}
	if (step.value === "collection" && form.outcome === "Collection Only") return previousRows.value.length > 0
	return true
})

function lineFor(item_code) {
	return priced.value?.lines.find((l) => l.item_code === item_code)
}

function go(delta) {
	message.value = ""
	const next = steps.value[stepIndex.value + delta]
	if (!next) return
	if (step.value === "outcome" && form.outcome === "Sale" && delta > 0) form.collect_amount = Number(priced.value?.rounded_total || 0)
	step.value = next
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
	if (!cartItems.value.length) {
		priced.value = null
		return
	}
	try {
		priced.value = await call(m("price_cart"), { trip: trip.value.name, customer: props.customer, items: cartItems.value })
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
		no_sale_reason: isNoSale.value ? form.no_sale_reason : null,
		remarks: form.remarks || null,
		update_customer: form.update_customer ? 1 : 0,
		sale_items: form.outcome === "Sale" ? cartItems.value : [],
		collect_amount: form.outcome === "Sale" ? Number(form.collect_amount || 0) : 0,
		collect_previous: ["Sale", "Collection Only"].includes(form.outcome) ? previousRows.value : [],
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
		;[card.value, vanItems.value] = await Promise.all([
			call(m("get_customer"), { customer: props.customer }),
			call(m("get_van_stock"), { trip: trip.value.name }),
		])
		captureLocation()
	} catch (e) {
		loadError.value = e.message
	}
})
</script>
