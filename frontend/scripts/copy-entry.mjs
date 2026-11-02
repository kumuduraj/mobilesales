// Publish the build entry points where Frappe serves them:
//   index.html -> mobilesales/www/mobile-sales.html      (Jinja host page, /mobile-sales)
//   sw.js      -> mobilesales/www/mobile-sales-sw.min.js (root-level service worker; "min.js" is served
//                                                          verbatim by Frappe's TemplatePage, no Jinja)
import { copyFileSync, readFileSync, writeFileSync } from "fs"

const BASE = "/assets/mobilesales/frontend/"
const out = "../mobilesales/public/frontend"

// vite-plugin-pwa adds manifest.webmanifest to the precache list after URL prefixing; served from the
// site root the worker would request /manifest.webmanifest (404) and fail to install.
const sw = readFileSync(`${out}/sw.js`, "utf8").replaceAll('"url":"manifest.webmanifest"', `"url":"${BASE}manifest.webmanifest"`)
if (!sw.includes(`"url":"${BASE}manifest.webmanifest"`)) throw new Error("manifest precache entry not found in sw.js")
writeFileSync(`${out}/sw.js`, sw)
writeFileSync("../mobilesales/www/mobile-sales-sw.min.js", sw)
copyFileSync(`${out}/index.html`, "../mobilesales/www/mobile-sales.html")
console.log("published mobile-sales.html and mobile-sales-sw.min.js into mobilesales/www")
