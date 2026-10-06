import { useParams, useNavigate } from "react-router-dom";
import StatutoryRatesLayout from "../../components/jurisdiction/StatutoryRatesLayout";

export default function IEStatutoryPage() {
  const { jurisdiction } = useParams();
  const navigate = useNavigate();
  return (
    <StatutoryRatesLayout
      country="IE" countryName="Ireland"
      initialState={jurisdiction ? decodeURIComponent(jurisdiction) : ""}
      onStateChange={(state) =>
        navigate(state ? `/super-admin/statutory-rates/ireland/${encodeURIComponent(state)}` : "/super-admin/statutory-rates/ireland", { replace: true })
      }
    />
  );
}
