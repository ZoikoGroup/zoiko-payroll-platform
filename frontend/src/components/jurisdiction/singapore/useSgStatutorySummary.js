import { useEffect, useState } from "react";
import { getSingaporeStatutorySummary } from "../../../service/superAdminService";

// Loads GET /super-admin/compliance/singapore/statutory-summary for a date
// (undefined = the backend's today). `loading` is derived from which request
// the stored result belongs to, so the effect never sets state synchronously.
export default function useSgStatutorySummary(asOf, reloadKey = 0) {
  const key = `${asOf || ""}#${reloadKey}`;
  const [result, setResult] = useState({ key: null, data: null, error: null });

  useEffect(() => {
    let live = true;
    getSingaporeStatutorySummary({ as_of: asOf })
      .then((data) => { if (live) setResult({ key, data, error: null }); })
      .catch((e) => { if (live) setResult({ key, data: null, error: e?.message || "Failed to load" }); });
    return () => { live = false; };
  }, [asOf, key, reloadKey]);

  const current = result.key === key;
  return { loading: !current, data: current ? result.data : null, error: current ? result.error : null };
}
