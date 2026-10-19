import { AlertTriangle, RefreshCcw } from "lucide-react";

// Shared load-failure banner for Command Center pages: shown inline (not
// only as a toast) so a failed load never looks like "all clear".
export function LoadError({ message, onRetry }) {
  if (!message) return null;
  return (
    <div className="mb-5 flex flex-wrap items-center gap-3 rounded-xl border border-error/40 bg-error-light px-4 py-3 text-sm text-error">
      <AlertTriangle size={16} className="shrink-0" />
      <span className="min-w-0 flex-1">{message}</span>
      {onRetry && (
        <button onClick={onRetry} className="flex items-center gap-1.5 rounded-lg border border-error/40 px-2.5 py-1 text-xs font-semibold hover:bg-error/10">
          <RefreshCcw size={13} /> Retry
        </button>
      )}
    </div>
  );
}

// Placeholder blocks while the first load is in flight.
export function LoadingBlocks({ count = 3, height = "h-24", cols = "sm:grid-cols-3" }) {
  return (
    <div className={`mb-6 grid grid-cols-1 gap-4 ${cols}`}>
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className={`${height} animate-pulse rounded-xl border border-border bg-surface`} />
      ))}
    </div>
  );
}
