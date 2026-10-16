import { getMxEmployer, getMxReadinessOn, listMxCollectiveAgreements, listMxEmployers } from "../../../../service/payrollService";
import { useLoad } from "../mxShared";

// The organisation's Mexico employer data: employers, the effective employer
// (the one chosen, else the first), its detail, the readiness on `on` (an
// explicit date — always sent) and the MX collective agreements it may link.
export default function useMexicoOrgData(chosenId, on) {
  const [employers, employersError, , reloadEmployers] = useLoad(() => listMxEmployers(), []);
  const employerId = chosenId ?? employers?.[0]?.employerId ?? null;
  const [detail, detailError, , reloadDetail] = useLoad(
    () => (employerId ? getMxEmployer(employerId) : Promise.resolve(null)), [employerId]);
  const [readiness, readinessError, , reloadReadiness] = useLoad(() => getMxReadinessOn(on), [on]);
  const [agreements] = useLoad(() => listMxCollectiveAgreements(), []);
  const reloadAll = () => { reloadEmployers(); reloadDetail(); reloadReadiness(); };
  return {
    employers: employers || [], employerId, detail: detail && detail.employerId === employerId ? detail : null,
    readiness, agreements: agreements || [], error: employersError || detailError || readinessError, reloadAll,
  };
}
