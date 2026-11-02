import path from "path"
import { defineConfig } from "vite"
import vue from "@vitejs/plugin-vue"
import { VitePWA } from "vite-plugin-pwa"
import frappeui from "frappe-ui/vite"

const BASE = "/assets/mobilesales/frontend/"

export default defineConfig({
	base: BASE,
	plugins: [
		frappeui({ frappeProxy: false, jinjaBootData: false, buildConfig: false }),
		vue(),
		VitePWA({
			// Service worker built as ONE bundled file; scripts/copy-entry.mjs publishes it as
			// /mobile-sales-sw.min.js (site root) so its scope can cover /mobile-sales.
			strategies: "injectManifest",
			srcDir: "src",
			filename: "sw.js",
			injectRegister: null,
			registerType: "autoUpdate",
			injectManifest: {
				globPatterns: ["**/*.{js,css,png,svg,woff2}"],
				modifyURLPrefix: { "": BASE },
				maximumFileSizeToCacheInBytes: 4 * 1024 * 1024,
			},
			manifest: {
				name: "Mobile Sales",
				short_name: "Mobile Sales",
				description: "Mobile sales: visits, invoices and collections",
				start_url: "/mobile-sales",
				scope: "/mobile-sales",
				display: "standalone",
				background_color: "#ffffff",
				theme_color: "#1f2937",
				icons: [
					{ src: `${BASE}icons/icon-192.png`, sizes: "192x192", type: "image/png", purpose: "any" },
					{ src: `${BASE}icons/icon-512.png`, sizes: "512x512", type: "image/png", purpose: "any" },
					{ src: `${BASE}icons/icon-512.png`, sizes: "512x512", type: "image/png", purpose: "maskable" },
				],
			},
		}),
	],
	resolve: { alias: { "@": path.resolve(__dirname, "src") } },
	build: {
		outDir: "../mobilesales/public/frontend",
		emptyOutDir: true,
		target: "es2018",
		sourcemap: false,
		chunkSizeWarningLimit: 1500,
	},
})
