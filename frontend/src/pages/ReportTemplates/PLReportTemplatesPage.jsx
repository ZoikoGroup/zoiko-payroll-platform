import { useParams, useNavigate } from "react-router-dom";
import ReportTemplateLayout from "../../components/reportTemplates/ReportTemplateLayout";

// Poland — same thin wrapper as every other jurisdiction. Templates are
// seeded Draft by scripts/seed_statutory_report_templates.py; activation goes
// through the shared lifecycle and the jurisdiction's activation gate.
export default function PLReportTemplatesPage() {
  const { jurisdiction } = useParams();
  const navigate = useNavigate();
  return (
    <ReportTemplateLayout
      country="PL" countryName="Poland"
      initialState={jurisdiction ? decodeURIComponent(jurisdiction) : ""}
      onStateChange={(state) =>
        navigate(state ? `/super-admin/report-templates/poland/${encodeURIComponent(state)}` : "/super-admin/report-templates/poland")
      }
    />
  );
}
