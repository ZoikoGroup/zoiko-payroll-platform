import { useEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";

// Tab row of the pack detail panel (JurisdictionLayout).
//
// Default: the original single scrolling row, markup unchanged, for every
// country that has neither `overflowTabs` nor `adaptive`.
//
// With `overflowTabs` and/or `adaptive` (opt-in per country): tabs that do not
// fit the available width, plus every overflow tab, go into a "More" menu, so
// the row never needs a horizontal scrollbar. When the selected tab sits in
// the menu, the More button shows that tab's name as the active tab.

const GAP = 4; // gap-1
const tabClass = (active) => `flex items-center gap-1.5 whitespace-nowrap border-b-2 px-3 py-2 text-xs font-medium ${
  active ? "border-primary text-primary" : "border-transparent text-foreground-muted hover:text-foreground"
}`;
const MORE = "__more";

function TabContent({ tab, labelFor }) {
  return <><tab.icon size={13} /> {labelFor(tab)}</>;
}

function MoreContent({ tab, labelFor }) {
  return <>{tab ? <><tab.icon size={13} /> {labelFor(tab)}</> : "More"} <ChevronDown size={13} aria-hidden="true" /></>;
}

function fitCount(layout, primary, overflow, activeKey) {
  if (!layout) return primary.length;
  for (let n = primary.length; n >= 0; n -= 1) {
    const menu = [...primary.slice(n), ...overflow];
    const used = primary.slice(0, n).reduce((sum, t) => sum + (layout.tab[t.key] || 0) + GAP, 0);
    const activeInMenu = menu.find((t) => t.key === activeKey);
    const reserve = menu.length ? (layout.more[activeInMenu ? activeInMenu.key : MORE] || 0) : 0;
    if (used + reserve <= layout.width) return n;
  }
  return 0;
}

function MoreMenu({ tabs, activeKey, onSelect, labelFor }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const active = tabs.find((t) => t.key === activeKey);
  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    const onKey = (e) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open]);
  return (
    <div ref={ref} className="relative ml-auto shrink-0">
      <button type="button" onClick={() => setOpen((o) => !o)} aria-haspopup="menu" aria-expanded={open}
        className={tabClass(Boolean(active))} data-testid="pack-tabs-more">
        <MoreContent tab={active} labelFor={labelFor} />
      </button>
      {open && (
        <div role="menu" className="absolute right-0 top-full z-30 mt-1 min-w-[220px] rounded-lg border border-border bg-surface py-1 shadow-lg">
          {tabs.map((t) => (
            <button key={t.key} type="button" role="menuitem" onClick={() => { setOpen(false); onSelect(t.key); }}
              className={`flex w-full items-center gap-2 px-3 py-2 text-left text-xs ${
                t.key === activeKey ? "bg-primary/10 font-semibold text-primary" : "text-foreground-secondary hover:bg-surface-muted"
              }`}>
              <t.icon size={13} /> {labelFor(t)}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function AdaptiveTabBar({ tabs, overflowTabs, activeKey, onSelect, labelFor }) {
  const barRef = useRef(null);
  const measureRef = useRef(null);
  const [layout, setLayout] = useState(null);

  useEffect(() => {
    const bar = barRef.current;
    const measure = measureRef.current;
    if (!bar || !measure || typeof ResizeObserver === "undefined") return undefined;
    const read = () => {
      const next = { width: bar.clientWidth, tab: {}, more: {} };
      measure.querySelectorAll("[data-measure]").forEach((el) => {
        const [kind, key] = el.getAttribute("data-measure").split(":");
        next[kind][key] = el.offsetWidth;
      });
      setLayout(next);
    };
    const observer = new ResizeObserver(read);
    observer.observe(bar);
    observer.observe(measure);
    return () => observer.disconnect();
  }, []);

  const n = fitCount(layout, tabs, overflowTabs, activeKey);
  const visible = tabs.slice(0, n);
  const menu = [...tabs.slice(n), ...overflowTabs];
  return (
    <div ref={barRef} className="relative mb-4 flex items-center gap-1 border-b border-border" data-testid="pack-tabs">
      {/* Off-screen copy of every tab, measured to decide what fits. */}
      <div aria-hidden="true" className="pointer-events-none invisible absolute inset-x-0 top-0 h-0 overflow-hidden">
        <div ref={measureRef} className="flex w-max">
          {tabs.map((t) => <span key={t.key} data-measure={`tab:${t.key}`} className={tabClass(false)}><TabContent tab={t} labelFor={labelFor} /></span>)}
          <span data-measure={`more:${MORE}`} className={tabClass(false)}><MoreContent labelFor={labelFor} /></span>
          {[...tabs, ...overflowTabs].map((t) => (
            <span key={`m${t.key}`} data-measure={`more:${t.key}`} className={tabClass(true)}><MoreContent tab={t} labelFor={labelFor} /></span>
          ))}
        </div>
      </div>
      {visible.map((t) => (
        <button key={t.key} onClick={() => onSelect(t.key)} className={tabClass(activeKey === t.key)}>
          <TabContent tab={t} labelFor={labelFor} />
        </button>
      ))}
      {menu.length > 0 && <MoreMenu tabs={menu} activeKey={activeKey} onSelect={onSelect} labelFor={labelFor} />}
    </div>
  );
}

export default function PackTabBar({ tabs, overflowTabs = [], adaptive = false, activeKey, onSelect, labelFor }) {
  if (adaptive || overflowTabs.length > 0) {
    return <AdaptiveTabBar tabs={tabs} overflowTabs={overflowTabs} activeKey={activeKey} onSelect={onSelect} labelFor={labelFor} />;
  }
  return (
    <div className="mb-4 flex items-center gap-1 border-b border-border overflow-x-auto">
      {tabs.map((t) => (
        <button key={t.key} onClick={() => onSelect(t.key)} className={tabClass(activeKey === t.key)}>
          <TabContent tab={t} labelFor={labelFor} />
        </button>
      ))}
    </div>
  );
}
