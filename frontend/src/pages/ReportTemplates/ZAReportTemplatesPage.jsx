import { useParams, useNavigate } from "react-router-dom";
import ReportTemplateLayout from "../../components/reportTemplates/ReportTemplateLayout";

// South Africa — same thin wrapper as every other jurisdiction. Templates are
// seeded Draft by scripts/seed_statutory_report_templates.py; activation goes
// through the shared lifecycle and the jurisdiction's activation gate.
export default function ZAReportTemplatesPage() {
  const { jurisdiction } = useParams();
  const navigate = useNavigate();
  return (
    <ReportTemplateLayout
      country="ZA" countryName="South Africa"
      initialState={jurisdiction ? decodeURIComponent(jurisdiction) : ""}
      onStateChange={(state) =>
        navigate(state ? `/super-admin/report-templates/south-africa/${encodeURIComponent(state)}` : "/super-admin/report-templates/south-africa")
      }
    />
  );
}
