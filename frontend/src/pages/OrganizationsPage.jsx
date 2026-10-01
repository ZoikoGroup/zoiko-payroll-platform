import React, { useEffect, useState, useCallback } from "react";
import { Plus, Trash2, Power, RefreshCw, Pencil, Building2, Receipt } from "lucide-react";

import { apiFetch } from "../api/client";
import { useToast } from "../context/ToastContext";
import ConfirmDialog from "../components/ConfirmDialog";
import Modal from "../components/Modal";
import SearchInput from "../components/SearchInput";
import StatusPill from "../components/StatusPill";

const BILLING_CLASSIFICATIONS = ["COMMERCIAL_ACTIVE", "NON_CHARGEABLE", "LEGACY", "INTERNAL", "DEMO", "QA"];

const BILLING_CLASSIFICATION_PILL = {
  COMMERCIAL_ACTIVE: "active",
  NON_CHARGEABLE: "inactive",
  LEGACY: "on_hold",
  INTERNAL: "deactivated",
  DEMO: "pending",
  QA: "pending",
};

const BILLING_CLASSIFICATION_CONSEQUENCE = {
  COMMERCIAL_ACTIVE: "This organization will become eligible for billing — checkout, invoicing, and dunning will treat it as a real paying customer.",
  NON_CHARGEABLE: "This organization will no longer be eligible for billing. Any existing subscription is left untouched, but no new invoice will be generated for it.",
  LEGACY: "This organization will be marked as a legacy account and excluded from billing eligibility.",
  INTERNAL: "This organization will be marked as an internal Zoiko account and excluded from billing eligibility.",
  DEMO: "This organization will be marked as a demo account and excluded from billing eligibility.",
  QA: "This organization will be marked as a QA/test account and excluded from billing eligibility.",
};

const EMPTY_ORG = {
  organization_name: "",
  industry: "",
  address: "",
  email: "",
  phone: "",
  tax_no: "",
  registration_number: "",
};

function initialsFor(name) {
  return (
    (name || "")
      .split(" ")
      .filter(Boolean)
      .slice(0, 2)
      .map((w) => w[0])
      .join("")
      .toUpperCase() || "?"
  );
}

