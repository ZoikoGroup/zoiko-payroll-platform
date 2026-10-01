import { useParams, useNavigate } from "react-router-dom";
import StatutoryRatesLayout from "../../components/jurisdiction/StatutoryRatesLayout";

export default function SEStatutoryPage() {
  const { jurisdiction } = useParams();
  const navigate = useNavigate();
  return (
    <StatutoryRatesLayout
      country="SE" countryName="Sweden"
      initialState={jurisdiction ? decodeURIComponent(jurisdiction) : ""}
      onStateChange={(state) =>
        navigate(state ? `/super-admin/statutory-rates/sweden/${encodeURIComponent(state)}` : "/super-admin/statutory-rates/sweden", { replace: true })
      }
    />
  );
}
