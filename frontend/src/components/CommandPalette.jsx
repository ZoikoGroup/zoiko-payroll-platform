import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Search, CornerDownLeft, Command } from "lucide-react";
import { NAV_GROUPS } from "./superAdminNav";

function normalize(value) {
  return value.toLowerCase().replace(/_/g, " ").trim();
}

function fuzzyScore(queryTokens, haystack) {
  const target = normalize(haystack);
  let score = 0;
  for (const token of queryTokens) {
    if (target.startsWith(token)) score += 3;
    else if (target.includes(token)) score += 1;
    else return -1;
  }
  return score;
}

export default function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef(null);
  const listRef = useRef(null);
  const navigate = useNavigate();

  const flatEntries = useMemo(
    () =>
      NAV_GROUPS.flatMap((group) =>
        group.items.map((item) => ({
          label: item.label,
          href: item.href,
          group: group.title,
          hint: `${item.href} · ${group.title}`,
        }))
      ),
    []
  );

  const queryTokens = normalize(query).split(/\s+/).filter(Boolean);

  const results = useMemo(() => {
    if (queryTokens.length === 0) return flatEntries;
    return flatEntries
      .map((entry) => ({ entry, score: fuzzyScore(queryTokens, `${entry.label} ${entry.group} ${entry.href}`) }))
      .filter((r) => r.score >= 0)
      .sort((a, b) => b.score - a.score)
      .map((r) => r.entry);
  }, [flatEntries, queryTokens]);

  useEffect(() => {
    function onKeyDown(e) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((v) => !v);
      } else if (e.key === "Escape" && open) {
        setOpen(false);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open]);

  useEffect(() => {
    if (open) {
      setQuery("");
      setActiveIndex(0);
      setTimeout(() => inputRef.current?.focus(), 10);
    }
  }, [open]);

  useEffect(() => setActiveIndex(0), [query]);

  useEffect(() => {
    if (!open || !listRef.current) return;
    const el = listRef.current.querySelector(`[data-index="${activeIndex}"]`);
    el?.scrollIntoView({ block: "nearest" });
  }, [activeIndex, open]);

  function go(entry) {
    navigate(entry.href);
    setOpen(false);
  }

  function onKeyDown(e) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((i) => Math.min(i + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (results[activeIndex]) go(results[activeIndex]);
    }
  }

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Command palette"
      className="fixed inset-0 z-[999] flex items-start justify-center bg-slate-950/50 px-4 pt-[12vh] backdrop-blur-sm"
      onClick={() => setOpen(false)}
    >
      <div
        className="w-full max-w-xl overflow-hidden rounded-2xl border border-border bg-surface shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 border-b border-border-light px-4 py-3">
          <Search size={18} className="shrink-0 text-foreground-muted" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Jump to a page… (substring match on page name, section, or URL)"
            className="w-full bg-transparent text-base text-foreground outline-none placeholder:text-foreground-disabled"
          />
          <kbd className="hidden shrink-0 items-center gap-1 rounded border border-border bg-surface-muted px-2 py-1 text-[10px] font-semibold text-foreground-muted sm:flex">
            <Command size={11} /> K
          </kbd>
        </div>

        <div ref={listRef} className="max-h-[45vh] overflow-y-auto p-2">
          {results.length === 0 && (
            <p className="px-3 py-8 text-center text-sm text-foreground-disabled">
              No pages match “{query}”.
            </p>
          )}
          {results.map((entry, i) => (
            <button
              key={entry.href}
              type="button"
              data-index={i}
              onClick={() => go(entry)}
              onMouseMove={() => setActiveIndex(i)}
              className={`flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2.5 text-left text-sm transition ${
                i === activeIndex ? "bg-primary-light/60 text-foreground" : "text-foreground-secondary"
              }`}
            >
              <span className="min-w-0">
                <span className="block truncate font-medium">{entry.label}</span>
                <span className="block truncate text-xs text-foreground-muted">{entry.hint}</span>
              </span>
              {i === activeIndex && (
                <kbd className="flex shrink-0 items-center gap-1 rounded border border-border bg-surface-muted px-1.5 py-0.5 text-[10px] font-semibold text-foreground-muted">
                  <CornerDownLeft size={11} /> open
                </kbd>
              )}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-3 border-t border-border-light px-4 py-2 text-[11px] text-foreground-muted">
          <span><kbd className="rounded border border-border bg-surface-muted px-1.5 py-0.5">↑↓</kbd> navigate</span>
          <span><kbd className="rounded border border-border bg-surface-muted px-1.5 py-0.5">Enter</kbd> open</span>
          <span><kbd className="rounded border border-border bg-surface-muted px-1.5 py-0.5">Esc</kbd> close</span>
        </div>
      </div>
    </div>
  );
}