export default function OrganizationsPage() {
  const { addToast } = useToast();
  const [orgs, setOrgs] = useState([]);
  const [search, setSearch] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [deleting, setDeleting] = useState(null);
  const [modalMode, setModalMode] = useState(null); // null | "create" | "edit"
  const [editingId, setEditingId] = useState(null);
  const [form, setForm] = useState(EMPTY_ORG);
  const [busy, setBusy] = useState(false);
  const [billingOrg, setBillingOrg] = useState(null); // org currently being reclassified
  const [billingClassification, setBillingClassification] = useState("");
  const [billingReason, setBillingReason] = useState("");

  const load = useCallback(() => {
    setLoading(true);
    setError("");
    apiFetch("/api/organizations", { params: { search, limit: 200 } })
      .then((data) => setOrgs(data.organizations))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [search]);

  useEffect(() => {
    load();
  }, [load]);

  async function toggleStatus(org) {
    setBusy(true);
    try {
      await apiFetch(`/api/organizations/${org.id}/status`, {
        method: "PATCH",
        params: { is_active: !org.is_active },
      });
      addToast?.(`Organization "${org.organization_name}" ${org.is_active ? "suspended" : "activated"}.`);
      load();
    } catch (err) {
      addToast?.(err.message, "error");
    } finally {
      setBusy(false);
    }
  }

  function openBillingClassification(org) {
    setBillingOrg(org);
    setBillingClassification(org.billing_classification || "NON_CHARGEABLE");
    setBillingReason("");
  }

  async function handleBillingClassificationSubmit(e) {
    e.preventDefault();
    setBusy(true);
    try {
      await apiFetch(`/api/organizations/${billingOrg.id}/billing-classification`, {
        method: "PATCH",
        body: { billing_classification: billingClassification, reason: billingReason },
      });
      addToast?.(`"${billingOrg.organization_name}" is now ${billingClassification}.`);
      setBillingOrg(null);
      load();
    } catch (err) {
      addToast?.(err.message, "error");
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete() {
    setBusy(true);
    try {
      await apiFetch(`/api/organizations/${deleting.id}`, { method: "DELETE" });
      addToast?.(`Organization "${deleting.organization_name}" and all of its data deleted.`);
      setDeleting(null);
      load();
    } catch (err) {
      addToast?.(err.message, "error");
    } finally {
      setBusy(false);
    }
  }

  function openCreate() {
    setModalMode("create");
    setEditingId(null);
    setForm(EMPTY_ORG);
  }

  function openEdit(org) {
    setModalMode("edit");
    setEditingId(org.id);
    setForm({
      organization_name: org.organization_name || "",
      industry: org.industry || "",
      address: org.address || "",
      email: org.email || "",
      phone: org.phone || "",
      tax_no: org.tax_no || "",
      registration_number: org.registration_number || "",
    });
  }

  function closeModal() {
    setModalMode(null);
    setEditingId(null);
    setForm(EMPTY_ORG);
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setBusy(true);
    try {
      if (modalMode === "edit") {
        await apiFetch(`/api/organizations/${editingId}`, { method: "PUT", body: form });
        addToast?.(`Organization "${form.organization_name}" updated.`);
      } else {
        await apiFetch("/api/organizations", { method: "POST", body: form });
        addToast?.(`Organization "${form.organization_name}" created.`);
      }
      closeModal();
      load();
    } catch (err) {
      addToast?.(err.message, "error");
    } finally {
      setBusy(false);
    }
  }

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));
  const INPUT =
    "w-full rounded-lg border border-border bg-surface text-foreground px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-focus-ring";

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Organizations</h1>
          <p className="text-sm text-foreground-muted mt-0.5">
            {loading ? "Loading…" : `${orgs.length} organization${orgs.length === 1 ? "" : "s"}`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <SearchInput value={search} onChange={setSearch} placeholder="Search name or code…" />
          <button
            onClick={load}
            disabled={loading}
            title="Refresh list"
            className="flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm text-foreground-secondary hover:bg-surface-muted disabled:opacity-50"
          >
            <RefreshCw size={15} className={loading ? "animate-spin" : ""} />
            Refresh
          </button>
          <button
            onClick={openCreate}
            className="flex items-center gap-2 rounded-lg bg-primary px-3 py-2 text-sm font-medium text-white hover:bg-primary-hover"
          >
            <Plus size={16} />
            New Organization
          </button>
        </div>
      </div>

      {error && (
        <p className="mb-4 rounded-lg border border-error/30 bg-error-light px-4 py-3 text-sm text-error">
          {error}
        </p>
      )}

      <div className="bg-surface rounded-xl shadow-sm overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-background text-left text-xs text-foreground-muted">
            <tr>
              <th className="px-4 py-3">Name</th>
              <th className="px-4 py-3">Code</th>
              <th className="px-4 py-3">Industry</th>
              <th className="px-4 py-3">Email</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Billing</th>
              <th className="px-4 py-3">Created</th>
              <th className="px-4 py-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {orgs.map((org) => (
              <tr key={org.id} className="border-t border-border-light hover:bg-surface-muted/60 transition-colors">
                <td className="px-4 py-3 font-medium text-foreground-secondary">
                  <div className="flex items-center gap-2.5">
                    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary-light text-xs font-semibold text-primary-hover">
                      {initialsFor(org.organization_name)}
                    </span>
                    {org.organization_name}
                  </div>
                </td>
                <td className="px-4 py-3 font-mono text-xs text-foreground-muted">{org.organization_code}</td>
                <td className="px-4 py-3 text-foreground-muted">{org.industry || "—"}</td>
                <td className="px-4 py-3 text-foreground-secondary">{org.email || "—"}</td>
                <td className="px-4 py-3">
                  <StatusPill status={org.is_active ? "active" : "suspended"} />
                </td>
                <td className="px-4 py-3">
                  <StatusPill
                    status={BILLING_CLASSIFICATION_PILL[org.billing_classification] || "inactive"}
                    label={org.billing_classification || "NON_CHARGEABLE"}
                  />
                </td>
                <td className="px-4 py-3 text-foreground-muted">
                  {new Date(org.created_at).toLocaleDateString()}
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <button
                      disabled={busy}
                      title="Edit organization"
                      onClick={() => openEdit(org)}
                      className="flex items-center gap-1 rounded-lg bg-surface-muted px-2.5 py-1 text-xs font-medium text-foreground-secondary hover:bg-border-light disabled:opacity-40"
                    >
                      <Pencil size={12} />
                      Edit
                    </button>
                    <button
                      disabled={busy}
                      title="Change billing classification"
                      onClick={() => openBillingClassification(org)}
                      className="flex items-center gap-1 rounded-lg bg-surface-muted px-2.5 py-1 text-xs font-medium text-foreground-secondary hover:bg-border-light disabled:opacity-40"
                    >
                      <Receipt size={12} />
                      Billing
                    </button>
                    <button
                      disabled={busy}
                      title={org.is_active ? "Suspend organization" : "Activate organization"}
                      onClick={() => toggleStatus(org)}
                      className={`flex items-center gap-1 rounded-lg px-2.5 py-1 text-xs font-medium disabled:opacity-40 ${
                        org.is_active
                          ? "bg-error-light text-error hover:bg-error/20"
                          : "bg-success-light text-success hover:bg-success/20"
                      }`}
                    >
                      <Power size={12} />
                      {org.is_active ? "Suspend" : "Activate"}
                    </button>
                    <button
                      disabled={busy}
                      title="Delete organization"
                      onClick={() => setDeleting(org)}
                      className="flex items-center gap-1 rounded-lg bg-error-light px-2.5 py-1 text-xs font-medium text-error hover:bg-error/20 disabled:opacity-40"
                    >
                      <Trash2 size={12} />
                      Delete
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!loading && orgs.length === 0 && (
          <div className="flex flex-col items-center justify-center gap-2 px-4 py-14 text-center">
            <Building2 size={28} className="text-foreground-disabled" />
            <p className="text-sm text-foreground-disabled">
              {search ? `No organizations match "${search}".` : "No organizations found."}
            </p>
          </div>
        )}
      </div>

      {modalMode && (
        <Modal title={modalMode === "edit" ? "Edit Organization" : "New Organization"} onClose={closeModal}>
          <form onSubmit={handleSubmit} className="grid grid-cols-2 gap-4">
            <label className="block col-span-2">
              <span className="text-xs font-medium text-foreground-secondary">Name *</span>
              <input className={INPUT} required value={form.organization_name} onChange={set("organization_name")} />
            </label>
            <label className="block">
              <span className="text-xs font-medium text-foreground-secondary">Industry</span>
              <input className={INPUT} value={form.industry} onChange={set("industry")} />
            </label>
            <label className="block">
              <span className="text-xs font-medium text-foreground-secondary">Email</span>
              <input className={INPUT} type="email" value={form.email} onChange={set("email")} />
            </label>
            <label className="block col-span-2">
              <span className="text-xs font-medium text-foreground-secondary">Address</span>
              <input className={INPUT} value={form.address} onChange={set("address")} />
            </label>
            <label className="block">
              <span className="text-xs font-medium text-foreground-secondary">Phone</span>
              <input className={INPUT} value={form.phone} onChange={set("phone")} />
            </label>
            <label className="block">
              <span className="text-xs font-medium text-foreground-secondary">Tax No</span>
              <input className={INPUT} value={form.tax_no} onChange={set("tax_no")} />
            </label>
            <label className="block col-span-2">
              <span className="text-xs font-medium text-foreground-secondary">Registration Number</span>
              <input className={INPUT} value={form.registration_number} onChange={set("registration_number")} />
            </label>
            <div className="col-span-2 flex justify-end gap-3 mt-2">
              <button
                type="button"
                onClick={closeModal}
                disabled={busy}
                className="px-4 py-2 rounded-lg text-sm font-medium text-foreground-secondary bg-surface-muted hover:bg-border-light disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={busy}
                className="px-4 py-2 rounded-lg text-sm font-medium text-white bg-primary hover:bg-primary-hover disabled:opacity-50"
              >
                {busy
                  ? modalMode === "edit" ? "Saving…" : "Creating…"
                  : modalMode === "edit" ? "Save Changes" : "Create"}
              </button>
            </div>
          </form>
        </Modal>
      )}

      {deleting && (
        <ConfirmDialog
          title="Delete Organization"
          message={`Hard-delete "${deleting.organization_name}" (${deleting.organization_code}) and ALL of its data — users, payroll, policies, documents? This is permanent.`}
          busy={busy}
          onConfirm={handleDelete}
          onClose={() => setDeleting(null)}
        />
      )}

      {billingOrg && (
        <Modal title={`Change billing classification — ${billingOrg.organization_name}`} onClose={() => setBillingOrg(null)} maxWidth="max-w-md">
          <form onSubmit={handleBillingClassificationSubmit} className="space-y-4">
            <label className="block">
              <span className="text-xs font-medium text-foreground-secondary">New classification</span>
              <select
                className={INPUT}
                value={billingClassification}
                onChange={(e) => setBillingClassification(e.target.value)}
              >
                {BILLING_CLASSIFICATIONS.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            </label>

            <p className="rounded-lg border border-warning/30 bg-warning-light px-3 py-2.5 text-xs text-warning">
              {BILLING_CLASSIFICATION_CONSEQUENCE[billingClassification]}
            </p>

            <label className="block">
              <span className="text-xs font-medium text-foreground-secondary">Reason *</span>
              <textarea
                className={INPUT}
                required
                rows={2}
                value={billingReason}
                onChange={(e) => setBillingReason(e.target.value)}
                placeholder="Why is this org moving classifications? (recorded in the audit log)"
              />
            </label>

            <div className="flex justify-end gap-3">
              <button
                type="button"
                onClick={() => setBillingOrg(null)}
                disabled={busy}
                className="px-4 py-2 rounded-lg text-sm font-medium text-foreground-secondary bg-surface-muted hover:bg-border-light disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={busy || billingClassification === billingOrg.billing_classification}
                className="px-4 py-2 rounded-lg text-sm font-medium text-white bg-primary hover:bg-primary-hover disabled:opacity-50"
              >
                {busy ? "Saving…" : "Confirm change"}
              </button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  );
}
