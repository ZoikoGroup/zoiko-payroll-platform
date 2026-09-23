import { useParams, useNavigate } from "react-router-dom";
import ReportTemplateLayout from "../../components/reportTemplates/ReportTemplateLayout";

export default function BBReportTemplatesPage() {
  const { jurisdiction } = useParams();
  const navigate = useNavigate();
  return (
    <ReportTemplateLayout
      country="BB" countryName="Barbados"
      initialState={jurisdiction ? decodeURIComponent(jurisdiction) : ""}
      onStateChange={(state) =>
        navigate(state ? `/super-admin/report-templates/barbados/${encodeURIComponent(state)}` : "/super-admin/report-templates/barbados")
      }
    />
  );
}
