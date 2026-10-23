import { getBrEmployer, getBrReadinessOn, listBrEmployers } from "../../../../service/payrollService";
import { useLoad } from "../brShared";

// The organisation's Brazil employer data: employers, the effective employer
// (the one chosen, else the first), its detail, and the readiness on `on` (an
// explicit date — always sent).
export default function useBrazilOrgData(chosenId, on) {
  const [employers, employersError, , reloadEmployers] = useLoad(() => listBrEmployers(), []);
  const employerId = chosenId ?? employers?.[0]?.employerId ?? null;
  const [detail, detailError, , reloadDetail] = useLoad(
    () => (employerId ? getBrEmployer(employerId) : Promise.resolve(null)), [employerId]);
  const [readiness, readinessError, , reloadReadiness] = useLoad(() => getBrReadinessOn(on), [on]);
  const reloadAll = () => { reloadEmployers(); reloadDetail(); reloadReadiness(); };
  return {
    employers: employers || [], employerId, detail: detail && detail.employerId === employerId ? detail : null,
    readiness, error: employersError || detailError || readinessError, reloadAll,
  };
}
