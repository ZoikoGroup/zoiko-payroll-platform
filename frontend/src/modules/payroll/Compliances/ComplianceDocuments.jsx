import { useRef, useState, useEffect, useCallback } from "react";
import { UploadCloud, FileText, Trash2, CheckCircle2, AlertTriangle, Loader2, ArrowUpCircle } from "lucide-react";
import {
  uploadComplianceDocument,
  deleteComplianceDocument,
  fetchComplianceDocuments,
  normalizeComplianceDocument,
  applyExtractedRate,
} from "../../../service/payrollService";

const statusConfig = {
  processing:  { label: "Extracting…", color: "bg-[#F8A60A]/10 text-[#F8A60A]", icon: Loader2, spin: true },
  parsed:      { label: "Parsed", color: "bg-[#19C58A]/10 text-[#19C58A]", icon: CheckCircle2 },
  failed:      { label: "Extraction failed", color: "bg-[#FF6E86]/10 text-[#FF6E86]", icon: AlertTriangle },
  unavailable: { label: "Couldn't reach the server", color: "bg-[#F8F7F4] dark:bg-[#2A2520] text-[#9E9690]", icon: AlertTriangle },
};

const POLL_INTERVAL_MS = 3000;

export default function ComplianceDocumentUpload({ country, addToast, documents = [], setDocuments = () => {} }) {
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef(null);

  const loadDocuments = useCallback(async () => {
    const serverDocs = await fetchComplianceDocuments(country);
    if (serverDocs.length === 0) return;
    setDocuments((prev) => {
      const serverIds = new Set(serverDocs.map((d) => String(d.id)));
      const kept = prev.filter((d) => !serverIds.has(String(d.id)));
      const normalized = serverDocs.map((d) =>
        normalizeComplianceDocument({ ...d, sizeLabel: formatBytes(d.fileSize) }, country)
      );
      return [...kept, ...normalized];
    });
  }, [country, setDocuments]);

  useEffect(() => {
    if (documents.length === 0) {
      loadDocuments().catch(() => {});
    }
  }, []);

  useEffect(() => {
    const stillProcessing = documents.some((d) => d.status === "processing");
    if (!stillProcessing) return;
    const id = setInterval(loadDocuments, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [documents, loadDocuments]);

  const handleFiles = async (fileList) => {
    const files = Array.from(fileList || []);
    if (files.length === 0) return;

    for (const file of files) {
      const localId = `local-${Date.now()}-${file.name}`;
      const draft = {
        id: localId,
        fileName: file.name,
        sizeLabel: formatBytes(file.size),
        uploadedAt: new Date().toISOString(),
        status: "processing",
        extracted: null,
        error: null,
      };
      setDocuments((prev) => [draft, ...prev]);

      try {
        const result = await uploadComplianceDocument(file, country);
        setDocuments((prev) =>
          prev.map((d) =>
            d.id === localId
              ? normalizeComplianceDocument(
                  { ...result, sizeLabel: formatBytes(result?.fileSize) || draft.sizeLabel },
                  country
                )
              : d
          )
        );
      } catch (err) {
        setDocuments((prev) =>
          prev.map((d) =>
            d.id === localId
              ? {
                  ...d,
                  status: "unavailable",
                  error: "Couldn't reach the server to upload this document. Check your connection and try again.",
                }
              : d
          )
        );
      }
    }
  };

  const handleDelete = async (doc) => {
    setDocuments((prev) => prev.filter((d) => d.id !== doc.id));
    if (!String(doc.id).startsWith("local-")) {
      try {
        await deleteComplianceDocument(doc.id);
      } catch {
        addToast?.("Removed locally, but couldn't sync the deletion to the server.", "error");
      }
    }
  };

  return (
    <div className="space-y-4">
      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => { e.preventDefault(); setDragOver(false); handleFiles(e.dataTransfer.files); }}
        onClick={() => inputRef.current?.click()}
        className={`cursor-pointer rounded-[18px] border-2 border-dashed p-10 text-center transition-all duration-200 ${
          dragOver ? "border-[#19C58A] bg-[#19C58A]/5" : "border-[#E5E0D9] dark:border-[#38312D] bg-white dark:bg-[#221D1A] hover:border-[#19C58A]/50"
        }`}
      >
        <UploadCloud size={28} className="mx-auto mb-3 text-[#9E9690]" />
        <p className="text-[13px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">
          Drop a compliance or tax document here, or click to upload
        </p>
        <p className="text-[13px] text-[#9E9690] mt-1">
          PDF, image, or scanned notice — we'll pull out contribution rates, tax slabs, and requirements for this jurisdiction.
        </p>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept=".pdf,.png,.jpg,.jpeg"
          className="hidden"
          onChange={(e) => handleFiles(e.target.files)}
        />
      </div>

      {documents.length === 0 ? (
        <div className="bg-white dark:bg-[#221D1A] border border-[#E5E0D9] dark:border-[#38312D] rounded-[18px] p-8 text-center shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
          <FileText size={40} className="mx-auto mb-3 text-[#9E9690]" />
          <p className="text-[15px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">No documents uploaded yet</p>
          <p className="text-[13px] text-[#9E9690] mt-1">Upload compliance documents for this jurisdiction to get started.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {documents.map((doc) => {
            const sc = statusConfig[doc.status] || statusConfig.processing;
            const Icon = sc.icon;
            return (
              <div key={doc.id} className="bg-white dark:bg-[#221D1A] border border-[#E5E0D9] dark:border-[#38312D] rounded-[18px] p-5 shadow-[0_1px_3px_rgba(0,0,0,0.04)] hover:shadow-[0_8px_24px_rgba(0,0,0,0.06)] transition-all duration-200">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-start gap-3 min-w-0">
                    <div className="h-9 w-9 rounded-[10px] bg-[#35B6F5]/10 flex items-center justify-center shrink-0">
                      <FileText size={16} className="text-[#35B6F5]" />
                    </div>
                    <div className="min-w-0">
                      <p className="text-[13px] font-bold text-[#1A1816] dark:text-[#F0EDE8] truncate">{doc.fileName}</p>
                      <p className="text-[13px] text-[#9E9690]">{doc.sizeLabel} · {new Date(doc.uploadedAt).toLocaleString()}</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <span className={`flex items-center gap-1.5 rounded-full px-3 py-1 text-[11px] font-bold ${sc.color}`}>
                      <Icon size={12} className={sc.spin ? "animate-spin" : ""} /> {sc.label}
                    </span>
                    <button
                      onClick={() => handleDelete(doc)}
                      className="p-1.5 rounded-[10px] text-[#9E9690] hover:bg-[#FF6E86]/10 hover:text-[#FF6E86] transition-all duration-200"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>

                {doc.error && (
                  <p className="text-[13px] text-[#FF6E86] mt-3 bg-[#FF6E86]/5 rounded-[12px] px-3.5 py-2.5">{doc.error}</p>
                )}

                {(doc.status === "parsed" || doc.status === "failed") && doc.extracted && (
                  <ExtractedPreview
                    documentId={doc.id}
                    extracted={doc.extracted}
                    source={doc.extractionSource}
                    errorMessage={doc.extractionError}
                    country={country}
                    addToast={addToast}
                  />
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function ExtractedPreview({ documentId, extracted, source, errorMessage, country, addToast }) {
  const { contributionRates, taxSlabs, requirements, registeredEntityDetails } = extracted || {};
  const isFallback = source === "policy";
  const [applyingKey, setApplyingKey] = useState(null);

  const handleApply = async (kind, row, key) => {
    setApplyingKey(key);
    try {
      await applyExtractedRate({ documentId, kind, row, countryCode: country });
      addToast?.(`Applied "${row.label}" to active rates.`, "success");
    } catch {
      addToast?.(`Couldn't apply "${row.label}" — this action isn't wired up on the backend yet.`, "error");
    } finally {
      setApplyingKey(null);
    }
  };
  return (
    <div className="mt-4 pt-4 border-t border-[#E5E0D9] dark:border-[#38312D] space-y-4">
      <p className="text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">
        {isFallback ? "Policy-based preview" : "Extracted from this document"} — reference only, nothing is auto-applied
      </p>
      {isFallback && (
        <div className="text-[13px] bg-[#F8A60A]/5 rounded-[12px] px-3.5 py-2.5 space-y-1">
          <p className="text-[#F8A60A] font-semibold">The document parser did not return structured values, so the current company policy defaults are being shown for reference.</p>
          {errorMessage && (
            <p className="text-[#F8A60A]/70 font-mono text-[11px]">Reason: {errorMessage}</p>
          )}
        </div>
      )}

      {registeredEntityDetails && (
        <div>
          <p className="text-[11px] font-bold uppercase tracking-widest text-[#9E9690] mb-2">Registered Entity Details</p>
          <div className="space-y-1">
            {registeredEntityDetails.name && (
              <div className="flex justify-between text-[13px] text-[#6B6560] dark:text-[#A69B93] bg-[#F8F7F4] dark:bg-[#2A2520] rounded-[10px] px-3.5 py-2">
                <span>Company Name</span>
                <span className="font-mono text-right">{registeredEntityDetails.name}</span>
              </div>
            )}
            {registeredEntityDetails.registrationNumber && (
              <div className="flex justify-between text-[13px] text-[#6B6560] dark:text-[#A69B93] bg-[#F8F7F4] dark:bg-[#2A2520] rounded-[10px] px-3.5 py-2">
                <span>Registration Number</span>
                <span className="font-mono">{registeredEntityDetails.registrationNumber}</span>
              </div>
            )}
            {registeredEntityDetails.vatNumber && (
              <div className="flex justify-between text-[13px] text-[#6B6560] dark:text-[#A69B93] bg-[#F8F7F4] dark:bg-[#2A2520] rounded-[10px] px-3.5 py-2">
                <span>VAT Number</span>
                <span className="font-mono">{registeredEntityDetails.vatNumber}</span>
              </div>
            )}
            {registeredEntityDetails.payeReference && (
              <div className="flex justify-between text-[13px] text-[#6B6560] dark:text-[#A69B93] bg-[#F8F7F4] dark:bg-[#2A2520] rounded-[10px] px-3.5 py-2">
                <span>PAYE Reference</span>
                <span className="font-mono">{registeredEntityDetails.payeReference}</span>
              </div>
            )}
            {registeredEntityDetails.utr && (
              <div className="flex justify-between text-[13px] text-[#6B6560] dark:text-[#A69B93] bg-[#F8F7F4] dark:bg-[#2A2520] rounded-[10px] px-3.5 py-2">
                <span>UTR</span>
                <span className="font-mono">{registeredEntityDetails.utr}</span>
              </div>
            )}
            {registeredEntityDetails.accountsReferenceDate && (
              <div className="flex justify-between text-[13px] text-[#6B6560] dark:text-[#A69B93] bg-[#F8F7F4] dark:bg-[#2A2520] rounded-[10px] px-3.5 py-2">
                <span>Accounts Reference Date</span>
                <span className="font-mono">{registeredEntityDetails.accountsReferenceDate}</span>
              </div>
            )}
            {registeredEntityDetails.pan && (
              <div className="flex justify-between text-[13px] text-[#6B6560] dark:text-[#A69B93] bg-[#F8F7F4] dark:bg-[#2A2520] rounded-[10px] px-3.5 py-2">
                <span>PAN</span>
                <span className="font-mono uppercase">{registeredEntityDetails.pan}</span>
              </div>
            )}
            {registeredEntityDetails.tan && (
              <div className="flex justify-between text-[13px] text-[#6B6560] dark:text-[#A69B93] bg-[#F8F7F4] dark:bg-[#2A2520] rounded-[10px] px-3.5 py-2">
                <span>TAN</span>
                <span className="font-mono uppercase">{registeredEntityDetails.tan}</span>
              </div>
            )}
            {registeredEntityDetails.gst && (
              <div className="flex justify-between text-[13px] text-[#6B6560] dark:text-[#A69B93] bg-[#F8F7F4] dark:bg-[#2A2520] rounded-[10px] px-3.5 py-2">
                <span>GST</span>
                <span className="font-mono uppercase">{registeredEntityDetails.gst}</span>
              </div>
            )}
            {registeredEntityDetails.pfCode && (
              <div className="flex justify-between text-[13px] text-[#6B6560] dark:text-[#A69B93] bg-[#F8F7F4] dark:bg-[#2A2520] rounded-[10px] px-3.5 py-2">
                <span>PF Code</span>
                <span className="font-mono">{registeredEntityDetails.pfCode}</span>
              </div>
            )}
            {registeredEntityDetails.esiCode && (
              <div className="flex justify-between text-[13px] text-[#6B6560] dark:text-[#A69B93] bg-[#F8F7F4] dark:bg-[#2A2520] rounded-[10px] px-3.5 py-2">
                <span>ESI Code</span>
                <span className="font-mono">{registeredEntityDetails.esiCode}</span>
              </div>
            )}
            {registeredEntityDetails.ein && (
              <div className="flex justify-between text-[13px] text-[#6B6560] dark:text-[#A69B93] bg-[#F8F7F4] dark:bg-[#2A2520] rounded-[10px] px-3.5 py-2">
                <span>EIN</span>
                <span className="font-mono">{registeredEntityDetails.ein}</span>
              </div>
            )}
            {registeredEntityDetails.stateId && (
              <div className="flex justify-between text-[13px] text-[#6B6560] dark:text-[#A69B93] bg-[#F8F7F4] dark:bg-[#2A2520] rounded-[10px] px-3.5 py-2">
                <span>State ID</span>
                <span className="font-mono">{registeredEntityDetails.stateId}</span>
              </div>
            )}
            {registeredEntityDetails.naicsCode && (
              <div className="flex justify-between text-[13px] text-[#6B6560] dark:text-[#A69B93] bg-[#F8F7F4] dark:bg-[#2A2520] rounded-[10px] px-3.5 py-2">
                <span>NAICS Code</span>
                <span className="font-mono">{registeredEntityDetails.naicsCode}</span>
              </div>
            )}
            {registeredEntityDetails.address && (
              <div className="flex justify-between text-[13px] text-[#6B6560] dark:text-[#A69B93] bg-[#F8F7F4] dark:bg-[#2A2520] rounded-[10px] px-3.5 py-2">
                <span>Registered Address</span>
                <span className="font-mono text-right max-w-[60%]">{registeredEntityDetails.address}</span>
              </div>
            )}
          </div>
        </div>
      )}

      {contributionRates?.length > 0 && (
        <div>
          <p className="text-[11px] font-bold uppercase tracking-widest text-[#9E9690] mb-2">Contribution Rates</p>
          <div className="space-y-1">
            {contributionRates.map((r, i) => {
              const key = `rate-${r.id ?? i}`;
              return (
                <div key={key} className="flex items-center justify-between text-[13px] text-[#6B6560] dark:text-[#A69B93] bg-[#F8F7F4] dark:bg-[#2A2520] rounded-[10px] px-3.5 py-2">
                  <span>{r.label}</span>
                  <div className="flex items-center gap-3">
                    <span className="font-mono">{r.employee} / {r.employer}</span>
                    <button
                      onClick={() => handleApply("contributionRate", r, key)}
                      disabled={applyingKey === key}
                      className="flex items-center gap-1 text-[#19C58A] hover:text-[#15B07A] font-semibold disabled:opacity-50 text-[11px]"
                      title="Apply this rate to the org's active configuration"
                    >
                      {applyingKey === key ? <Loader2 size={12} className="animate-spin" /> : <ArrowUpCircle size={12} />}
                      Apply
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {taxSlabs?.length > 0 && (
        <div>
          <p className="text-[11px] font-bold uppercase tracking-widest text-[#9E9690] mb-2">Tax Slabs</p>
          <div className="space-y-1">
            {taxSlabs.map((s, i) => {
              const key = `slab-${s.id ?? i}`;
              return (
                <div key={key} className="flex items-center justify-between text-[13px] text-[#6B6560] dark:text-[#A69B93] bg-[#F8F7F4] dark:bg-[#2A2520] rounded-[10px] px-3.5 py-2">
                  <span>{s.min} – {s.max}</span>
                  <div className="flex items-center gap-3">
                    <span className="font-mono">{s.rate}</span>
                    <button
                      onClick={() => handleApply("taxSlab", s, key)}
                      disabled={applyingKey === key}
                      className="flex items-center gap-1 text-[#19C58A] hover:text-[#15B07A] font-semibold disabled:opacity-50 text-[11px]"
                      title="Apply this slab to the org's active configuration"
                    >
                      {applyingKey === key ? <Loader2 size={12} className="animate-spin" /> : <ArrowUpCircle size={12} />}
                      Apply
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {requirements?.length > 0 && (
        <div>
          <p className="text-[11px] font-bold uppercase tracking-widest text-[#9E9690] mb-2">Requirements Noted</p>
          <ul className="space-y-1 list-disc list-inside">
            {requirements.map((r, i) => (
              <li key={i} className="text-[13px] text-[#6B6560] dark:text-[#A69B93]">{r.label}{r.note ? ` — ${r.note}` : ""}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function formatBytes(bytes) {
  if (!bytes) return "0 KB";
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(0)} KB`;
  return `${(kb / 1024).toFixed(1)} MB`;
}
