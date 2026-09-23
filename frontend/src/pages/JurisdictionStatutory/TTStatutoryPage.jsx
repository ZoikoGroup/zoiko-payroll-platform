import { useParams, useNavigate } from "react-router-dom";
import StatutoryRatesLayout from "../../components/jurisdiction/StatutoryRatesLayout";

export default function TTStatutoryPage() {
  const { jurisdiction } = useParams();
  const navigate = useNavigate();
  return (
    <StatutoryRatesLayout
      country="TT" countryName="Trinidad and Tobago"
      initialState={jurisdiction ? decodeURIComponent(jurisdiction) : ""}
      onStateChange={(state) =>
        navigate(state ? `/super-admin/statutory-rates/trinidad-and-tobago/${encodeURIComponent(state)}` : "/super-admin/statutory-rates/trinidad-and-tobago", { replace: true })
      }
    />
  );
}
