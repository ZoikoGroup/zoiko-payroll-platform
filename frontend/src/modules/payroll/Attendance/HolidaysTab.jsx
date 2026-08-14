import { useState, useMemo } from "react";
import { Plus, Trash2, CalendarDays, Flag } from "lucide-react";

const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
const MONTH_FULL = ["January","February","March","April","May","June","July","August","September","October","November","December"];
const DAYS_SHORT = ["S","M","T","W","T","F","S"];

const MONTH_LETTER = ["J","F","M","A","M","J","J","A","S","O","N","D"];

function getMonthGrid(year, month) {
  const firstDay = new Date(year, month, 1).getDay();
  const totalDays = new Date(year, month + 1, 0).getDate();
  return { firstDay, totalDays };
}

function dateKey(year, month, day) {
  return `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

// Parses a full "YYYY-MM-DD" date string. Every holiday here always carries
// a full date (from the backend, or from the <input type="date"> add form) —
// this used to assume a bare "MM-DD" instead, which read the month into the
// day badge for every holiday (e.g. April 2nd and April 14th both showed "4").
function parseMD(dateStr) {
  const parts = String(dateStr || "").split("-").map(Number);
  const [, m, d] = parts.length === 3 ? parts : [null, ...parts];
  return { month: (m || 1) - 1, day: d || 1 };
}

function formatDateLong(dateStr) {
  if (!dateStr) return "";
  try {
    return new Date(dateStr + "T00:00:00").toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
  } catch { return dateStr; }
}

function MiniMonth({ year, month, holidayDates, today }) {
  const { firstDay, totalDays } = getMonthGrid(year, month);
  const cells = [];
  for (let i = 0; i < firstDay; i++) cells.push(null);
  for (let d = 1; d <= totalDays; d++) cells.push(d);

  return (
    <div className="bg-surface border border-border rounded-[12px] p-3 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
      <p className="text-[11px] font-bold text-foreground mb-2 text-center">{MONTHS[month]}</p>
      <div className="grid grid-cols-7 gap-0.5">
        {DAYS_SHORT.map((d, i) => (
          <div key={i} className="text-center text-[8px] font-bold text-foreground-muted pb-0.5">{d}</div>
        ))}
        {cells.map((day, i) => {
          if (day === null) return <div key={`e-${i}`} />;
          const dk = dateKey(year, month, day);
          const isHoliday = holidayDates.has(dk);
          const isToday = today && day === today.getDate() && month === today.getMonth() && year === today.getFullYear();
          return (
            <div
              key={dk}
              className={`text-center text-[10px] py-0.5 rounded-[4px] font-medium ${
                isToday ? "bg-primary text-white font-bold" :
                isHoliday ? "bg-warning/15 text-warning font-bold" :
                "text-foreground-muted"
              }`}
            >
              {day}
            </div>
          );
        })}
      </div>
    </div>
  );
}

const COUNTRY_NAMES = { IN: "India", US: "United States", UK: "United Kingdom", AU: "Australia", DE: "Germany", CA: "Canada" };

const CATEGORY_FILTERS = [
  { value: "all", label: "All" },
  { value: "national", label: "National" },
  { value: "company", label: "Company" },
];

export default function HolidaysTab({ holidays = [], onAdd, onDelete, year, jurisdictionCountry }) {
  const today = useMemo(() => new Date(), []);
  const [categoryFilter, setCategoryFilter] = useState("all");

  const filteredHolidays = useMemo(() => {
    if (categoryFilter === "all") return holidays;
    return holidays.filter((h) => (h.source === "company" ? "company" : "national") === categoryFilter);
  }, [holidays, categoryFilter]);

  const holidayDateSet = useMemo(() => {
    const s = new Set();
    filteredHolidays.forEach((h) => { if (h.date) s.add(h.date); });
    return s;
  }, [filteredHolidays]);

  const [showAddForm, setShowAddForm] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDate, setNewDate] = useState("");

  function handleAdd() {
    if (!newName.trim() || !newDate) return;
    onAdd?.({ name: newName.trim(), date: newDate, description: newName.trim() });
    setNewName("");
    setNewDate("");
    setShowAddForm(false);
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col lg:flex-row gap-4">
        {/* Left: Holiday list */}
        <div className="w-full lg:w-[40%] bg-surface border border-border rounded-[18px] shadow-[0_1px_3px_rgba(0,0,0,0.04)] overflow-hidden flex flex-col">
          <div className="flex items-center justify-between px-5 py-4 border-b border-border">
            <div>
              <h3 className="text-[15px] font-bold text-foreground">{year} Holidays</h3>
              <p className="text-[11px] text-foreground-muted">
                {filteredHolidays.length} holiday{filteredHolidays.length !== 1 ? "s" : ""}
                {jurisdictionCountry && ` · ${COUNTRY_NAMES[jurisdictionCountry] || jurisdictionCountry}`}
              </p>
            </div>
            <button
              onClick={() => setShowAddForm(true)}
              className="flex items-center gap-1.5 bg-primary rounded-[12px] px-3.5 py-2 text-[13px] font-bold text-white transition-all duration-200 hover:bg-primary-hover shadow-[0_2px_8px_rgba(25,197,138,0.3)]"
            >
              <Plus size={14} /> Add
            </button>
          </div>

          {/* Category filter */}
          <div className="flex items-center gap-1.5 px-5 py-2.5 border-b border-border">
            {CATEGORY_FILTERS.map((f) => (
              <button
                key={f.value}
                onClick={() => setCategoryFilter(f.value)}
                className={`rounded-[10px] px-3 py-1.5 text-[11px] font-bold transition-all duration-200 ${
                  categoryFilter === f.value
                    ? "bg-primary text-white"
                    : "bg-background text-foreground-muted hover:text-foreground-muted"
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>

          {/* Inline add form */}
          {showAddForm && (
            <div className="px-5 py-3 border-b border-border bg-background space-y-2">
              <input
                type="text"
                placeholder="Holiday name"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                className="w-full rounded-[10px] border border-border bg-surface px-3 py-2 text-[13px] text-foreground placeholder:text-foreground-muted focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/20"
              />
              <input
                type="date"
                value={newDate}
                onChange={(e) => setNewDate(e.target.value)}
                className="w-full rounded-[10px] border border-border bg-surface px-3 py-2 text-[13px] text-foreground focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/20"
              />
              <div className="flex gap-2">
                <button onClick={handleAdd} className="flex-1 bg-primary rounded-[10px] px-3 py-2 text-[12px] font-bold text-white hover:bg-primary-hover transition-colors">Add Holiday</button>
                <button onClick={() => { setShowAddForm(false); setNewName(""); setNewDate(""); }} className="rounded-[10px] border border-border bg-surface-muted px-3 py-2 text-[12px] font-semibold text-foreground-muted hover:border-primary hover:text-primary transition-colors">Cancel</button>
              </div>
            </div>
          )}

          {/* Holiday list */}
          <div className="flex-1 overflow-y-auto max-h-[500px]">
            {filteredHolidays.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-12 text-center px-4">
                <CalendarDays size={28} className="text-foreground-muted mb-2" />
                <p className="text-[13px] text-foreground-muted font-medium">No holidays added yet</p>
              </div>
            ) : (
              filteredHolidays.map((h, i) => {
                const parsed = h.date ? parseMD(h.date) : null;
                const monthIdx = parsed ? parsed.month : 0;
                const dayNum = parsed ? parsed.day : 0;
                return (
                  <div key={h.id || i} className="flex items-center gap-3 px-5 py-3 border-b border-border/50 hover:bg-background dark:hover:bg-surface-muted transition-colors group">
                    <div className="w-10 h-10 rounded-[10px] bg-warning/10 flex flex-col items-center justify-center flex-shrink-0">
                      <span className="text-[14px] font-extrabold text-warning leading-none">{dayNum}</span>
                      <span className="text-[8px] font-bold text-warning/70 leading-none">{MONTH_LETTER[monthIdx]}</span>
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-[13px] font-semibold text-foreground truncate">{h.name}</p>
                      <p className="text-[11px] text-foreground-muted">{formatDateLong(h.date)}</p>
                    </div>
                    <span className="px-2 py-0.5 rounded-full bg-category-teal/10 text-category-teal text-[10px] font-bold flex-shrink-0">{h.source === "company" ? "Company" : "National"}</span>
                    <button
                      onClick={() => onDelete?.(h.id)}
                      className="p-1.5 rounded-[8px] text-error opacity-0 group-hover:opacity-100 hover:bg-error/10 transition-all flex-shrink-0"
                      title="Remove holiday"
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Right: Year calendar */}
        <div className="w-full lg:w-[60%] bg-surface border border-border rounded-[18px] p-5 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
          <div className="flex items-center gap-2 mb-4">
            <CalendarDays size={16} className="text-primary" />
            <h3 className="text-[15px] font-bold text-foreground">Holiday Calendar</h3>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-3">
            {MONTHS.map((_, mi) => (
              <MiniMonth key={mi} year={year} month={mi} holidayDates={holidayDateSet} today={today} />
            ))}
          </div>
          {/* Legend */}
          <div className="mt-4 flex items-center gap-4 pt-3 border-t border-border">
            <div className="flex items-center gap-1.5">
              <div className="w-3 h-3 rounded bg-primary" />
              <span className="text-[11px] text-foreground-muted">Today</span>
            </div>
            <div className="flex items-center gap-1.5">
              <div className="w-3 h-3 rounded bg-warning/30" />
              <span className="text-[11px] text-foreground-muted">Holiday</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
