import { useEffect, useMemo, useState } from "react";
import {
  ShieldCheck,
  Loader2,
  FileSearch,
  RefreshCw,
  ChevronDown,
  X,
  BookOpen,
  Plus,
  Save,
  Send,
  Pencil,
} from "lucide-react";
import { useAuth } from "../../context/AuthContext";
import { ROLES } from "../../config/roles";
import {
  getAssistRetentionSummary,
  listAssistAuditEvents,
  listAdminAssistSessions,
  runAssistRetentionCleanup,
  listAssistModelExecutions,
  listAssistKbItems,
  createAssistKbItem,
  updateAssistKbItem,
  publishAssistKbItem,
  listAssistKbSources,
} from "../../service/assistService";
import { formatAssistDate } from "./locales";

const ALLOWED_ROLES = new Set([ROLES.ORG_ADMIN, ROLES.PAYROLL_ADMIN, ROLES.SUPER_ADMIN]);

function Card({ title, value, sub, accent }) {
  return (
    <div className="rounded-[16px] border border-border bg-white p-4">
      <p className="text-[11px] font-semibold text-foreground-muted">{title}</p>
      <p className={`mt-1 text-[22px] font-extrabold ${accent || "text-foreground"}`}>{value}</p>
      {sub ? <p className="mt-1 text-[10px] text-foreground-disabled">{sub}</p> : null}
    </div>
  );
}

function JsonExpandable({ label, value }) {
  const [open, setOpen] = useState(false);
  if (value === undefined || value === null || value === "") return null;
  return (
    <div className="mt-1">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1 text-[10px] font-semibold text-primary"
      >
        <ChevronDown size={11} className={`transition-transform ${open ? "rotate-180" : ""}`} />
        {label}
      </button>
      {open ? (
        <pre className="mt-1 max-h-40 overflow-auto rounded-[10px] bg-background px-2.5 py-2 text-[10px] leading-relaxed text-foreground-muted">
          {JSON.stringify(value, null, 2)}
        </pre>
      ) : null}
    </div>
  );
}

function StatusPill({ value }) {
  const tone =
    value === "COMPLETED" || value === "ACTIVE"
      ? "bg-primary/10 text-primary-hover"
      : value === "REFUSED" || value === "FAILED"
        ? "bg-error/10 text-error"
        : value === "ARCHIVED"
          ? "bg-background-secondary text-foreground-muted"
          : "bg-warning-light text-warning";
  return <span className={`rounded-full px-2 py-0.5 text-[9px] font-bold uppercase ${tone}`}>{value}</span>;
}

const KB_STATES = ["", "DRAFT", "IN_REVIEW", "APPROVED", "PUBLISHED", "SUPERSEDED"];
const CONTENT_TYPES = ["HOW_TO", "FAQ", "POLICY", "GUIDE", "REFERENCE"];
const AUTHORITIES = ["TIER_1_STATUTE", "TIER_2_APPROVED_PRIMARY", "TIER_3_APPROVED_SECONDARY", "TIER_4_TENANT"];

const inputCls =
  "w-full rounded-[10px] border border-border bg-white px-2.5 py-2 text-[12px] text-foreground outline-none focus:border-primary";

