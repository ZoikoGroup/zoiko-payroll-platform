import { useParams, useNavigate } from "react-router-dom";
import StatutoryRatesLayout from "../../components/jurisdiction/StatutoryRatesLayout";

// Netherlands statutory rates — the shared, governed rates / slabs editor
// (same as Ireland). NL-specific authority data lives in the Compliance
// workspace (/super-admin/compliance/netherlands).
export default function NLStatutoryPage() {
  const { jurisdiction } = useParams();
  const navigate = useNavigate();
  return (
    <StatutoryRatesLayout
      country="NL" countryName="Netherlands"
      initialState={jurisdiction ? decodeURIComponent(jurisdiction) : ""}
      onStateChange={(state) =>
        navigate(state ? `/super-admin/statutory-rates/netherlands/${encodeURIComponent(state)}` : "/super-admin/statutory-rates/netherlands", { replace: true })
      }
    />
  );
}
