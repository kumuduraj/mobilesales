<template>
	<div class="space-y-3">
		<div v-if="!trip" class="card text-center text-gray-500">{{ __("No open trip to settle.") }}</div>
		<div v-else-if="trip.status !== 'Settling'" class="card text-center text-gray-500">
			{{ __("Settlement opens after End Day (trip is {0}).", [__(trip.status)]) }}
		</div>
		<div v-else-if="!data" class="card text-center text-gray-500">{{ message || __("Loading…") }}</div>

		<template v-else>
			<div class="card">
				<div class="flex items-center justify-between">
					<div>
						<div class="text-sm text-gray-500">{{ __("Settlement") }}</div>
						<div class="font-semibold">{{ data.name || __("Not saved yet") }}</div>
					</div>
					<span class="rounded-full bg-gray-100 px-3 py-1 text-sm">{{ __(data.workflow_state) }}</span>
				</div>
				<p v-if="!data.editable" class="mt-2 text-sm text-gray-600">
					{{ __("Submitted for verification. The store keeper and cashier take it from here.") }}
				</p>
				<div class="mt-3 grid grid-cols-3 gap-2 text-center text-sm">
					<div><div class="font-semibold">{{ data.total_visits }}</div><div class="text-xs text-gray-500">{{ __("Visits") }}</div></div>
					<div><div class="font-semibold">{{ money(data.invoiced_amount) }}</div><div class="text-xs text-gray-500">{{ __("Invoiced") }}</div></div>
					<div><div class="font-semibold">{{ money(data.total_collected) }}</div><div class="text-xs text-gray-500">{{ __("Collected") }}</div></div>
				</div>
			</div>

			<div class="card">
				<div class="mb-2 font-semibold">{{ __("Stock to return") }}</div>
				<div v-for="row in data.stock_lines" :key="row.item_code" class="border-t border-gray-100 py-2 first:border-0">
					<div class="flex justify-between">
						<div class="font-medium">{{ row.item_name }}</div>
						<div class="text-sm text-gray-600">{{ __("Expected") }} {{ qty(row.expected_balance) }} {{ row.uom }}</div>
					</div>
					<div class="mt-2 grid grid-cols-2 gap-2">
						<div>
							<label class="label">{{ __("Returned") }}</label>
							<input v-model.number="row.returned_qty" class="field" type="number" inputmode="decimal" min="0" :disabled="!data.editable" />
						</div>
						<div>
							<label class="label">{{ __("Damaged") }}</label>
							<input v-model.number="row.damaged_qty" class="field" type="number" inputmode="decimal" min="0" :disabled="!data.editable" />
						</div>
					</div>
					<div v-if="row.has_batch_no && row.damaged_qty > 0" class="mt-2">
						<label class="label">{{ __("Damaged batch (optional)") }}</label>
						<select v-model="row.damaged_batch_no" class="field" :disabled="!data.editable">
							<option :value="null">{{ __("Oldest first") }}</option>
							<option v-for="b in batchesFor(row.item_code)" :key="b.batch_no" :value="b.batch_no">{{ b.batch_no }} ({{ qty(b.expected) }})</option>
						</select>
					</div>
					<div class="mt-1 text-sm" :class="missing(row) < 0 ? 'text-red-700' : missing(row) > 0 ? 'text-amber-700' : 'text-gray-500'">
						{{ missing(row) < 0 ? __("Excess {0} — recount", [qty(-missing(row))]) : __("Missing {0}", [qty(missing(row))]) }}
					</div>
				</div>
			</div>

			<div class="card">
				<div class="mb-2 font-semibold">{{ __("Cash") }}</div>
				<div v-for="d in data.denominations" :key="d.denomination" class="flex items-center justify-between border-t border-gray-100 py-1.5 first:border-0">
					<span class="w-24">{{ money(d.denomination) }}</span>
					<input v-model.number="d.count" class="field w-24 text-center" type="number" inputmode="numeric" min="0" :disabled="!data.editable" />
					<span class="w-28 text-right text-sm">{{ money(d.denomination * (d.count || 0)) }}</span>
				</div>
				<div class="mt-3 space-y-1 border-t border-gray-200 pt-2 text-sm">
					<div class="flex justify-between"><span>{{ __("Opening float") }}</span><span>{{ money(data.opening_cash_float) }}</span></div>
					<div class="flex justify-between"><span>{{ __("Expected cash") }}</span><span class="font-semibold">{{ money(data.expected_cash) }}</span></div>
					<div class="flex justify-between"><span>{{ __("Handing over") }}</span><span class="font-semibold">{{ money(handed) }}</span></div>
					<div class="flex justify-between" :class="variance < 0 ? 'text-red-700' : variance > 0 ? 'text-amber-700' : ''">
						<span>{{ __("Variance") }}</span><span class="font-semibold">{{ money(variance) }}</span>
					</div>
				</div>
			</div>

			<p v-if="message" class="card border-red-300 text-sm text-red-700">{{ message }}</p>
			<div v-if="data.editable" class="grid grid-cols-2 gap-2">
				<button class="btn-secondary" :disabled="busy || !online" @click="save()">{{ __("Save") }}</button>
				<button class="btn-primary" :disabled="busy || !online || hasExcess" @click="submitForVerification">
					{{ __("Submit for Verification") }}
				</button>
			</div>
		</template>
	</div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue"
import { call, m } from "../api"
import { money, online, qty, session } from "../state"
import { __ } from "../translation"

const trip = computed(() => session.ctx?.trip)
const data = ref(null)
const busy = ref(false)
const message = ref("")

const handed = computed(() => (data.value?.denominations || []).reduce((s, d) => s + d.denomination * (Number(d.count) || 0), 0))
// Display only: the server recomputes expected cash and the variance on every save.
const variance = computed(() => handed.value - Number(data.value?.expected_cash || 0))
const hasExcess = computed(() => (data.value?.stock_lines || []).some((r) => missing(r) < 0))

function missing(row) {
	return Number(row.expected_balance || 0) - Number(row.returned_qty || 0) - Number(row.damaged_qty || 0)
}

function batchesFor(item_code) {
	return (data.value?.batch_lines || []).filter((b) => b.item_code === item_code && b.expected > 0)
}

function payload() {
	return {
		stock_lines: data.value.stock_lines.map((r) => ({
			item_code: r.item_code,
			returned_qty: Number(r.returned_qty || 0),
			damaged_qty: Number(r.damaged_qty || 0),
			damaged_batch_no: r.damaged_batch_no || null,
		})),
		denominations: data.value.denominations.map((d) => ({ denomination: d.denomination, count: Number(d.count || 0) })),
		cash_handed_over: handed.value,
	}
}

async function save() {
	if (busy.value) return false
	busy.value = true
	message.value = ""
	try {
		data.value = await call(m("save_settlement"), { trip: trip.value.name, payload: payload() })
		return true
	} catch (e) {
		message.value = e.message
		return false
	} finally {
		busy.value = false
	}
}

async function submitForVerification() {
	if (busy.value) return // double-tap protection
	if (!window.confirm(__("Submit the settlement? You cannot change it afterwards."))) return
	if (!(await save())) return
	busy.value = true
	try {
		data.value = await call(m("submit_settlement_for_verification"), { settlement_name: data.value.name })
	} catch (e) {
		message.value = e.message
	} finally {
		busy.value = false
	}
}

onMounted(async () => {
	if (!trip.value || trip.value.status !== "Settling") return
	try {
		data.value = await call(m("get_settlement_draft"), { trip: trip.value.name })
	} catch (e) {
		message.value = e.message
	}
})
</script>
