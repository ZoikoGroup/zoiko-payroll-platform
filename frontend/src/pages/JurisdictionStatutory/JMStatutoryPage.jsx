import { useParams, useNavigate } from "react-router-dom";
import StatutoryRatesLayout from "../../components/jurisdiction/StatutoryRatesLayout";

export default function JMStatutoryPage() {
  const { jurisdiction } = useParams();
  const navigate = useNavigate();
  return (
    <StatutoryRatesLayout
      country="JM" countryName="Jamaica"
      initialState={jurisdiction ? decodeURIComponent(jurisdiction) : ""}
      onStateChange={(state) =>
        navigate(state ? `/super-admin/statutory-rates/jamaica/${encodeURIComponent(state)}` : "/super-admin/statutory-rates/jamaica", { replace: true })
      }
    />
  );
}
