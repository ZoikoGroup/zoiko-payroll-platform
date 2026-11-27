import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Check, ChevronDown, Globe2, Search } from "lucide-react";

import CountryFlag from "./CountryFlag";

// A country picker that shows each country's flag — a native <select> can't
// draw images in its options. Used by the registration country field, the
// phone calling-code selector, the dashboard country filter and the
// "Add country" dialog.
//
//   <CountrySelect value={code} onChange={setCode} options={[{ value, label, code, hint }]} />
//
// * options: `value` is what onChange receives; `code` picks the flag (an
//   option without one, e.g. "All countries", shows a globe); `hint` is
//   extra text on the right (a calling code, a currency, "set-up pending").
// * variant: "app" (theme tokens, follows light/dark mode) or "auth" (the
//   always-light sign-in / sign-up pages).
// * compact: show only the flag and `selectedLabel` in the button (the phone
//   code selector).
// * The list opens in a portal with fixed positioning, so a scrolling card or
//   a modal never clips it; it flips above the button when there's no room.
//   Keyboard: arrows, Home/End, Enter, Escape, and type to filter when the
//   list is long enough to search.

const PALETTES = {
  app: {
    button: "border-border bg-background text-foreground hover:border-border-strong",
    placeholder: "text-foreground-muted",
    focus: "focus-visible:border-primary focus-visible:ring-2 focus-visible:ring-primary/20",
    invalid: "border-error!",
    panel: "border-border bg-surface text-foreground shadow-[0_12px_32px_rgba(0,0,0,0.18)]",
    search: "border-border bg-background text-foreground placeholder:text-foreground-muted",
    active: "bg-surface-muted",
    selected: "text-primary font-semibold",
    hint: "text-foreground-muted",
    icon: "text-foreground-muted",
  },
  auth: {
    button: "border-slate-200 bg-white text-slate-900 hover:border-slate-300",
    placeholder: "text-slate-400",
    focus: "focus-visible:border-blue-600 focus-visible:ring-2 focus-visible:ring-blue-600/15",
    invalid: "border-red-400!",
    panel: "border-slate-200 bg-white text-slate-900 shadow-[0_16px_40px_-12px_rgba(15,23,42,0.35)]",
    search: "border-slate-200 bg-white text-slate-900 placeholder:text-slate-400",
    active: "bg-slate-100",
    selected: "text-blue-700 font-semibold",
    hint: "text-slate-500",
    icon: "text-slate-500",
  },
};

const PANEL_MAX_HEIGHT = 288;

function OptionFlag({ option, size = "sm" }) {
  return option?.code
    ? <CountryFlag code={option.code} name={option.label} size={size} decorative />
    : <Globe2 size={size === "sm" ? 16 : 18} className="shrink-0 opacity-70" aria-hidden="true" />;
}

