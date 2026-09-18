import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Building2,
  ChevronDown,
  ChevronUp,
  FileSignature,
  Plus,
  RefreshCcw,
} from "lucide-react";
import Modal from "../../components/Modal";
import StatusPill from "../../components/StatusPill";
import { useToast } from "../../context/ToastContext";
import { listOrganizationsForPicker } from "../../service/superAdminService";
import {
  createOrderForm,
  listOrderForms,
} from "../../service/commandCenterService";

// Same feature_key vocabulary as billing/feature_keys.py — shared with
// require_scope_limit/require_entitlement on the backend. A value of 0 means
// "explicitly off"; null/absent means "on/unlimited".
const SCALE_LIMIT_HINTS = [
  { key: "max_entities", hint: "cap on companies/entities (integer)" },
  { key: "max_billable_worker_months", hint: "cap on billable worker-months (integer)" },
  { key: "multi_entity", hint: "on or 0" },
  { key: "multi_currency", hint: "on or 0" },
  { key: "api_access", hint: "on or 0" },
  { key: "assist", hint: "on or 0" },
];

const EMPTY_FORM = {
  organization_id: "",
  contract_reference: "",
  term_start: "",
  term_end: "",
  scale_limits: "{\n  \"max_entities\": 10\n}",
  price_terms: "{\n  \"annual_usd\": 100000\n}",
};

function formatDate(value) {
  if (!value) return "—";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleDateString();
}

function parseJsonField(text, fieldName) {
  const trimmed = (text || "").trim();
  if (!trimmed) return {};
  try {
    const parsed = JSON.parse(trimmed);
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      throw new Error(`${fieldName} must be a JSON object`);
    }
    return parsed;
  } catch (err) {
    throw new Error(`${fieldName}: ${err.message}`);
  }
}

