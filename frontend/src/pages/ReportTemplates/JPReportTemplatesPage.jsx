import { useParams, useNavigate } from "react-router-dom";
import ReportTemplateLayout from "../../components/reportTemplates/ReportTemplateLayout";

// Japan — same thin wrapper as every other jurisdiction. Templates are
// seeded Draft by scripts/seed_statutory_report_templates.py; activation goes
// through the shared lifecycle and the jurisdiction's activation gate.
export default function JPReportTemplatesPage() {
  const { jurisdiction } = useParams();
  const navigate = useNavigate();
  return (
    <ReportTemplateLayout
      country="JP" countryName="Japan"
      initialState={jurisdiction ? decodeURIComponent(jurisdiction) : ""}
      onStateChange={(state) =>
        navigate(state ? `/super-admin/report-templates/japan/${encodeURIComponent(state)}` : "/super-admin/report-templates/japan")
      }
    />
  );
}
