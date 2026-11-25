import { useParams, useNavigate } from "react-router-dom";
import ReportTemplateLayout from "../../components/reportTemplates/ReportTemplateLayout";

export default function ESReportTemplatesPage() {
  const { jurisdiction } = useParams();
  const navigate = useNavigate();
  return (
    <ReportTemplateLayout
      country="ES" countryName="Spain"
      initialState={jurisdiction ? decodeURIComponent(jurisdiction) : ""}
      onStateChange={(state) =>
        navigate(state ? `/super-admin/report-templates/spain/${encodeURIComponent(state)}`
          : "/super-admin/report-templates/spain")
      }
    />
  );
}
