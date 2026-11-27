// Shared by the *-ui-validation scripts: "this country has a flag".
//
// Flags come from the bundled flag-icons package through
// components/jurisdiction/CountryFlag.jsx (utils/countryFlags.js), never from
// emoji or hand-drawn SVGs, so a country has a flag when flag-icons ships its
// ISO code and the component still resolves flags through getFlagUrl.
import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const FRONTEND = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const ALIASES = { uk: "gb" };

export function hasBundledFlag(code) {
  const iso = ALIASES[String(code).toLowerCase()] || String(code).toLowerCase();
  const component = readFileSync(resolve(FRONTEND, "src/components/jurisdiction/CountryFlag.jsx"), "utf-8");
  const lookup = readFileSync(resolve(FRONTEND, "src/utils/countryFlags.js"), "utf-8");
  return component.includes("getFlagUrl(code)")
    && lookup.includes("/node_modules/flag-icons/flags/4x3/*.svg")
    && existsSync(resolve(FRONTEND, "node_modules/flag-icons/flags/4x3", `${iso}.svg`));
}
