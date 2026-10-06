import { useParams, useNavigate } from "react-router-dom";
import ReportTemplateLayout from "../../components/reportTemplates/ReportTemplateLayout";

// Hong Kong (ZP-HK-ENG-001): the same thin wrapper every jurisdiction uses —
// template lifecycle (approve, status, versions, audit) in the shared module.
// No IRD / eMPF file layout is seeded: the authority schemas are not
// archived yet (release gate G2). Every rule is enforced server-side.
export default function HKReportTemplatesPage() {
  const { jurisdiction } = useParams();
  const navigate = useNavigate();
  return (
    <ReportTemplateLayout
      country="HK" countryName="Hong Kong"
      initialState={jurisdiction ? decodeURIComponent(jurisdiction) : ""}
      onStateChange={(state) =>
        navigate(state ? `/super-admin/report-templates/hong-kong/${encodeURIComponent(state)}` : "/super-admin/report-templates/hong-kong")
      }
    />
  );
}
