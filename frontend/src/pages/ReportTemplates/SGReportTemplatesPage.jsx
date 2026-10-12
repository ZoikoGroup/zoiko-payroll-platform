import { useParams, useNavigate } from "react-router-dom";
import ReportTemplateLayout from "../../components/reportTemplates/ReportTemplateLayout";

// Singapore (final closure): the same thin wrapper every jurisdiction uses, so
// the 11 Singapore templates are reachable from Super Admin → Report Templates
// for their full lifecycle (approve, status, versions, audit). Every rule is
// enforced server-side.
export default function SGReportTemplatesPage() {
  const { jurisdiction } = useParams();
  const navigate = useNavigate();
  return (
    <ReportTemplateLayout
      country="SG" countryName="Singapore"
      initialState={jurisdiction ? decodeURIComponent(jurisdiction) : ""}
      onStateChange={(state) =>
        navigate(state ? `/super-admin/report-templates/singapore/${encodeURIComponent(state)}` : "/super-admin/report-templates/singapore")
      }
    />
  );
}
