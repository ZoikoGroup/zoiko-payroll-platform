import { useParams, useNavigate } from "react-router-dom";
import StatutoryRatesLayout from "../../components/jurisdiction/StatutoryRatesLayout";

export default function BBStatutoryPage() {
  const { jurisdiction } = useParams();
  const navigate = useNavigate();
  return (
    <StatutoryRatesLayout
      country="BB" countryName="Barbados"
      initialState={jurisdiction ? decodeURIComponent(jurisdiction) : ""}
      onStateChange={(state) =>
        navigate(state ? `/super-admin/statutory-rates/barbados/${encodeURIComponent(state)}` : "/super-admin/statutory-rates/barbados", { replace: true })
      }
    />
  );
}