export default function OrderFormsPage() {
  const { addToast } = useToast() || {};
  const [rows, setRows] = useState([]);
  const [organizations, setOrganizations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [keyword, setKeyword] = useState("");
  const [form, setForm] = useState(EMPTY_FORM);
  const [formError, setFormError] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [pendingPayload, setPendingPayload] = useState(null);
  const [busy, setBusy] = useState(false);
  const [expandedId, setExpandedId] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listOrderForms();
      setRows(res.order_forms || []);
    } catch (err) {
      addToast?.(err.message, "error");
    } finally {
      setLoading(false);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    listOrganizationsForPicker()
      .then(setOrganizations)
      .catch((err) => addToast?.(err.message, "error"));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Org ids that already have an Order Form on file — choosing one of these
  // would hit the backend's uniqueness rule (409), so keep them out of the
  // "create" path up front instead of letting the user find out on submit.
  const orgsWithOrderForm = useMemo(() => new Set(rows.map((r) => r.organization_id)), [rows]);

  const selectedOrg = useMemo(
    () => organizations.find((o) => o.id === Number(form.organization_id)) || null,
    [organizations, form.organization_id]
  );

  const filteredRows = useMemo(() => {
    const k = keyword.trim().toLowerCase();
    if (!k) return rows;
    return rows.filter(
      (r) =>
        (r.organization_name || "").toLowerCase().includes(k) ||
        (r.contract_reference || "").toLowerCase().includes(k)
    );
  }, [rows, keyword]);

  function setField(field, value) {
    setForm((prev) => ({ ...prev, [field]: value }));
    setFormError("");
  }

  function handleRecordClick(e) {
    e.preventDefault();
    setConfirming(true);
  }

  async function handleConfirmRecord() {
    if (!selectedOrg) {
      setFormError("Choose an organization.");
      setConfirming(false);
      return;
    }
    let scaleLimits;
    let priceTerms;
    try {
      scaleLimits = parseJsonField(form.scale_limits, "Scale limits");
      priceTerms = parseJsonField(form.price_terms, "Price terms");
    } catch (err) {
      setFormError(err.message);
      setConfirming(false);
      return;
    }

    const payload = {
      contract_reference: form.contract_reference.trim(),
      negotiated_scale_limits: scaleLimits,
      negotiated_price_terms: priceTerms,
      term_start: form.term_start,
      term_end: form.term_end || null,
    };
    if (!payload.contract_reference) {
      setFormError("Contract reference is required.");
      setConfirming(false);
      return;
    }
    if (!payload.term_start) {
      setFormError("Term start is required.");
      setConfirming(false);
      return;
    }

    setPendingPayload({ payload, org: selectedOrg });
    setFormError("");
  }

  async function handleSubmit() {
    const { payload, org } = pendingPayload;
    setBusy(true);
    try {
      await createOrderForm(org.id, payload);
      addToast?.(
        `Order Form ${payload.contract_reference} recorded for ${org.organization_name}. The org is now commercially active with custom, contract-defined limits.`
      );
      setConfirming(false);
      setPendingPayload(null);
      setForm(EMPTY_FORM);
      await load();
    } catch (err) {
      addToast?.(err.message, "error");
      setConfirming(false);
      setPendingPayload(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-foreground flex items-center gap-2">
            <FileSignature size={22} className="text-primary" /> Order Forms
          </h1>
          <p className="text-sm text-foreground-muted mt-0.5">
            Signed Enterprise Order Forms — the one path that makes an organization commercially active by human decision.
          </p>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm text-foreground-secondary hover:bg-slate-100 dark:hover:bg-white/5 disabled:opacity-50"
        >
          <RefreshCcw size={15} className={loading ? "animate-spin" : ""} /> Refresh
        </button>
      </div>

      {/* ── Record a new Order Form ───────────────────────────────────────── */}
      <form
        onSubmit={handleRecordClick}
        className="bg-surface rounded-xl shadow-sm border border-border p-5 mb-6"
      >
        <div className="flex items-center gap-2 mb-4">
          <Plus size={16} className="text-primary" />
          <h2 className="text-base font-semibold text-foreground">Record a signed Order Form</h2>
        </div>

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <label className="block sm:col-span-2 lg:col-span-1">
            <span className="text-xs font-medium text-foreground-secondary">Organization *</span>
            <select
              value={form.organization_id}
              onChange={(e) => setField("organization_id", e.target.value)}
              className="mt-1 w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-foreground"
            >
              <option value="">Choose an organization…</option>
              {organizations.map((org) => {
                const hasForm = orgsWithOrderForm.has(org.id);
                return (
                  <option key={org.id} value={org.id} disabled={hasForm}>
                    {org.organization_name}
                    {hasForm ? " (Order Form already on file)" : ""}
                  </option>
                );
              })}
            </select>
          </label>

          <label className="block">
            <span className="text-xs font-medium text-foreground-secondary">Contract reference *</span>
            <input
              type="text"
              value={form.contract_reference}
              onChange={(e) => setField("contract_reference", e.target.value)}
              maxLength={100}
              placeholder="OF-2026-0001"
              className="mt-1 w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-foreground"
            />
          </label>

          <label className="block">
            <span className="text-xs font-medium text-foreground-secondary">Term start *</span>
            <input
              type="date"
              value={form.term_start}
              onChange={(e) => setField("term_start", e.target.value)}
              className="mt-1 w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-foreground"
            />
          </label>

          <label className="block">
            <span className="text-xs font-medium text-foreground-secondary">Term end</span>
            <input
              type="date"
              value={form.term_end}
              onChange={(e) => setField("term_end", e.target.value)}
              className="mt-1 w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-foreground"
            />
          </label>

          <label className="block sm:col-span-2 lg:col-span-1">
            <span className="text-xs font-medium text-foreground-secondary">Negotiated scale limits (JSON) *</span>
            <textarea
              rows={4}
              value={form.scale_limits}
              onChange={(e) => setField("scale_limits", e.target.value)}
              spellCheck={false}
              className="mt-1 w-full rounded-lg border border-border bg-surface px-3 py-2 font-mono text-xs text-foreground"
            />
            <span className="mt-1 block text-[11px] text-foreground-muted">
              Same keys as plan entitlements: {SCALE_LIMIT_HINTS.map((h) => h.key).join(", ")} — 0 means off.
            </span>
          </label>

          <label className="block">
            <span className="text-xs font-medium text-foreground-secondary">Negotiated price terms (JSON) *</span>
            <textarea
              rows={4}
              value={form.price_terms}
              onChange={(e) => setField("price_terms", e.target.value)}
              spellCheck={false}
              className="mt-1 w-full rounded-lg border border-border bg-surface px-3 py-2 font-mono text-xs text-foreground"
            />
          </label>
        </div>

        {formError && (
          <p className="mt-3 rounded-lg border border-error/30 bg-error-light px-3 py-2 text-xs text-error">{formError}</p>
        )}

        <div className="mt-4 flex justify-end">
          <button
            type="submit"
            className="flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover"
          >
            <FileSignature size={15} /> Review &amp; record
          </button>
        </div>
      </form>

      {/* ── Existing Order Forms ─────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center gap-3 mb-4">
        <h2 className="text-base font-semibold text-foreground">On file ({rows.length})</h2>
        <input
          type="text"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          placeholder="Filter by organization or contract reference…"
          className="ml-auto w-full max-w-xs rounded-lg border border-border bg-surface px-3 py-2 text-sm text-foreground"
        />
      </div>

      <div className="bg-surface rounded-xl shadow-sm border border-border overflow-hidden overflow-x-auto">
        <table className="w-full text-sm min-w-[760px]">
          <thead className="bg-background text-left text-xs text-foreground-muted">
            <tr>
              <th className="px-4 py-3">Organization</th>
              <th className="px-4 py-3">Contract Reference</th>
              <th className="px-4 py-3">Route</th>
              <th className="px-4 py-3">Term Start</th>
              <th className="px-4 py-3">Term End</th>
              <th className="px-4 py-3">Recorded</th>
              <th className="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody>
            {filteredRows.map((row) => {
              const isOpen = expandedId === row.id;
              return (
                <FragmentRow key={row.id} row={row} isOpen={isOpen} onToggle={() => setExpandedId(isOpen ? null : row.id)} />
              );
            })}
          </tbody>
        </table>
        {!loading && filteredRows.length === 0 && (
          <div className="flex flex-col items-center justify-center gap-2 px-4 py-14 text-center">
            <FileSignature size={28} className="text-border-strong" />
            <p className="text-sm text-foreground-disabled">No Order Forms on file yet.</p>
            {keyword && <p className="text-xs text-foreground-muted">Try clearing the filter.</p>}
          </div>
        )}
      </div>

      {/* ── Explicit confirmation — every mutating action gets one ──────── */}
      {confirming && (
        <Modal
          title="Record this Order Form?"
          onClose={() => { if (!busy) setConfirming(false); }}
          maxWidth="max-w-md"
        >
          <div className="rounded-lg border border-amber-300 bg-amber-50 px-3.5 py-3 text-xs text-amber-800">
            <span className="flex items-center gap-2 font-semibold">
              <AlertTriangle size={14} className="shrink-0" />
              This will make {selectedOrg?.organization_name || "this organization"} commercially active with custom,
              contract-defined limits.
            </span>
            <span className="mt-1 block">
              Its commercial route becomes <strong>Enterprise Order Form</strong> and self-service checkout is permanently
              unavailable for it. This cannot be undone from this screen.
            </span>
          </div>
          <dl className="mt-4 space-y-2 text-sm">
            <div className="flex justify-between gap-3">
              <dt className="text-foreground-muted">Organization</dt>
              <dd className="font-medium text-foreground">{selectedOrg?.organization_name}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-foreground-muted">Contract reference</dt>
              <dd className="font-medium text-foreground">{pendingPayload?.payload.contract_reference}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-foreground-muted">Term</dt>
              <dd className="font-medium text-foreground">
                {formatDate(pendingPayload?.payload.term_start)} → {formatDate(pendingPayload?.payload.term_end)}
              </dd>
            </div>
          </dl>
          <div className="mt-5 flex justify-end gap-3">
            <button
              type="button"
              onClick={() => { setConfirming(false); setPendingPayload(null); }}
              disabled={busy}
              className="rounded-lg bg-surface-muted px-4 py-2 text-sm font-medium text-foreground-secondary hover:bg-border-light disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleSubmit}
              disabled={busy}
              className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50"
            >
              {busy ? "Recording…" : "Confirm — make commercially active"}
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}

function FragmentRow({ row, isOpen, onToggle }) {
  return (
    <>
      <tr
        className="border-t border-border-light cursor-pointer hover:bg-slate-50 dark:hover:bg-white/5"
        onClick={onToggle}
      >
        <td className="px-4 py-3 font-medium text-foreground">
          <span className="flex items-center gap-2">
            <Building2 size={14} className="text-border-strong" />
            {row.organization_name}
          </span>
        </td>
        <td className="px-4 py-3 text-foreground-secondary">{row.contract_reference}</td>
        <td className="px-4 py-3"><StatusPill status="active" label="Enterprise Order Form" /></td>
        <td className="px-4 py-3 text-foreground-muted">{formatDate(row.term_start)}</td>
        <td className="px-4 py-3 text-foreground-muted">{formatDate(row.term_end)}</td>
        <td className="px-4 py-3 text-foreground-muted">{formatDate(row.created_at)}</td>
        <td className="px-4 py-3 text-right">
          {isOpen ? <ChevronUp size={15} className="ml-auto text-foreground-muted" /> : <ChevronDown size={15} className="ml-auto text-foreground-muted" />}
        </td>
      </tr>
      {isOpen && (
        <tr className="border-t border-border-light bg-background">
          <td colSpan={7} className="px-4 py-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-foreground-muted mb-1.5">Negotiated scale limits</p>
                <pre className="rounded-lg border border-border bg-surface p-3 text-xs text-foreground whitespace-pre-wrap break-words">
                  {JSON.stringify(row.negotiated_scale_limits || {}, null, 2)}
                </pre>
              </div>
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-foreground-muted mb-1.5">Negotiated price terms</p>
                <pre className="rounded-lg border border-border bg-surface p-3 text-xs text-foreground whitespace-pre-wrap break-words">
                  {JSON.stringify(row.negotiated_price_terms || {}, null, 2)}
                </pre>
              </div>
            </div>
            <p className="mt-3 text-[11px] text-foreground-muted">
              Recorded by user id {row.signed_by ?? "—"} · Created {formatDate(row.created_at)}
            </p>
          </td>
        </tr>
      )}
    </>
  );
}