import { useCallback, useEffect, useRef, useState } from "react";

// Shared building blocks for the Brazil (CLT) Super Admin tabs — a direct
// mirror of ../netherlands/nlShared.jsx so the BR workspace reads the same way
// the NL one does: compact table styles, a load hook, an action hook, messages.
export const card = "rounded-xl border border-border bg-surface p-4";
export const th = "px-2 py-1.5 text-left text-[11px] font-semibold uppercase tracking-wide text-foreground-muted";
export const td = "px-2 py-1.5 text-[12px] text-foreground align-top";
export const btn = "rounded-lg border border-border px-3 py-1.5 text-[12px] font-semibold text-foreground hover:bg-surface-muted disabled:opacity-40";
export const btnPrimary = "rounded-lg bg-primary px-3 py-1.5 text-[12px] font-semibold text-white hover:opacity-90 disabled:opacity-40";
export const input = "rounded-lg border border-border bg-surface px-2 py-1 text-[12px] text-foreground";
export const labelCls = "flex flex-col gap-1 text-[11px] font-semibold text-foreground-muted";

export function useLoad(loadFn, deps = []) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const loadFnRef = useRef(loadFn);
  useEffect(() => { loadFnRef.current = loadFn; }, [loadFn]);
  const reload = useCallback(() => {
    setLoading(true);
    setError(null);
    loadFnRef.current()
      .then((d) => setData(d))
      .catch((e) => setError(e?.message || "Could not load."))
      .finally(() => setLoading(false));
  }, []);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { reload(); }, deps);
  return [data, error, loading, reload];
}

// Runs one action, shows its error or a notice, then reloads — same idiom as
// nlShared's useAction.
export function useAction(reload) {
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(false);
  const run = useCallback(async (fn, okMessage) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await fn();
      if (okMessage) setNotice(okMessage);
      reload?.();
      return result;
    } catch (e) {
      setError(e?.message || "The action failed.");
      return false;
    } finally {
      setBusy(false);
    }
  }, [reload]);
  return { run, error, notice, busy };
}

export function Messages({ error, notice }) {
  return (
    <>
      {error && <p role="alert" className="text-[13px] text-error">{error}</p>}
      {notice && <p className="text-[13px] text-success">{notice}</p>}
    </>
  );
}

export function NeedOrg() {
  return (
    <div className={card}>
      <p className="text-[13px] text-foreground-muted">Select an organisation above to see its Brazil data.</p>
    </div>
  );
}

// Normalises the many list endpoint shapes (bare array, { rows }, { rubrics },
// { items }) into one array so a non-array payload can never crash a table.
export const toRows = (data) => {
  if (Array.isArray(data)) return data;
  if (data && typeof data === "object") return data.rows || data.rubrics || data.items || data.gates || [];
  return [];
};

// Column helper: reads the first key actually present on the row, trying both
// camelCase and snake_case (Brazil's API mixes the two), else shows "—".
export const cell = (...keys) => (row) => {
  for (const k of keys) {
    const v = row?.[k];
    if (v !== undefined && v !== null && v !== "") return v;
  }
  return "—";
};

export const yesNoCell = (...keys) => (row) => {
  for (const k of keys) {
    const v = row?.[k];
    if (v !== undefined && v !== null && v !== "") return v ? "Yes" : "No";
  }
  return "—";
};

export function Table({ columns, rows, empty = "Nothing recorded yet.", rowKey = (r) => r.id ?? r.code ?? r.key }) {
  const list = toRows(rows);
  if (list.length === 0) return <p className="text-[12px] text-foreground-muted">{empty}</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full">
        <thead>
          <tr>{columns.map((c) => <th key={c.key} className={th}>{c.label}</th>)}</tr>
        </thead>
        <tbody>
          {list.map((r, i) => (
            <tr key={rowKey(r) ?? i} className="border-t border-border">
              {columns.map((c) => <td key={c.key} className={td}>{c.render ? c.render(r) : (r[c.key] ?? "—")}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Field({ label, children }) {
  return <label className={labelCls}>{label}{children}</label>;
}

export const yesNo = (v) => (v ? "Yes" : "No");
