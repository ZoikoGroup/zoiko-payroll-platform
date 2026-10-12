import { useEffect, useState, useCallback } from "react";
import { getCompliancePolicies } from "../../../../service/superAdminService";

// Shared by USOrganizationsSection/USVersionsSection/USAuditSection —
// resolves "the" tax pack for a given scope (federal, i.e. state="", or a
// specific state) using the exact same getCompliancePolicies call
// JurisdictionLayout itself uses. Prefers the Active pack, falling back to
// the most recent one if nothing is Active yet — same convention
// JurisdictionLayout's own sidebar selection defaults to.
export default function useActivePackForScope(scope) {
  const [pack, setPack] = useState(null);
  const [packs, setPacks] = useState([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const result = await getCompliancePolicies({ country: "US", state: scope || undefined, packType: "tax" });
      const list = result || [];
      setPacks(list);
      setPack(list.find((p) => p.status === "Active") || list[0] || null);
    } finally {
      setLoading(false);
    }
  }, [scope]);

  useEffect(() => { load(); }, [load]);

  return { pack, packs, setPack, loading, reload: load };
}
