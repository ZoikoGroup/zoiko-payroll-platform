import { useParams, useNavigate } from "react-router-dom";
import StatutoryRatesLayout from "../../components/jurisdiction/StatutoryRatesLayout";

// Brazil statutory rates — the shared, governed rates / slabs editor (same as
// the Netherlands). BR-specific authority data (INSS bands, IRRF table,
// salário-família, FGTS, CPP, rubrics, FPAS) lives in the Compliance
// workspace (/super-admin/compliance/brazil).
export default function BRStatutoryPage() {
  const { jurisdiction } = useParams();
  const navigate = useNavigate();
  return (
    <StatutoryRatesLayout
      country="BR" countryName="Brazil"
      initialState={jurisdiction ? decodeURIComponent(jurisdiction) : ""}
      onStateChange={(state) =>
        navigate(state ? `/super-admin/statutory-rates/brazil/${encodeURIComponent(state)}` : "/super-admin/statutory-rates/brazil", { replace: true })
      }
    />
  );
}
