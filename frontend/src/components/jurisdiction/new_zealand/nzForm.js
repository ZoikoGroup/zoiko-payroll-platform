import { useEffect, useState } from "react";
import { getSourceArtifacts } from "../../../service/superAdminService";

// Plain helpers for the New Zealand governed console (no components here, so
// fast refresh keeps working for the component files).

export function reviewed(source) {
  return Boolean(source && source.hasFile && source.checksumSha256 && source.reviewerId);
}

export function useSources() {
  const [sources, setSources] = useState([]);
  useEffect(() => {
    let ignore = false;
    getSourceArtifacts().then((rows) => { if (!ignore) setSources(rows || []); }).catch(() => {});
    return () => { ignore = true; };
  }, []);
  return sources;
}

export function governanceError(value) {
  if (!value.sourceDocumentId) return "Select the source document.";
  if (!(value.reason || "").trim()) return "A change reason is required.";
  return null;
}

export function governancePayload(value) {
  return { reason: value.reason.trim(), sourceDocumentId: Number(value.sourceDocumentId),
    specialistVerified: Boolean(value.specialistVerified) };
}

const nzd = (value) => `$${Number(value).toLocaleString("en-NZ", { maximumFractionDigits: 2 })}`;

export function band(row) {
  if (!row || (row.minAmount == null && row.maxAmount == null)) return "—";
  return `${nzd(row.minAmount ?? 0)} – ${row.maxAmount != null ? nzd(row.maxAmount) : "and above"}`;
}
