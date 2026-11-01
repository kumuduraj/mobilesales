import path from "path"
import { defineConfig } from "vitest/config"
import vue from "@vitejs/plugin-vue"

// Mount test only (CLAUDE.md rule 18); the app build itself is vite.config.js.
export default defineConfig({
	plugins: [vue()],
	resolve: { alias: { "@": path.resolve(__dirname, "src") } },
	test: { environment: "happy-dom", include: ["tests/**/*.test.js"], css: false },
})
