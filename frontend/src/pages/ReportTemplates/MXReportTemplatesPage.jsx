import { useParams, useNavigate } from "react-router-dom";
import ReportTemplateLayout from "../../components/reportTemplates/ReportTemplateLayout";

// Mexico — the shared report-template lifecycle (same thin wrapper as every
// other jurisdiction). Templates are seeded Draft; activation is refused
// until the output each one describes exists (Phases 6–10). The CDMX ISN
// return lives under /super-admin/report-templates/mexico/CDMX.
export default function MXReportTemplatesPage() {
  const { jurisdiction } = useParams();
  const navigate = useNavigate();
  return (
    <ReportTemplateLayout
      country="MX" countryName="Mexico"
      initialState={jurisdiction ? decodeURIComponent(jurisdiction) : ""}
      onStateChange={(state) =>
        navigate(state ? `/super-admin/report-templates/mexico/${encodeURIComponent(state)}` : "/super-admin/report-templates/mexico")
      }
    />
  );
}
