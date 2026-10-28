import { useParams, useNavigate } from "react-router-dom";
import ReportTemplateLayout from "../../components/reportTemplates/ReportTemplateLayout";
import MXTemplateLibraryPanel from "../../components/jurisdiction/mexico/MXTemplateLibraryPanel";
import MXTemplateVersionsPanel from "../../components/jurisdiction/mexico/MXTemplateVersionsPanel";

// Mexico — the shared report-template lifecycle (same thin wrapper as every
// other jurisdiction). Templates are seeded Draft; activation is refused
// until the report's gates are SIGNED, its content is Active and its fields
// resolve on a committed payslip (completion W4-3a). The CDMX ISN
// return lives under /super-admin/report-templates/mexico/CDMX.
export default function MXReportTemplatesPage() {
  const { jurisdiction } = useParams();
  const navigate = useNavigate();
  return (
    <>
      <ReportTemplateLayout
        country="MX" countryName="Mexico"
        initialState={jurisdiction ? decodeURIComponent(jurisdiction) : ""}
        onStateChange={(state) =>
          navigate(state ? `/super-admin/report-templates/mexico/${encodeURIComponent(state)}` : "/super-admin/report-templates/mexico")
        }
      />
      {/* Final mile X3b: library tools (coverage, version diff, sandbox preview) */}
      <MXTemplateLibraryPanel />
      {/* Template versions: each version's gate answer, Draft copy of a chosen version (rollback) */}
      <div className="mt-6"><MXTemplateVersionsPanel /></div>
    </>
  );
}
