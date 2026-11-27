// Country flag images from the flag-icons package (MIT), bundled with the
// app — never fetched from a CDN and never Unicode flag emoji. Windows has no
// colour flag glyphs, so emoji flags render as the bare letters ("IN", "AU");
// an SVG image looks the same on every platform.
//
// Every 4:3 flag is listed here, but `?no-inline` makes each one its own
// small static file: the bundle holds only the file names, and a browser
// downloads just the flags a page shows (then caches them, as the file names
// are content-hashed).
const FLAG_FILES = import.meta.glob("/node_modules/flag-icons/flags/4x3/*.svg", {
  eager: true,
  query: "?no-inline",
  import: "default",
});

const FLAG_URLS = Object.fromEntries(
  Object.entries(FLAG_FILES).map(([path, url]) => [path.slice(path.lastIndexOf("/") + 1, -4).toLowerCase(), url]),
);

// Codes this app uses that differ from ISO 3166-1 alpha-2.
const CODE_ALIASES = { uk: "gb" };

/** ISO 3166-1 alpha-2 code (lower-case) for an app country code, or "". */
export function normalizeFlagCode(code) {
  const lower = String(code || "").trim().toLowerCase();
  return CODE_ALIASES[lower] || lower;
}

/** URL of the country's flag image, or null when there is none. */
export function getFlagUrl(code) {
  return FLAG_URLS[normalizeFlagCode(code)] || null;
}
