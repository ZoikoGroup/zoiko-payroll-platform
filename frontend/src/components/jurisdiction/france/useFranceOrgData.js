import { useCallback, useEffect, useState } from "react";
import { describeLoadError } from "../../../service/errorClassification";

// One org-scoped loader for every France panel. The data is tagged with the
// organization it was loaded for, and a late response for a previous org is
// discarded — so switching organizations can never show (or crash on) the
// previous org's data. `loading` is DERIVED (data not yet for this org)
// rather than stored, which is what removes the render-before-effect race.
//
//   const { data, error, loading, reload, setData } =
//     useFranceOrgData(organizationId, (params) => listFranceEstablishments(params));
export function useFranceOrgData(organizationId, loader) {
  const [state, setState] = useState({ orgId: null, data: null, error: null });
  const [version, setVersion] = useState(0);

  useEffect(() => {
    if (!organizationId) return undefined;
    let cancelled = false;
    Promise.resolve(loader({ organizationId }))
      .then((data) => { if (!cancelled) setState({ orgId: organizationId, data, error: null }); })
      .catch((err) => { if (!cancelled) setState({ orgId: organizationId, data: null, error: describeLoadError(err) }); });
    return () => { cancelled = true; };
    // `loader` is intentionally not a dependency: callers pass an inline
    // arrow; reload() is the explicit refresh trigger.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [organizationId, version]);

  const reload = useCallback(() => setVersion((v) => v + 1), []);
  const setData = useCallback(
    (updater) => setState((s) => ({ ...s, data: typeof updater === "function" ? updater(s.data) : updater })),
    [],
  );

  const current = state.orgId === organizationId && organizationId != null;
  return {
    data: current ? state.data : null,
    error: current ? state.error : null,
    loading: Boolean(organizationId) && !current,
    reload,
    setData,
  };
}
