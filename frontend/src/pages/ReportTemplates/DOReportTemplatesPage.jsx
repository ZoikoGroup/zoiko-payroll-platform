import { useParams, useNavigate } from "react-router-dom";
import ReportTemplateLayout from "../../components/reportTemplates/ReportTemplateLayout";

export default function DOReportTemplatesPage() {
  const { jurisdiction } = useParams();
  const navigate = useNavigate();
  return (
    <ReportTemplateLayout
      country="DO" countryName="Dominican Republic"
      initialState={jurisdiction ? decodeURIComponent(jurisdiction) : ""}
      onStateChange={(state) =>
        navigate(state ? `/super-admin/report-templates/dominican-republic/${encodeURIComponent(state)}` : "/super-admin/report-templates/dominican-republic")
      }
    />
  );
}
