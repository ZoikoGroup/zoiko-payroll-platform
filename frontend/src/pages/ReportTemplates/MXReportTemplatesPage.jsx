import { useParams, useNavigate } from "react-router-dom";
import ReportTemplateLayout from "../../components/reportTemplates/ReportTemplateLayout";
import { MX_DETAIL_TABS, MX_PAGE_TOOLS, renderMxOverview } from "../../components/jurisdiction/mexico/mxReportTemplateExtras";

// Mexico — the same thin wrapper as every other jurisdiction. Mexico's extras
// (template status on Overview, "Versions & gates", "Preview" and a page-level
// "Library") go through the layout's generic extension props; see
// mxReportTemplateExtras.jsx. Templates are seeded Draft; activation is
// refused until the report's gates are SIGNED, its content is Active and its
// fields resolve on a committed payslip (completion W4-3a) — server-side.
// The CDMX ISN return lives under /super-admin/report-templates/mexico/CDMX.
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
      extraDetailTabs={MX_DETAIL_TABS}
      renderOverviewExtra={renderMxOverview}
      pageTools={MX_PAGE_TOOLS}
    />
  );
}
