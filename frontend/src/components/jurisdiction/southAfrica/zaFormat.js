import { useCallback, useEffect, useRef, useState } from "react";

export const card = "rounded-xl border border-border bg-surface p-4";
export const th = "px-2 py-1.5 text-left text-[11px] font-semibold uppercase tracking-wide text-foreground-muted";
export const td = "px-2 py-1.5 text-[12px] text-foreground align-top";

export function useLoad(loadFn) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const loadFnRef = useRef(loadFn);
  useEffect(() => { loadFnRef.current = loadFn; }, [loadFn]);

  const reload = useCallback(() => {
    setLoading(true);
    setError(null);
    loadFnRef.current()
      .then((d) => { setData(d); setError(null); })
      .catch((e) => setError(e?.message || "Could not load."))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    let ignore = false;
    loadFnRef.current()
      .then((d) => {
        if (ignore) return;
        setData(d);
        setError(null);
      })
      .catch((e) => {
        if (ignore) return;
        setError(e?.message || "Could not load.");
      })
      .finally(() => {
        if (!ignore) setLoading(false);
      });
    return () => { ignore = true; };
  }, []);

  return [data, error, loading, reload];
}

export function isPending(row) {
  return Boolean(row && (
    String(row.label || row.rateLabel || "").includes("[PENDING G1]")
    || String(row.textValue || "") === "PENDING_G1"
  ));
}

export function rateValue(row) {
  if (!row) return "—";
  const employee = row.employeeRatePct != null ? `${Number(row.employeeRatePct).toFixed(2)}%` : null;
  const employer = row.employerRatePct != null ? `${Number(row.employerRatePct).toFixed(2)}%` : null;
  if (employee && employer) return `Employee ${employee} / Employer ${employer}`;
  if (employee) return employee;
  if (employer) return `Employer ${employer}`;
  if (row.flatAmount != null) return row.flatAmount;
  return row.textValue ?? "—";
}

export function byKeys(rates, keys) {
  const map = new Map((rates || []).map((row) => [row.componentKey, row]));
  return keys.map((key) => map.get(key)).filter(Boolean);
}