function KbItemRow({ item, onEdit, onPublish, savingId }) {
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({ title: item.title, summary: item.summary || "", body: item.body });

  if (editing) {
    return (
      <div className="border-b border-border-light bg-background-secondary px-4 py-3">
        <input
          className={inputCls}
          value={form.title}
          onChange={(e) => setForm({ ...form, title: e.target.value })}
          placeholder="Title"
        />
        <textarea
          className={`${inputCls} mt-2`}
          rows={2}
          value={form.summary}
          onChange={(e) => setForm({ ...form, summary: e.target.value })}
          placeholder="Summary"
        />
        <textarea
          className={`${inputCls} mt-2`}
          rows={4}
          value={form.body}
          onChange={(e) => setForm({ ...form, body: e.target.value })}
          placeholder="Body"
        />
        <div className="mt-2 flex gap-2">
          <button
            type="button"
            disabled={savingId === item.id}
            onClick={async () => {
              await onEdit(item.id, form);
              setEditing(false);
            }}
            className="inline-flex items-center gap-1.5 rounded-[10px] bg-primary px-3 py-1.5 text-[11px] font-bold text-white transition hover:bg-primary-hover disabled:opacity-60"
          >
            {savingId === item.id ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
            Save
          </button>
          <button
            type="button"
            onClick={() => setEditing(false)}
            className="rounded-[10px] border border-border px-3 py-1.5 text-[11px] font-bold text-foreground-muted"
          >
            Cancel
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="border-b border-border-light px-4 py-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-[13px] font-bold text-foreground">{item.title}</p>
            <StatusPill value={item.state} />
            {item.version > 1 ? <span className="rounded-full bg-background-secondary px-2 py-0.5 text-[9px] font-bold text-foreground-muted">v{item.version}</span> : null}
          </div>
          <p className="mt-1 text-[11px] text-foreground-muted">{item.summary || item.body?.slice(0, 120) || "—"}</p>
          <p className="mt-1 text-[10px] text-foreground-muted">
            {item.content_type} · {item.authority.replaceAll("_", " ")} · #{(item.id)}
            {item.next_review_at ? ` · review ${item.next_review_at}` : ""}
          </p>
        </div>
        <div className="flex shrink-0 gap-1.5">
          {item.state !== "PUBLISHED" ? (
            <button
              type="button"
              onClick={() => setEditing(true)}
              className="inline-flex items-center gap-1 rounded-[8px] border border-border px-2 py-1 text-[10px] font-bold text-foreground-muted hover:border-primary hover:text-primary"
            >
              <Pencil size={10} /> Edit
            </button>
          ) : null}
          {item.state === "APPROVED" ? (
            <button
              type="button"
              disabled={savingId === item.id}
              onClick={() => onPublish(item.id)}
              className="inline-flex items-center gap-1 rounded-[8px] bg-primary px-2 py-1 text-[10px] font-bold text-white transition hover:bg-primary-hover disabled:opacity-60"
            >
              {savingId === item.id ? <Loader2 size={10} className="animate-spin" /> : <Send size={10} />}
              Publish
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function KnowledgePanel({ allowed }) {
  const [items, setItems] = useState(null);
  const [sources, setSources] = useState([]);
  const [state, setState] = useState("");
  const [savingId, setSavingId] = useState(null);
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({
    title: "",
    summary: "",
    body: "",
    content_type: "HOW_TO",
    authority: "TIER_3_APPROVED_SECONDARY",
  });

  async function load() {
    try {
      const [it, src] = await Promise.all([listAssistKbItems({ state: state || undefined }), listAssistKbSources()]);
      setItems(it);
      setSources(src);
    } catch {
      setItems([]);
    }
  }

  useEffect(() => {
    if (allowed) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state, allowed]);

  async function handleCreate() {
    if (!form.title.trim() || !form.body.trim()) return;
    setSavingId("create");
    try {
      await createAssistKbItem(form);
      setForm({ title: "", summary: "", body: "", content_type: "HOW_TO", authority: "TIER_3_APPROVED_SECONDARY" });
      setShowCreate(false);
      await load();
    } finally {
      setSavingId(null);
    }
  }

  async function handleEdit(id, values) {
    setSavingId(id);
    try {
      await updateAssistKbItem(id, values);
      await load();
    } finally {
      setSavingId(null);
    }
  }

  async function handlePublish(id) {
    setSavingId(id);
    try {
      await publishAssistKbItem(id);
      await load();
    } finally {
      setSavingId(null);
    }
  }

  return (
    <div className="mt-4 space-y-4">
      <div className="rounded-[16px] border border-border bg-white">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border-light px-4 py-3">
          <div className="flex flex-wrap items-center gap-2">
            <label className="text-[11px] font-bold text-foreground-muted">State</label>
            <select
              value={state}
              onChange={(e) => setState(e.target.value)}
              className="rounded-[10px] border border-border bg-white px-2.5 py-1.5 text-[12px] text-foreground outline-none focus:border-primary"
            >
              {KB_STATES.map((s) => (
                <option key={s} value={s}>
                  {s === "" ? "All states" : s.replaceAll("_", " ")}
                </option>
              ))}
            </select>
            {state ? (
              <button
                type="button"
                onClick={() => setState("")}
                className="inline-flex items-center gap-1 rounded-[8px] px-2 py-1 text-[11px] font-semibold text-error hover:bg-error-light"
              >
                <X size={11} /> Clear
              </button>
            ) : null}
          </div>
          <button
            type="button"
            onClick={() => setShowCreate((v) => !v)}
            className="inline-flex items-center gap-1.5 rounded-[10px] border border-border bg-white px-3 py-1.5 text-[11px] font-bold text-primary hover:border-primary"
          >
            <Plus size={12} /> New knowledge item
          </button>
        </div>

        {showCreate ? (
          <div className="border-b border-border-light bg-background-secondary px-4 py-3">
            <div className="grid gap-2">
              <input
                className={inputCls}
                placeholder="Title"
                value={form.title}
                onChange={(e) => setForm({ ...form, title: e.target.value })}
              />
              <textarea
                className={inputCls}
                rows={2}
                placeholder="Summary"
                value={form.summary}
                onChange={(e) => setForm({ ...form, summary: e.target.value })}
              />
              <textarea
                className={inputCls}
                rows={4}
                placeholder="Body (governed answer content)"
                value={form.body}
                onChange={(e) => setForm({ ...form, body: e.target.value })}
              />
              <div className="grid grid-cols-2 gap-2">
                <select
                  className={inputCls}
                  value={form.content_type}
                  onChange={(e) => setForm({ ...form, content_type: e.target.value })}
                >
                  {CONTENT_TYPES.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
                <select
                  className={inputCls}
                  value={form.authority}
                  onChange={(e) => setForm({ ...form, authority: e.target.value })}
                >
                  {AUTHORITIES.map((a) => (
                    <option key={a} value={a}>
                      {a.replaceAll("_", " ")}
                    </option>
                  ))}
                </select>
              </div>
              <div className="flex gap-2">
                <button
                  type="button"
                  disabled={savingId === "create"}
                  onClick={handleCreate}
                  className="inline-flex items-center gap-1.5 rounded-[10px] bg-primary px-3 py-1.5 text-[11px] font-bold text-white transition hover:bg-primary-hover disabled:opacity-60"
                >
                  {savingId === "create" ? <Loader2 size={12} className="animate-spin" /> : <Plus size={12} />}
                  Create draft
                </button>
                <button
                  type="button"
                  onClick={() => setShowCreate(false)}
                  className="rounded-[10px] border border-border px-3 py-1.5 text-[11px] font-bold text-foreground-muted"
                >
                  Cancel
                </button>
              </div>
            </div>
          </div>
        ) : null}

        {items === null ? (
          <div className="flex items-center justify-center p-10">
            <Loader2 size={18} className="animate-spin text-primary" />
          </div>
        ) : items.length === 0 ? (
          <p className="p-8 text-center text-[12px] text-foreground-muted">No knowledge items match.</p>
        ) : (
          <div className="max-h-[560px] overflow-y-auto">
            {items.map((it) => (
              <KbItemRow key={it.id} item={it} onEdit={handleEdit} onPublish={handlePublish} savingId={savingId} />
            ))}
          </div>
        )}
      </div>

      {/* Sources */}
      <div className="rounded-[16px] border border-border bg-white">
        <p className="border-b border-border-light px-4 py-3 text-[12px] font-bold text-foreground">
          Knowledge sources ({sources.length})
        </p>
        {sources.length === 0 ? (
          <p className="p-6 text-center text-[12px] text-foreground-muted">No sources registered.</p>
        ) : (
          <div className="max-h-[240px] overflow-y-auto">
            {sources.map((s) => (
              <div key={s.id} className="flex items-start justify-between gap-3 border-b border-border-light px-4 py-2.5">
                <div className="min-w-0">
                  <p className="text-[12px] font-bold text-foreground">{s.name}</p>
                  <p className="text-[10px] text-foreground-muted">
                    {s.source_type || "source"} · {s.authority_tier.replaceAll("_", " ")}
                  </p>
                </div>
                <StatusPill value={s.state} />
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default function AssistAdminPage() {
  const { role } = useAuth();
  const [summary, setSummary] = useState(null);
  const [events, setEvents] = useState(null);
  const [sessions, setSessions] = useState(null);
  const [eventType, setEventType] = useState("");
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState("audit");
  const [runningRetention, setRunningRetention] = useState(false);

  const allowed = ALLOWED_ROLES.has(role);

  async function loadAll() {
    setBusy(true);
    try {
      const [sum, evs, sess] = await Promise.all([
        getAssistRetentionSummary(),
        listAssistAuditEvents({ limit: 100, event_type: eventType || undefined }),
        listAdminAssistSessions({ limit: 50 }),
      ]);
      setSummary(sum);
      setEvents(evs.events || []);
      setSessions(sess.sessions || []);
    } catch {
      // show restricted message
    } finally {
      setBusy(false);
    }
  }

  async function runRetention() {
    setRunningRetention(true);
    try {
      await runAssistRetentionCleanup();
      setSummary(await getAssistRetentionSummary());
    } catch {
      // ignore
    } finally {
      setRunningRetention(false);
    }
  }

  useEffect(() => {
    if (allowed) loadAll();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!allowed) return;
    const timer = setTimeout(() => {
      listAssistAuditEvents({ limit: 100, event_type: eventType || undefined })
        .then((evs) => setEvents(evs.events || []))
        .catch(() => {});
    }, 250);
    return () => clearTimeout(timer);
  }, [eventType]); // eslint-disable-line react-hooks/exhaustive-deps

  const eventTypes = useMemo(() => {
    if (!events) return [];
    const seen = new Set();
    for (const e of events) seen.add(e.event_type);
    return [...seen].sort();
  }, [events]);

  if (!allowed) {
    return (
      <div className="flex min-h-screen items-center justify-center p-8">
        <div className="max-w-md rounded-[20px] border border-error/30 bg-error-light px-8 py-10 text-center">
          <ShieldCheck className="mx-auto h-10 w-10 text-error" />
          <h1 className="mt-4 text-[18px] font-bold text-foreground">Restricted area</h1>
          <p className="mt-2 text-[13px] text-foreground-muted">
            Assist audit and retention administration requires org admin or payroll admin privileges.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-6xl px-4 py-8 lg:px-8">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="flex items-center gap-2 text-[12px] font-bold uppercase tracking-[0.2em] text-primary">
            <ShieldCheck size={14} /> Zoiko Payroll Assist
          </p>
          <h1 className="mt-1 text-[24px] font-extrabold text-foreground">Assist Governance</h1>
        </div>
        <button
          type="button"
          onClick={loadAll}
          disabled={busy}
          className="inline-flex items-center gap-1.5 rounded-[12px] border border-border bg-white px-3 py-2 text-[12px] font-bold text-foreground-muted transition hover:border-primary hover:text-primary disabled:opacity-60"
        >
          {busy ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
          Refresh
        </button>
      </div>

      {/* Retention summary */}
      <div className="mt-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Card title="Total sessions" value={summary?.total_sessions ?? "—"} />
        <Card title="Archived" value={summary?.status_counts?.ARCHIVED ?? "—"} accent="text-foreground-muted" />
        <Card title="Expired (retention)" value={summary?.expired_sessions ?? "—"} accent="text-warning" />
        <Card
          title="Retention policy"
          value={summary?.retention_policy ? summary.retention_policy.replaceAll("_", " ") : "—"}
          accent="text-primary"
          sub="classification-based retention window"
        />
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button
          type="button"
          disabled={runningRetention}
          onClick={runRetention}
          className="inline-flex items-center gap-1.5 rounded-[10px] border border-warning bg-warning-light px-3 py-1.5 text-[11px] font-bold text-warning transition hover:bg-warning-light disabled:opacity-60"
        >
          {runningRetention ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
          Run retention cleanup
        </button>
        <span className="text-[11px] text-foreground-muted">Archives sessions past their retention window (audited).</span>
      </div>

      {summary?.retention_class_counts ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {Object.entries(summary.retention_class_counts).map(([cls, count]) => (
            <span key={cls} className="rounded-full bg-background px-2.5 py-1 text-[10px] font-semibold text-foreground-muted">
              {cls.replaceAll("_", " ")} · {count}
            </span>
          ))}
        </div>
      ) : null}

      {/* Tabs */}
      <div className="mt-6 flex border-b border-border">
        {[
          { id: "audit", label: "Audit events", icon: FileSearch },
          { id: "sessions", label: "Sessions", icon: ShieldCheck },
          { id: "knowledge", label: "Knowledge base", icon: BookOpen },
        ].map((tb) => {
          const Icon = tb.icon;
          return (
            <button
              key={tb.id}
              type="button"
              onClick={() => setTab(tb.id)}
              className={`flex items-center gap-1.5 rounded-t-[10px] px-4 py-2.5 text-[12px] font-bold transition ${
                tab === tb.id ? "border-b-2 border-primary text-primary" : "text-foreground-muted hover:text-foreground-muted"
              }`}
            >
              <Icon size={13} /> {tb.label}
            </button>
          );
        })}
      </div>

      {/* Audit events */}
      {tab === "audit" ? (
        <div className="mt-4 rounded-[16px] border border-border bg-white">
          <div className="flex flex-wrap items-center gap-2 border-b border-border-light px-4 py-3">
            <label className="text-[11px] font-bold text-foreground-muted">Event type</label>
            <select
              value={eventType}
              onChange={(e) => setEventType(e.target.value)}
              className="rounded-[10px] border border-border bg-white px-2.5 py-1.5 text-[12px] text-foreground outline-none focus:border-primary"
            >
              <option value="">All</option>
              {eventTypes.map((et) => (
                <option key={et} value={et}>
                  {et}
                </option>
              ))}
            </select>
            {eventType ? (
              <button
                type="button"
                onClick={() => setEventType("")}
                className="inline-flex items-center gap-1 rounded-[8px] px-2 py-1 text-[11px] font-semibold text-error hover:bg-error-light"
              >
                <X size={11} /> Clear
              </button>
            ) : null}
          </div>
          {events === null ? (
            <div className="flex items-center justify-center p-10">
              <Loader2 size={18} className="animate-spin text-primary" />
            </div>
          ) : events.length === 0 ? (
            <p className="p-8 text-center text-[12px] text-foreground-muted">No audit events match.</p>
          ) : (
            <div className="max-h-[560px] overflow-y-auto">
              <table className="w-full text-left">
                <thead className="sticky top-0 bg-white">
                  <tr className="border-b border-border-light text-[10px] uppercase tracking-wide text-foreground-muted">
                    <th className="px-4 py-2.5 font-bold">Event</th>
                    <th className="px-3 py-2.5 font-bold">Session</th>
                    <th className="px-3 py-2.5 font-bold">User</th>
                    <th className="px-3 py-2.5 font-bold">Recorded</th>
                    <th className="px-4 py-2.5 font-bold">Details</th>
                  </tr>
                </thead>
                <tbody>
                  {events.map((e) => (
                    <tr key={e.id} className="border-b border-border-light align-top hover:bg-background-secondary">
                      <td className="px-4 py-3">
                        <p className="text-[12px] font-bold text-foreground">{e.event_type}</p>
                        <p className="text-[10px] text-foreground-muted">#{e.id}</p>
                      </td>
                      <td className="px-3 py-3 text-[11px] text-foreground-muted">{e.session_id ?? "—"}</td>
                      <td className="px-3 py-3 text-[11px] text-foreground-muted">{e.user_id ?? "—"}</td>
                      <td className="px-3 py-3 text-[11px] text-foreground-muted">{formatAssistDate(e.recorded_at)}</td>
                      <td className="px-4 py-3">
                        <JsonExpandable label={`payload (${Object.keys(e.payload || {}).length})`} value={e.payload} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      ) : null}

      {/* Sessions */}
      {tab === "sessions" ? (
        <div className="mt-4 rounded-[16px] border border-border bg-white">
          {sessions === null ? (
            <div className="flex items-center justify-center p-10">
              <Loader2 size={18} className="animate-spin text-primary" />
            </div>
          ) : sessions.length === 0 ? (
            <p className="p-8 text-center text-[12px] text-foreground-muted">No sessions found.</p>
          ) : (
            <div className="max-h-[560px] overflow-y-auto">
              <table className="w-full text-left">
                <thead className="sticky top-0 bg-white">
                  <tr className="border-b border-border-light text-[10px] uppercase tracking-wide text-foreground-muted">
                    <th className="px-4 py-2.5 font-bold">Session</th>
                    <th className="px-3 py-2.5 font-bold">State</th>
                    <th className="px-3 py-2.5 font-bold">Channel</th>
                    <th className="px-3 py-2.5 font-bold">Locale</th>
                    <th className="px-4 py-2.5 font-bold">Created</th>
                  </tr>
                </thead>
                <tbody>
                  {sessions.map((s) => (
                    <tr key={s.id} className="border-b border-border-light hover:bg-background-secondary">
                      <td className="px-4 py-3">
                        <p className="text-[12px] font-bold text-foreground">{s.title || `Session #${s.id}`}</p>
                        <p className="text-[10px] text-foreground-muted">org #{s.organization_id ?? "—"}</p>
                      </td>
                      <td className="px-3 py-3">
                        <StatusPill value={s.status} />
                      </td>
                      <td className="px-3 py-3 text-[11px] text-foreground-muted">{s.channel || "WEB"}</td>
                      <td className="px-3 py-3 text-[11px] text-foreground-muted">{s.locale || "en"}</td>
                      <td className="px-4 py-3 text-[11px] text-foreground-muted">{formatAssistDate(s.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      ) : null}

      {/* Knowledge base */}
      {tab === "knowledge" ? <KnowledgePanel allowed={allowed} /> : null}
    </div>
  );
}
