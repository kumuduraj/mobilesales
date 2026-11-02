<template>
	<div v-if="prints.length || visit.payment_entry" class="grid grid-cols-2 gap-2">
		<a
			v-for="p in prints"
			:key="p.key"
			:class="[p.primary ? 'btn-primary col-span-2' : 'btn-secondary', 'min-h-[44px] text-sm']"
			:href="p.url"
			:data-print="p.key"
			target="_blank"
		>{{ p.label }}</a>
		<a
			v-if="visit.payment_entry"
			class="btn-secondary min-h-[44px] text-sm"
			data-print="receipt"
			:href="printUrl('Payment Entry', visit.payment_entry, 'Mobile Collection Receipt')"
			target="_blank"
		>{{ __("Receipt") }}</a>
	</div>
</template>

<script setup>
import { computed } from "vue"
import { printUrl, visitPrints } from "../state"

const props = defineProps({ visit: { type: Object, required: true } })
const prints = computed(() => visitPrints(props.visit))
</script>
