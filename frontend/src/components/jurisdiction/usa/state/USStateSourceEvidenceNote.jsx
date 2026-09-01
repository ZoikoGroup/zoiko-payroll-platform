import { Link } from "react-router-dom";
import { FileCheck2 } from "lucide-react";

// Source Evidence (SourceArtifact) has no state/jurisdiction field in its
// data model at all — nothing to filter or embed for a single state without
// a backend change. Rather than fabricate a filtered view, this points to
// the existing platform-wide Source Evidence tab (SourceEvidencePanel.jsx,
// untouched).
export default function USStateSourceEvidenceNote() {
  return (
    <div className="rounded-xl border border-dashed border-border bg-surface-muted p-6 text-center">
      <FileCheck2 size={20} className="mx-auto mb-2 text-foreground-disabled" />
      <p className="mx-auto max-w-md text-xs text-foreground-secondary">
        Source Evidence records aren't tracked per-state — they're a platform-wide log of the official
        publications behind configured rates and slabs.
      </p>
      <Link
        to="/super-admin/compliance/united-states?section=sourceEvidence"
        className="mt-2 inline-block text-xs font-semibold text-primary hover:underline"
      >
        View Source Evidence →
      </Link>
    </div>
  );
}
