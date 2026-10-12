import SourceEvidencePanel from "../SourceEvidencePanel";

// India Source Evidence (ZP-TAX-IN-2026-27-001 §23, gap-closure Phase F,
// 2026-09-11) — SourceEvidencePanel.jsx is already genuinely platform-
// wide (it calls getSourceArtifacts() with no jurisdiction/country
// filter at all, listing every SourceArtifact row regardless of which
// country it backs — confirmed by reading the component directly rather
// than assumed), so this is a direct reuse, not a fork: the same
// component USACompliancePage.jsx already embeds. See
// backend/scripts/populate_in_source_evidence_v1.py for the India-
// specific rows this tab will show once that script is run.
export default function INSourceEvidenceTab() {
  return <SourceEvidencePanel />;
}
