<template>
	<div class="space-y-3">
		<div v-if="!trip" class="card text-center">
			<div class="text-lg font-semibold">{{ __("No trip loaded") }}</div>
			<p class="mt-1 text-gray-600">{{ __("No trip loaded — ask the store keeper to load your van.") }}</p>
			<button class="btn-secondary mt-4 w-full" :disabled="busy" @click="refresh">{{ __("Check again") }}</button>
		</div>

		<template v-else>
			<div class="card">
				<div class="flex items-center justify-between">
					<div>
						<div class="text-sm text-gray-500">{{ __("Trip") }}</div>
						<div class="text-lg font-semibold">{{ trip.name }}</div>
						<div class="text-sm text-gray-500">{{ trip.trip_date }} · {{ trip.route || __("No route") }}</div>
					</div>
					<span class="rounded-full bg-gray-100 px-3 py-1 text-sm font-medium">{{ __(trip.status) }}</span>
				</div>
				<button v-if="trip.status === 'Loaded'" class="btn-primary mt-4 w-full" :disabled="busy || !online" @click="action('start_trip')">
					{{ __("Start Trip") }}
				</button>
				<button v-if="trip.status === 'In Field'" class="btn-secondary mt-4 w-full" :disabled="busy || !online" @click="confirmEndDay">
					{{ __("End Day") }}
				</button>
				<router-link v-if="trip.status === 'Settling'" to="/settlement" class="btn-primary mt-4 w-full">
					{{ __("Go to Settlement") }}
				</router-link>
				<button v-if="trip.status === 'Settling'" class="btn-secondary mt-2 w-full" :disabled="busy || !online" @click="confirmReopen">
					{{ __("Reopen Trip") }}
				</button>
				<p v-if="message" class="mt-3 text-sm text-red-700">{{ message }}</p>
			</div>

			<div class="grid grid-cols-3 gap-2">
				<div class="card p-3 text-center">
					<div class="text-2xl font-semibold">{{ trip.visits || 0 }}</div>
					<div class="text-xs text-gray-500">{{ __("Visits") }}</div>
				</div>
				<div class="card p-3 text-center">
					<div class="text-base font-semibold">{{ money(trip.invoiced_amount) }}</div>
					<div class="text-xs text-gray-500">{{ __("Sales") }}</div>
				</div>
				<div class="card p-3 text-center">
					<div class="text-base font-semibold">{{ money(trip.collected_amount) }}</div>
					<div class="text-xs text-gray-500">{{ __("Collected") }}</div>
				</div>
			</div>

			<div class="card">
				<div class="mb-2 flex items-center justify-between">
					<div class="font-semibold">{{ __("Van stock") }}</div>
					<button class="text-sm text-gray-600 underline" :disabled="busy" @click="loadStock">{{ __("Refresh") }}</button>
				</div>
				<div v-if="!stock.length" class="text-sm text-gray-500">{{ __("Van is empty.") }}</div>
				<div v-for="row in stock" :key="row.item_code" class="border-t border-gray-100 py-2 first:border-0">
					<div class="flex justify-between">
						<div>
							<div class="font-medium">{{ row.item_name }}</div>
							<div class="text-xs text-gray-500">{{ row.item_code }}</div>
						</div>
						<div class="text-right font-semibold">{{ qty(row.actual_qty) }} {{ row.stock_uom }}</div>
					</div>
					<div v-for="b in row.batches" :key="b.batch_no" class="text-xs text-gray-500">{{ b.batch_no }}: {{ qty(b.qty) }}</div>
				</div>
			</div>
		</template>
	</div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue"
import { call, m } from "../api"
import { loadContext } from "../context"
import { money, online, qty, session } from "../state"
import { __ } from "../translation"

const trip = computed(() => session.ctx?.trip)
const stock = ref([])
const busy = ref(false)
const message = ref("")

async function loadStock() {
	if (!trip.value) return
	try {
		stock.value = await call(m("get_van_stock"), { trip: trip.value.name })
	} catch (e) {
		message.value = e.message
	}
}

async function refresh() {
	busy.value = true
	await loadContext()
	await loadStock()
	busy.value = false
}

async function action(method) {
	if (busy.value) return
	busy.value = true
	message.value = ""
	try {
		await call(m(method), { trip: trip.value.name })
		await loadContext()
	} catch (e) {
		message.value = e.message
	} finally {
		busy.value = false
	}
}

function confirmEndDay() {
	if (window.confirm(__("End the day? No more visits can be recorded on this trip."))) action("end_day")
}

function confirmReopen() {
	if (window.confirm(__("Reopen the trip to record more visits? A settlement not yet submitted for verification is deleted.")))
		action("reopen_trip")
}

onMounted(loadStock)
</script>
