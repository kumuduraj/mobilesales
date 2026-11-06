<template>
	<div class="space-y-3">
		<div class="card">
			<input v-model="q" class="field" type="search" :placeholder="__('Search any customer (name, mobile, address or city)')" @input="search" />
			<div v-for="c in results" :key="c.name" class="search-result flex items-center justify-between border-t border-gray-100 py-2">
				<div class="min-w-0">
					<div class="font-medium">{{ c.customer_name }}</div>
					<div v-if="customerLine(c)" class="customer-line text-xs text-gray-500">{{ customerLine(c) }}</div>
					<div v-if="Number(c.outstanding)" class="balance text-xs" :class="balance(c.outstanding).credit ? 'text-green-700' : 'text-gray-500'">
						{{ balance(c.outstanding).label }}: {{ balance(c.outstanding).text }}
					</div>
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
			<div
				v-for="(c, i) in plan"
				:key="c.customer"
				class="route-row border-t border-gray-100 py-3 first:border-0"
				:class="{ 'route-next -mx-2 rounded-lg border-0 bg-amber-50 px-2 ring-2 ring-amber-400': next && c.customer === next.customer }"
				:data-customer="c.customer"
			>
				<button class="flex w-full items-center justify-between text-left" :disabled="!canVisit" @click="open(c.customer)">
					<div class="min-w-0">
						<div class="font-medium">
							<span class="route-number mr-1 text-gray-400">{{ c.sequence || i + 1 }}.</span>{{ c.customer_name }}
							<span v-if="next && c.customer === next.customer" class="next-badge ml-1 rounded bg-amber-400 px-1.5 py-0.5 text-xs font-bold text-gray-900">{{ __("NEXT") }}</span>
							<span v-if="c.visited" class="visited ml-1 text-green-700">✓ <span class="text-xs">{{ __(c.outcome || "Visited") }}</span></span>
						</div>
						<div v-if="customerLine(c)" class="customer-line text-xs text-gray-500">{{ customerLine(c) }}</div>
						<div class="balance text-xs" :class="balance(c.outstanding).credit ? 'text-green-700' : 'text-gray-500'">
							{{ balance(c.outstanding).label }}: {{ balance(c.outstanding).text }}
						</div>
					</div>
					<span class="text-gray-400">›</span>
				</button>
				<button v-if="next && c.customer === next.customer && canVisit" class="btn-primary start-visit mt-2 w-full" @click="open(c.customer)">
					{{ __("Start visit") }}
				</button>
			</div>
			<p v-if="trip && !canVisit" class="mt-2 text-sm text-gray-500">{{ __("Start the trip to record visits.") }}</p>
			<p v-else-if="plan.length && !next" class="mt-2 text-sm text-green-700">{{ __("Every route customer is visited.") }}</p>
		</div>
		<p v-if="message" class="text-sm text-red-700">{{ message }}</p>
	</div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue"
import { useRouter } from "vue-router"
import { call, m } from "../api"
import { onReconnect } from "../connection"
import NewCustomer from "../components/NewCustomer.vue"
import { balance, customerLine, session } from "../state"

const router = useRouter()
const trip = computed(() => session.ctx?.trip)
const canVisit = computed(() => trip.value?.status === "In Field")
const plan = ref([])
// NEXT: the first customer in route order due today and not visited yet (else the first not visited); the
// agent may visit in any order, NEXT just moves on
const next = computed(() => plan.value.find((c) => c.due !== false && !c.visited) || plan.value.find((c) => !c.visited) || null)
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

async function loadPlan() {
	if (!trip.value) return
	try {
		plan.value = await call(m("get_route_plan"), { trip: trip.value.name })
	} catch (e) {
		message.value = e.message
	}
}

onMounted(loadPlan)
onReconnect(loadPlan)
</script>
