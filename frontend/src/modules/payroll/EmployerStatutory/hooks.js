import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { describeError } from "./employerStatutoryApi";

const MOBILE_QUERY = "(max-width: 639px)";

function subscribeMobile(callback) {
  if (typeof window === "undefined" || !window.matchMedia) return () => {};
  const mql = window.matchMedia(MOBILE_QUERY);
  mql.addEventListener("change", callback);
  return () => mql.removeEventListener("change", callback);
}

function getMobileSnapshot() {
  return typeof window !== "undefined" && window.matchMedia ? window.matchMedia(MOBILE_QUERY).matches : false;
}

// True below 640px. Write actions are disabled there; reads still work.
export function useIsMobile() {
  return useSyncExternalStore(subscribeMobile, getMobileSnapshot, () => false);
}

// Loads `loader()` on mount and whenever reload() is called.
// `loading` is derived from which request the stored result belongs to, so
// the effect never sets state synchronously. A 404 is reported as
// `notFound` (single-object GETs: "not configured yet"), not as an error.
export function useLoad(loader) {
  const loaderRef = useRef(loader);
  useEffect(() => { loaderRef.current = loader; });
  const [key, setKey] = useState(0);
  const [result, setResult] = useState({ key: -1, data: null, error: null, notFound: false });

  useEffect(() => {
    let live = true;
    Promise.resolve()
      .then(() => loaderRef.current())
      .then((data) => { if (live) setResult({ key, data, error: null, notFound: false }); })
      .catch((err) => {
        if (!live) return;
        if (err?.status === 404) setResult({ key, data: null, error: null, notFound: true });
        else setResult({ key, data: null, error: describeError(err, "Could not load this data."), notFound: false });
      });
    return () => { live = false; };
  }, [key]);

  const reload = useCallback(() => setKey((k) => k + 1), []);
  const current = result.key === key;
  return {
    data: result.data,
    error: current ? result.error : null,
    notFound: result.notFound,
    loading: !current,
    // First load only — keeps the previous data on screen during a reload.
    initialLoading: result.key === -1,
    reload,
    setData: (data) => setResult((r) => ({ ...r, data, notFound: false })),
  };
}

// Runs one mutation at a time with a shared error / success message.
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  const run = useCallback(async (fn, okMessage) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const out = await fn();
      if (okMessage) setNotice(okMessage);
      return { ok: true, data: out };
    } catch (err) {
      setError(describeError(err, "The change was not accepted."));
      return { ok: false };
    } finally {
      setBusy(false);
    }
  }, []);

  const clear = useCallback(() => { setError(null); setNotice(null); }, []);
  return { run, busy, error, notice, setError, clear };
}
