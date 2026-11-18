import { Eye, Library, ShieldCheck } from "lucide-react";
import MXTemplateLibraryPanel, { MXTemplatePreviewTab, MXTemplateStatusBlock } from "./MXTemplateLibraryPanel";
import MXTemplateVersionsPanel from "./MXTemplateVersionsPanel";

// Mexico's extras for the shared ReportTemplateLayout, passed through its
// generic extension props by MXReportTemplatesPage (presentation only — every
// activation gate, payslip-proof check and maker-checker rule is server-side):
//   - Overview: built by, gates, field check and activation-gate answer;
//   - "Versions & gates": the selected template's versions, content hash, gate
//     answer, "New version" (Draft copy — the rollback path) and Compare;
//   - "Preview": the sandbox preview for a snapshot-field template;
//   - "Library": every template's build kind, gates and field check (page
//     toggle, collapsed by default).
// Module-level constants so the layout sees stable references.
export const MX_DETAIL_TABS = [
  { key: "mx-versions-gates", label: "Versions & gates", icon: ShieldCheck,
    render: (detail, ctx) => <MXTemplateVersionsPanel key={detail.id} detail={detail} ctx={ctx} /> },
  { key: "mx-preview", label: "Preview", icon: Eye,
    render: (detail) => <MXTemplatePreviewTab key={detail.id} detail={detail} /> },
];

export const MX_PAGE_TOOLS = [
  { key: "mx-library", label: "Library", icon: Library, render: () => <MXTemplateLibraryPanel /> },
];

export const renderMxOverview = (detail) => <MXTemplateStatusBlock detail={detail} />;
