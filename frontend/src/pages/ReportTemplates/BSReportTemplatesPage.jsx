import { useParams, useNavigate } from "react-router-dom";
import ReportTemplateLayout from "../../components/reportTemplates/ReportTemplateLayout";

export default function BSReportTemplatesPage() {
  const { jurisdiction } = useParams();
  const navigate = useNavigate();
  return (
    <ReportTemplateLayout
      country="BS" countryName="The Bahamas"
      initialState={jurisdiction ? decodeURIComponent(jurisdiction) : ""}
      onStateChange={(state) =>
        navigate(state ? `/super-admin/report-templates/bahamas/${encodeURIComponent(state)}` : "/super-admin/report-templates/bahamas")
      }
    />
  );
}
