import { Search } from "lucide-react";

// Extracted from the search-icon + input combo hand-rolled in UsersPage —
// applied consistently across every Super Admin list page's search box.
export default function SearchInput({ value, onChange, placeholder = "Search…", className = "" }) {
  return (
    <div className={`relative ${className}`}>
      <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 dark:text-[#9E9690]" />
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full rounded-lg border border-slate-300 dark:border-[#38312D] bg-white dark:bg-[#221D1A] py-2 pl-9 pr-3 text-sm text-slate-900 dark:text-[#F0EDE8] placeholder:text-slate-400 dark:placeholder:text-[#756B64] focus:outline-none focus:ring-2 focus:ring-orange-500"
      />
    </div>
  );
}
