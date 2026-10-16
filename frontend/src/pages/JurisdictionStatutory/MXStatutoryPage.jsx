import { useParams, useNavigate } from "react-router-dom";
import StatutoryRatesLayout from "../../components/jurisdiction/StatutoryRatesLayout";

// Mexico statutory rates — the shared rates / slabs view (same as the
// Netherlands). Mexico's statutory content is changed only through the
// governed pack lifecycle; the read-only, date-selected views live in the
// Compliance workspace (/super-admin/compliance/mexico).
export default function MXStatutoryPage() {
  const { jurisdiction } = useParams();
  const navigate = useNavigate();
  return (
    <StatutoryRatesLayout
      country="MX" countryName="Mexico"
      initialState={jurisdiction ? decodeURIComponent(jurisdiction) : ""}
      onStateChange={(state) =>
        navigate(state ? `/super-admin/statutory-rates/mexico/${encodeURIComponent(state)}` : "/super-admin/statutory-rates/mexico", { replace: true })
      }
    />
  );
}
