import { useParams, useNavigate } from "react-router-dom";
import ReportTemplateLayout from "../../components/reportTemplates/ReportTemplateLayout";

// Saudi Arabia — same thin wrapper as every other jurisdiction. Templates are
// seeded Draft by scripts/seed_statutory_report_templates.py; activation goes
// through the shared lifecycle and the jurisdiction's activation gate.
export default function SAReportTemplatesPage() {
  const { jurisdiction } = useParams();
  const navigate = useNavigate();
  return (
    <ReportTemplateLayout
      country="SA" countryName="Saudi Arabia"
      initialState={jurisdiction ? decodeURIComponent(jurisdiction) : ""}
      onStateChange={(state) =>
        navigate(state ? `/super-admin/report-templates/saudi-arabia/${encodeURIComponent(state)}` : "/super-admin/report-templates/saudi-arabia")
      }
    />
  );
}
