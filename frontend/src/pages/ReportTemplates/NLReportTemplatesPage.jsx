import { useParams, useNavigate } from "react-router-dom";
import ReportTemplateLayout from "../../components/reportTemplates/ReportTemplateLayout";

// Netherlands — same thin wrapper as every other jurisdiction (the shared
// report-template lifecycle). Loonaangifte returns are built in the NL
// Compliance workspace.
export default function NLReportTemplatesPage() {
  const { jurisdiction } = useParams();
  const navigate = useNavigate();
  return (
    <ReportTemplateLayout
      country="NL" countryName="Netherlands"
      initialState={jurisdiction ? decodeURIComponent(jurisdiction) : ""}
      onStateChange={(state) =>
        navigate(state ? `/super-admin/report-templates/netherlands/${encodeURIComponent(state)}` : "/super-admin/report-templates/netherlands")
      }
    />
  );
}
