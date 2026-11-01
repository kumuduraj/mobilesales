<template>
	<div class="space-y-3">
		<div class="card">
			<input v-model="q" class="field" type="search" :placeholder="__('Search any customer (name or mobile)')" @input="search" />
			<div v-for="c in results" :key="c.name" class="flex items-center justify-between border-t border-gray-100 py-2">
				<div>
					<div class="font-medium">{{ c.customer_name }}</div>
					<div class="text-xs text-gray-500">{{ c.mobile_no || c.name }}</div>
				</div>
				<button class="btn-secondary min-h-[40px] px-3 text-sm" :disabled="!canVisit" @click="open(c.name)">{{ __("Visit") }}</button>
			</div>
			<button class="btn-secondary mt-3 w-full" @click="showNew = !showNew">+ {{ __("New customer") }}</button>
			<NewCustomer v-if="showNew" @created="onCreated" />
		</div>

		<div class="card">
			<div class="mb-2 font-semibold">{{ __("Today's route") }}</div>
			<div v-if="!trip" class="text-sm text-gray-500">{{ __("No trip loaded — ask the store keeper.") }}</div>
			<div v-else-if="!plan.length" class="text-sm text-gray-500">{{ __("No route customers for this trip.") }}</div>
			<button
				v-for="c in plan"
				:key="c.customer"
				class="flex w-full items-center justify-between border-t border-gray-100 py-3 text-left first:border-0"
				:disabled="!canVisit"
				@click="open(c.customer)"
			>
				<div>
					<div class="font-medium">
						<span class="mr-1 text-gray-400">{{ c.sequence }}.</span>{{ c.customer_name }}
						<span v-if="c.visited" class="ml-1 text-green-700">✓</span>
					</div>
					<div class="text-xs text-gray-500">{{ __("Outstanding") }}: {{ money(c.outstanding) }}</div>
				</div>
				<span class="text-gray-400">›</span>
			</button>
			<p v-if="trip && !canVisit" class="mt-2 text-sm text-gray-500">{{ __("Start the trip to record visits.") }}</p>
		</div>
		<p v-if="message" class="text-sm text-red-700">{{ message }}</p>
	</div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue"
import { useRouter } from "vue-router"
import { call, m } from "../api"
import NewCustomer from "../components/NewCustomer.vue"
import { money, session } from "../state"

const router = useRouter()
const trip = computed(() => session.ctx?.trip)
const canVisit = computed(() => trip.value?.status === "In Field")
const plan = ref([])
const q = ref("")
const results = ref([])
const showNew = ref(false)
const message = ref("")
let timer = null

function search() {
	clearTimeout(timer)
	timer = setTimeout(async () => {
		try {
			results.value = await call(m("search_customers"), { q: q.value })
		} catch (e) {
			message.value = e.message
		}
	}, 300)
}

function open(customer) {
	router.push({ name: "visit", params: { customer } })
}

function onCreated(customer) {
	showNew.value = false
	if (canVisit.value) open(customer.name)
	else results.value = [{ name: customer.name, customer_name: customer.customer_name }]
}

onMounted(async () => {
	if (!trip.value) return
	try {
		plan.value = await call(m("get_route_plan"), { trip: trip.value.name })
	} catch (e) {
		message.value = e.message
	}
})
</script>