export default function CountrySelect({
  id,
  value,
  onChange,
  options,
  placeholder = "Select country",
  variant = "app",
  disabled = false,
  invalid = false,
  describedBy,
  required = false,
  ariaLabel,
  compact = false,
  selectedLabel,
  searchable,
  className = "",
  buttonClassName = "",
  panelMinWidth = 260,
  testId,
}) {
  const palette = PALETTES[variant] || PALETTES.app;
  const listId = useId();
  const buttonRef = useRef(null);
  const panelRef = useRef(null);
  const searchRef = useRef(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(-1);
  const [position, setPosition] = useState(null);

  const canSearch = searchable ?? options.length > 8;
  const selected = options.find((o) => o.value === value) || null;
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return options;
    return options.filter((o) => `${o.label} ${o.hint || ""} ${o.code || ""}`.toLowerCase().includes(q));
  }, [options, query]);

  function openList() {
    if (disabled) return;
    setQuery("");
    setActiveIndex(Math.max(0, options.findIndex((o) => o.value === value)));
    setOpen(true);
  }

  function close({ focusButton = true } = {}) {
    setOpen(false);
    setPosition(null);
    if (focusButton) buttonRef.current?.focus();
  }

  function choose(option) {
    if (!option || option.disabled) return;
    onChange(option.value);
    close();
  }

  // Place the panel under (or above) the button, and keep it there while
  // anything scrolls or the window resizes.
  useLayoutEffect(() => {
    if (!open) return undefined;
    function place() {
      const rect = buttonRef.current?.getBoundingClientRect();
      if (!rect) return;
      const width = Math.max(rect.width, panelMinWidth);
      const left = Math.min(Math.max(8, rect.left), window.innerWidth - width - 8);
      const below = window.innerHeight - rect.bottom - 8;
      const above = rect.top - 8;
      const upward = below < Math.min(PANEL_MAX_HEIGHT, 200) && above > below;
      setPosition({
        left,
        width: Math.min(width, window.innerWidth - 16),
        maxHeight: Math.max(140, Math.min(PANEL_MAX_HEIGHT, (upward ? above : below) - 4)),
        ...(upward ? { bottom: window.innerHeight - rect.top + 4 } : { top: rect.bottom + 4 }),
      });
    }
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [open, panelMinWidth]);

  // Close on a click anywhere else.
  useEffect(() => {
    if (!open) return undefined;
    function onPointerDown(e) {
      if (buttonRef.current?.contains(e.target) || panelRef.current?.contains(e.target)) return;
      close({ focusButton: false });
    }
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  // Focus the search box once the panel exists (it renders after placement).
  const placed = Boolean(position);
  useEffect(() => {
    if (open && placed && canSearch) searchRef.current?.focus();
  }, [open, placed, canSearch]);

  // Keep the highlighted option in view.
  useEffect(() => {
    if (!open || activeIndex < 0) return;
    panelRef.current?.querySelector(`[data-index="${activeIndex}"]`)?.scrollIntoView({ block: "nearest" });
  }, [open, activeIndex]);

  function onKeyDown(e) {
    if (!open) {
      if (["ArrowDown", "ArrowUp", "Enter", " "].includes(e.key)) {
        e.preventDefault();
        openList();
      }
      return;
    }
    const last = filtered.length - 1;
    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        setActiveIndex((i) => Math.min(last, i + 1));
        break;
      case "ArrowUp":
        e.preventDefault();
        setActiveIndex((i) => Math.max(0, i - 1));
        break;
      case "Home":
        e.preventDefault();
        setActiveIndex(0);
        break;
      case "End":
        e.preventDefault();
        setActiveIndex(last);
        break;
      case "Enter":
        e.preventDefault();
        choose(filtered[activeIndex]);
        break;
      case " ":
        if (!canSearch) {
          e.preventDefault();
          choose(filtered[activeIndex]);
        }
        break;
      case "Escape":
        e.preventDefault();
        close();
        break;
      case "Tab":
        close({ focusButton: false });
        break;
      default:
        // Without a search box, typing jumps to the first matching country.
        if (!canSearch && e.key.length === 1) {
          const k = e.key.toLowerCase();
          const idx = filtered.findIndex((o) => o.label.toLowerCase().startsWith(k));
          if (idx >= 0) setActiveIndex(idx);
        }
    }
  }

  const activeId = open && filtered[activeIndex] ? `${listId}-opt-${activeIndex}` : undefined;
  const buttonText = selected ? (compact ? selectedLabel ?? selected.label : selected.label) : placeholder;

  return (
    <div className={`relative ${className}`}>
      <button
        ref={buttonRef}
        id={id}
        type="button"
        disabled={disabled}
        onClick={() => (open ? close() : openList())}
        onKeyDown={onKeyDown}
        role="combobox"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        aria-activedescendant={canSearch ? undefined : activeId}
        aria-invalid={invalid || undefined}
        aria-describedby={describedBy}
        aria-required={required || undefined}
        aria-label={ariaLabel}
        data-testid={testId}
        title={selected?.label}
        className={`flex h-11 w-full items-center gap-2.5 rounded-lg border text-left text-[15px] outline-none transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${
          compact ? "pl-3 pr-2" : "pl-3.5 pr-3"} ${palette.button} ${palette.focus} ${invalid ? palette.invalid : ""} ${buttonClassName}`}
      >
        {selected ? <OptionFlag option={selected} /> : <Globe2 size={17} className={`shrink-0 ${palette.icon}`} aria-hidden="true" />}
        <span className={`min-w-0 flex-1 truncate ${selected ? "" : palette.placeholder}`}>{buttonText}</span>
        {!compact && selected?.hint && <span className={`shrink-0 text-[13px] ${palette.hint}`}>{selected.hint}</span>}
        <ChevronDown size={16} className={`shrink-0 transition-transform ${open ? "rotate-180" : ""} ${palette.icon}`} aria-hidden="true" />
      </button>

      {open && position && createPortal(
        <div
          ref={panelRef}
          style={{ position: "fixed", left: position.left, width: position.width, top: position.top, bottom: position.bottom, zIndex: 1000 }}
          className={`flex flex-col overflow-hidden rounded-xl border ${palette.panel}`}
        >
          {canSearch && (
            <div className="relative border-b border-inherit p-2">
              <Search size={15} className={`pointer-events-none absolute left-4.5 top-1/2 -translate-y-1/2 ${palette.icon}`} aria-hidden="true" />
              <input
                ref={searchRef}
                value={query}
                onChange={(e) => { setQuery(e.target.value); setActiveIndex(0); }}
                onKeyDown={onKeyDown}
                role="combobox"
                aria-expanded="true"
                aria-controls={listId}
                aria-activedescendant={activeId}
                aria-autocomplete="list"
                aria-label="Search countries"
                placeholder="Search countries"
                className={`h-9 w-full rounded-lg border pl-8 pr-3 text-[14px] outline-none ${palette.search}`}
              />
            </div>
          )}
          <ul id={listId} role="listbox" aria-label={ariaLabel || placeholder} style={{ maxHeight: position.maxHeight }}
            className="overflow-y-auto py-1" tabIndex={-1}>
            {filtered.length === 0 && (
              <li className={`px-3.5 py-2.5 text-[14px] ${palette.hint}`}>No countries match &ldquo;{query}&rdquo;</li>
            )}
            {filtered.map((option, index) => {
              const isSelected = option.value === value;
              return (
                <li
                  key={option.value}
                  id={`${listId}-opt-${index}`}
                  data-index={index}
                  role="option"
                  aria-selected={isSelected}
                  aria-disabled={option.disabled || undefined}
                  onPointerDown={(e) => e.preventDefault()}
                  onClick={() => choose(option)}
                  onPointerMove={() => setActiveIndex(index)}
                  className={`mx-1 flex cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-2 text-[14px] ${
                    index === activeIndex ? palette.active : ""} ${isSelected ? palette.selected : ""} ${option.disabled ? "cursor-not-allowed opacity-50" : ""}`}
                >
                  <OptionFlag option={option} />
                  <span className="min-w-0 flex-1 truncate">{option.label}</span>
                  {option.hint && <span className={`shrink-0 text-[12px] font-normal ${palette.hint}`}>{option.hint}</span>}
                  {isSelected && <Check size={14} className="shrink-0" aria-hidden="true" />}
                </li>
              );
            })}
          </ul>
        </div>,
        document.body,
      )}
    </div>
  );
}
