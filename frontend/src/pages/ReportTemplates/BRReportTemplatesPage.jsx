import { useParams, useNavigate } from "react-router-dom";
import ReportTemplateLayout from "../../components/reportTemplates/ReportTemplateLayout";

// Brazil — same thin wrapper as every other jurisdiction (the shared
// report-template lifecycle). Brazil-specific returns (eSocial / FGTS
// reporting) are built in the BR Compliance workspace.
export default function BRReportTemplatesPage() {
  const { jurisdiction } = useParams();
  const navigate = useNavigate();
  return (
    <ReportTemplateLayout
      country="BR" countryName="Brazil"
      initialState={jurisdiction ? decodeURIComponent(jurisdiction) : ""}
      onStateChange={(state) =>
        navigate(state ? `/super-admin/report-templates/brazil/${encodeURIComponent(state)}` : "/super-admin/report-templates/brazil")
      }
    />
  );
}
