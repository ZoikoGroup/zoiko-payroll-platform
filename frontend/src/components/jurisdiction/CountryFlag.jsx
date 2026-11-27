import { getFlagUrl } from "../../utils/countryFlags";

// The one country flag component — use it wherever a country is shown
// (country cards, pickers, the phone code selector, the header).
//
// Renders the bundled flag-icons SVG (see utils/countryFlags.js), never a
// flag emoji: Windows can't draw flag emoji and shows the letters instead.
//
//   <CountryFlag code="IN" name="India" size="md" />
//
// * `size` — "xs" 16x12, "sm" 20x15, "md" 24x18, "lg" 32x24, "xl" 40x30
//   (all 4:3). Leave it out and pass sizing classes instead, e.g.
//   className="h-full w-full" to fill a box (the flag is then cropped to the
//   box like a cover image).
// * `name` — the country's name: the image's alt text and tooltip.
// * `fallback` — what to show when there is no flag for the code; by
//   default the code itself in a small neutral badge of the same size.
// * `decorative` — the country is already named next to the flag: the
//   image is hidden from screen readers (alt="").
//
// A thin inner ring keeps white flags (Japan, Poland …) defined on white
// cards and light flags visible on dark surfaces in dark mode.

const SIZES = {
  xs: "h-3 w-4",
  sm: "h-[15px] w-5",
  md: "h-[18px] w-6",
  lg: "h-6 w-8",
  xl: "h-[30px] w-10",
};

const TEXT_SIZES = { xs: "text-[7px]", sm: "text-[8px]", md: "text-[9px]", lg: "text-[11px]", xl: "text-[13px]" };

export default function CountryFlag({
  code,
  name,
  size,
  className = "",
  fallback,
  decorative = false,
  title,
}) {
  const url = getFlagUrl(code);
  const sizeClass = size ? SIZES[size] || SIZES.md : "";
  const label = name || String(code || "").toUpperCase();
  const tooltip = title === undefined ? name || undefined : title || undefined;

  if (!url) {
    if (fallback !== undefined) return fallback;
    if (!code) return null;
    return (
      <span
        role={decorative ? undefined : "img"}
        aria-label={decorative ? undefined : label}
        aria-hidden={decorative ? "true" : undefined}
        title={tooltip}
        className={`inline-flex shrink-0 items-center justify-center rounded-[3px] bg-slate-200 font-bold uppercase leading-none text-slate-600 dark:bg-slate-700 dark:text-slate-200 ${
          sizeClass} ${size ? TEXT_SIZES[size] || TEXT_SIZES.md : "text-[10px]"} ${className}`}
      >
        {String(code).toUpperCase().slice(0, 3)}
      </span>
    );
  }

  return (
    <span
      title={tooltip}
      className={`relative inline-flex shrink-0 overflow-hidden rounded-[3px] bg-slate-100 align-middle dark:bg-slate-800 ${sizeClass} ${className}`}
    >
      <img
        src={url}
        alt={decorative ? "" : `${label} flag`}
        width={32}
        height={24}
        loading="lazy"
        decoding="async"
        draggable="false"
        className="h-full w-full object-cover"
      />
      <span aria-hidden="true" className="pointer-events-none absolute inset-0 rounded-[inherit] ring-1 ring-inset ring-black/10 dark:ring-white/20" />
    </span>
  );
}
