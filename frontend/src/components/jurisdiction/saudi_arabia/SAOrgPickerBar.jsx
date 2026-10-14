import { Building2, ChevronDown } from "lucide-react";

export function SAOrgPickerBar({
  orgDisplayName,
  orgDropdownOpen,
  setOrgDropdownOpen,
  orgSearch,
  setOrgSearch,
  loadingOrgs,
  filteredOrgs,
  selectedOrgId,
  eligibleOrgs,
  handleOrgSelect,
}) {
  return (
    <div className="mb-4 p-4 rounded-xl border border-border bg-surface">
      <div className="flex items-center gap-3">
        <span className="text-sm font-semibold text-foreground">Organization Scope</span>
        <div className="relative flex-1 max-w-md" role="combobox" aria-label="Select organization">
          <button
            type="button"
            onClick={() => setOrgDropdownOpen(!orgDropdownOpen)}
            className={`w-full flex items-center justify-between gap-2 rounded-lg border border-border bg-surface px-3 py-2 text-sm text-foreground ${orgDropdownOpen ? "border-primary" : ""}`}
            aria-expanded={orgDropdownOpen}
            aria-haspopup="listbox"
          >
            <span className="truncate">{orgDisplayName}</span>
            <ChevronDown className={`h-4 w-4 text-foreground-muted ${orgDropdownOpen ? "rotate-180" : ""}`} />
          </button>
          <div className={`absolute z-10 mt-1 w-full max-h-60 rounded-xl border border-border bg-surface shadow-lg overflow-hidden ${orgDropdownOpen ? "" : "hidden"}`}>
            <div className="p-2 border-b border-border">
              <input
                type="text"
                placeholder="Search organizations…"
                value={orgSearch}
                onChange={(e) => setOrgSearch(e.target.value)}
                className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-foreground"
                placeholder="Search organizations…"
                autoFocus
              />
            </div>
            <div className="max-h-40 overflow-y-auto" role="listbox">
              {loadingOrgs ? (
                <div className="p-4 text-center text-sm text-foreground-muted">Loading…</div>
              ) : filteredOrgs.length === 0 ? (
                <div className="p-4 text-center text-sm text-foreground-muted">No organizations found</div>
              ) : (
                <div>
                  {filteredOrgs.map((org) => (
                    <button
                      key={org.id}
                      type="button"
                      onClick={() => handleOrgSelect(org.id)}
                      className={`w-full px-3 py-2 text-sm text-left ${selectedOrgId === org.id ? "bg-primary/10 text-primary" : "text-foreground hover:bg-surface-muted"}`}
                      role="option"
                      aria-selected={selectedOrgId === org.id}
                    >
                      <span className="font-medium">{org.name}</span>
                      <span className="text-xs text-foreground-muted ml-2">({org.code})</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}