import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  X,
  Sparkles,
  ShieldCheck,
  RotateCcw,
  Info,
  ThumbsUp,
  ThumbsDown,
  Loader2,
  Plus,
  Trash2,
  Pencil,
  History,
  FileText,
  Check,
  Save,
  LifeBuoy,
  ArrowLeft,
} from "lucide-react";
import {
  acknowledgeAssistNotice,
  getAssistResponse,
  getAssistStatus,
  getPublicPayrollCountries,
  getAssistSuggestions,
  getCurrentAssistNotice,
  submitAssistFeedback,
  submitAssistMessage,
  createAssistSession,
  updateAssistSession,
  archiveAssistSession,
  listAssistSessions,
  listAssistMessages,
  streamAssistResponseEvents,
  confirmAssistAction,
  cancelAssistAction,
  createAssistDraft,
  listAssistDrafts,
  updateAssistDraft,
  deleteAssistDraft,
  stopAssistResponse,
  createAssistHandoffPreview,
  confirmAssistHandoff,
  cancelAssistHandoff,
} from "../../service/assistService";
import { ASSIST_LOCALES, getAssistLocale, setAssistLocale, t, formatAssistDate } from "./locales";
import { useAuth } from "../../context/AuthContext";
import zoikoPayrollLogo from "../../assets/zoiko-payroll-logo.png";
import zoikoPayrollIcon from "../../assets/zoiko-payroll-icon.png";
import { COPY, DEFAULT_LINKS, POPULAR_QUESTIONS, TOPICS } from "./concierge/content";
import {
  ConciergeComposer,
  ConciergeHeader,
  ConciergeLauncher,
  CountryCheck,
  CtaRow,
  FOCUS_RING,
  PANEL_CLASS,
  PopularQuestions,
  ThinkingBubble,
  TopicGrid,
  WelcomeBlock,
} from "./concierge/ConciergeUI";

// Scoped per user id — otherwise switching accounts in the same browser
// leaves the previous user's session id in localStorage, and the widget
// tries to reuse a session that belongs to a different organization.
const SESSION_KEY_PREFIX = "zoiko_payroll_assist_session";
function getSessionStorageKey(userId) {
  return userId ? `${SESSION_KEY_PREFIX}_${userId}` : SESSION_KEY_PREFIX;
}

// Mirrors MessageContent.text's max_length in the backend schemas.
const MAX_MESSAGE_LENGTH = 8000;

const ACCENT = "bg-primary";
const ACCENT_HOVER = "hover:bg-primary-hover";

function NoticeGate({ notice, onAcknowledge, busy }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 px-6 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-full bg-primary/10">
        <ShieldCheck className="h-6 w-6 text-primary" />
      </div>
      <div>
        <p className="text-[15px] font-bold text-foreground">{t("assist.notice.title")}</p>
        <p className="mt-2 text-[13px] leading-relaxed text-foreground-muted">{notice?.content}</p>
      </div>
      <button
        type="button"
        onClick={onAcknowledge}
        disabled={busy}
        className={`inline-flex items-center gap-2 rounded-[12px] px-5 py-2.5 text-[13px] font-bold text-white ${ACCENT} ${ACCENT_HOVER} transition-all duration-200 disabled:opacity-60`}
      >
        {busy ? <Loader2 size={15} className="animate-spin" /> : null}
        {t("assist.notice.acknowledge")}
      </button>
    </div>
  );
}

function AboutAssistSection({ title, body }) {
  return (
    <div>
      <p className="text-[12px] font-bold text-foreground">{title}</p>
      <p className="mt-1 text-[12px] leading-relaxed text-foreground-muted">{body}</p>
    </div>
  );
}

function AboutAssistPanel({ onClose }) {
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={t("assist.about.title")}
      className="absolute inset-0 z-20 flex flex-col bg-surface"
    >
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <p className="text-[13px] font-bold text-primary">{t("assist.about.title")}</p>
        <button
          type="button"
          onClick={onClose}
          aria-label={t("assist.close")}
          title={t("assist.close")}
          className="rounded-[10px] p-1.5 text-foreground-muted transition hover:bg-background hover:text-primary"
        >
          <X size={16} />
        </button>
      </div>
      <div className="flex-1 space-y-4 overflow-y-auto px-4 py-4">
        <AboutAssistSection title={t("assist.about.can.title")} body={t("assist.about.can.body")} />
        <AboutAssistSection title={t("assist.about.cannot.title")} body={t("assist.about.cannot.body")} />
        <AboutAssistSection title={t("assist.about.how.title")} body={t("assist.about.how.body")} />
        <AboutAssistSection title={t("assist.about.data.title")} body={t("assist.about.data.body")} />
        <AboutAssistSection title={t("assist.about.feedback.title")} body={t("assist.about.feedback.body")} />
        <AboutAssistSection title={t("assist.about.support.title")} body={t("assist.about.support.body")} />
      </div>
    </div>
  );
}

function SuggestionChips({ suggestions, onPick }) {
  if (!suggestions.length) return null;
  return (
    <div className="flex flex-wrap gap-2">
      {suggestions.slice(0, 4).map((s) => (
        <button
          key={s.intent_id + s.position}
          type="button"
          onClick={() => onPick(s.prompt)}
          className="rounded-[12px] border border-border bg-surface px-3 py-2 text-left text-[12px] font-medium text-foreground-muted transition-all duration-200 hover:border-primary hover:text-primary"
        >
          {s.prompt}
        </button>
      ))}
    </div>
  );
}

function FeedbackRow({ message, onFeedback }) {
  if (!message.responseId) return null;
  return (
    <div className="mt-1.5 flex items-center gap-1">
      <button
        type="button"
        onClick={() => onFeedback(message, "helpful")}
        className={`rounded-[8px] p-1 transition ${message.rating === "helpful" ? "bg-primary/10 text-primary" : "text-foreground-muted hover:text-primary"}`}
        title={t("assist.helpful")}
      >
        <ThumbsUp size={12} />
      </button>
      <button
        type="button"
        onClick={() => onFeedback(message, "not-helpful")}
        className={`rounded-[8px] p-1 transition ${message.rating === "not-helpful" ? "bg-error/10 text-error" : "text-foreground-muted hover:text-error"}`}
        title={t("assist.notHelpful")}
      >
        <ThumbsDown size={12} />
      </button>
    </div>
  );
}

function prettyJSON(value) {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value ?? "");
  }
}

function DiffPane({ label, value }) {
  if (value === undefined || value === null) return null;
  const text = typeof value === "object" ? prettyJSON(value) : String(value);
  return (
    <div className="min-w-0 flex-1">
      <p className="text-[10px] font-bold uppercase tracking-wide text-foreground-muted">{label}</p>
      <pre className="mt-1 max-h-32 overflow-y-auto whitespace-pre-wrap rounded-[10px] bg-background px-2.5 py-2 text-[10px] leading-relaxed text-foreground-muted">
        {text}
      </pre>
    </div>
  );
}

function ActionCard({ action, onError }) {
  const [state, setState] = useState("ready");
  const [receipt, setReceipt] = useState(null);
  const available = action.available !== false;

  if (!available) {
    return (
      <div className="mt-2 rounded-[12px] border border-warning/30 bg-warning-light px-3 py-2">
        <p className="text-[11px] font-semibold text-warning">{t("assist.action.title")}</p>
        <p className="mt-0.5 text-[11px] text-warning">{action.reason || "Action unavailable."}</p>
      </div>
    );
  }

  async function handleConfirm() {
    setState("busy");
    try {
      const result = await confirmAssistAction(action.preview_id);
      setReceipt(result);
      setState("confirmed");
    } catch (e) {
      setState("ready");
      onError?.(e.message || "Action confirmation failed.");
    }
  }

  async function handleCancel() {
    setState("busy");
    try {
      await cancelAssistAction(action.preview_id);
      setState("cancelled");
    } catch (e) {
      setState("ready");
      onError?.(e.message || "Action cancellation failed.");
    }
  }

  if (state === "confirmed") {
    return (
      <div className="mt-2 rounded-[12px] border border-success/30 bg-success-light px-3 py-2.5">
        <p className="flex items-center gap-1.5 text-[12px] font-bold text-primary-hover">
          <Check size={13} /> {t("assist.action.confirmed")}
        </p>
        <p className="mt-0.5 break-all text-[10px] text-category-teal">
          {t("assist.action.receipt", { id: receipt?.receipt_id || action.preview_id })}
        </p>
      </div>
    );
  }

  if (state === "cancelled") {
    return (
      <div className="mt-2 rounded-[12px] border border-border bg-background px-3 py-2.5">
        <p className="flex items-center gap-1.5 text-[12px] font-semibold text-foreground-muted">
          <X size={13} /> {t("assist.action.cancelled")}
        </p>
      </div>
    );
  }

  return (
    <div className="mt-2 rounded-[12px] border border-warning/30 bg-warning-light px-3 py-2.5">
      <div className="flex items-center justify-between gap-2">
        <p className="flex items-center gap-1.5 text-[11px] font-bold text-warning">
          <ShieldCheck size={12} /> {t("assist.action.title")}
        </p>
        <span className="rounded-full bg-warning/10 px-2 py-0.5 text-[9px] font-bold uppercase text-warning">
          {t("assist.action.riskTier", { tier: action.risk_tier })}
        </span>
      </div>
      <p className="mt-1.5 truncate text-[10px] text-warning">
        {action.action_id} · {t("assist.action.target", { type: action.target?.type })}
      </p>
      {action.confirmation?.label ? (
        <p className="mt-1 text-[11px] font-medium text-warning">{action.confirmation.label}</p>
      ) : null}
      {action.confirmation?.step_up_required ? (
        <p className="mt-1 text-[10px] text-warning">MFA / second approver required</p>
      ) : null}
      <div className="mt-2 flex gap-2">
        <DiffPane label={t("assist.action.before")} value={action.before} />
        <DiffPane label={t("assist.action.after")} value={action.after} />
      </div>
      <div className="mt-2.5 flex items-center gap-2">
        <button
          type="button"
          onClick={handleConfirm}
          disabled={state === "busy"}
          className={`inline-flex items-center gap-1.5 rounded-[10px] px-3 py-1.5 text-[11px] font-bold text-white transition disabled:opacity-60 ${ACCENT} ${ACCENT_HOVER}`}
        >
          {state === "busy" ? <Loader2 size={12} className="animate-spin" /> : null}
          {action.confirmation?.label || t("assist.action.confirm")}
        </button>
        <button
          type="button"
          onClick={handleCancel}
          disabled={state === "busy"}
          className="inline-flex items-center gap-1.5 rounded-[10px] border border-border bg-surface px-3 py-1.5 text-[11px] font-semibold text-foreground-muted transition hover:border-error hover:text-error disabled:opacity-60"
        >
          {t("assist.action.cancel")}
        </button>
      </div>
    </div>
  );
}

const HANDOFF_DESTINATIONS = ["PAYROLL_SUPPORT", "COMPLIANCE_LOCAL_PAYROLL"];

function HandoffPanel({ sessionId, onClose }) {
  const [state, setState] = useState("form"); // form | busy | preview | confirmed
  const [destination, setDestination] = useState(HANDOFF_DESTINATIONS[0]);
  const [reasonCode, setReasonCode] = useState("USER_REQUESTED");
  const [summary, setSummary] = useState("");
  const [preview, setPreview] = useState(null);
  const [receipt, setReceipt] = useState(null);
  const [error, setError] = useState("");

  async function handleCreatePreview(e) {
    e.preventDefault();
    if (!summary.trim()) return;
    setState("busy");
    setError("");
    try {
      const result = await createAssistHandoffPreview({
        destination,
        reason_code: reasonCode,
        summary: summary.trim(),
        source_session_id: sessionId ?? null,
      });
      setPreview(result);
      setState("preview");
    } catch (err) {
      setError(err.message || "Could not prepare the handoff.");
      setState("form");
    }
  }

  async function handleConfirm() {
    setState("busy");
    try {
      const result = await confirmAssistHandoff(preview.preview_id);
      setReceipt(result);
      setState("confirmed");
    } catch (err) {
      setError(err.message || "Could not confirm the handoff.");
      setState("preview");
    }
  }

  async function handleCancel() {
    setState("busy");
    try {
      await cancelAssistHandoff(preview.preview_id);
      onClose();
    } catch (err) {
      setError(err.message || "Could not cancel the handoff.");
      setState("preview");
    }
  }

  return (
    <div className="mx-4 mt-3 rounded-[14px] border border-border bg-surface p-3">
      <div className="mb-2 flex items-center justify-between">
        <p className="flex items-center gap-1.5 text-[12px] font-bold text-foreground">
          <LifeBuoy size={13} className="text-primary" /> {t("assist.handoff.title")}
        </p>
        <button type="button" onClick={onClose} className="rounded-[8px] p-1 text-foreground-muted hover:text-foreground">
          <X size={14} />
        </button>
      </div>

      {error ? <p className="mb-2 rounded-[10px] bg-error-light px-2.5 py-1.5 text-[11px] text-error">{error}</p> : null}

      {state === "confirmed" ? (
        <div className="rounded-[12px] border border-success/30 bg-success-light px-3 py-2.5">
          <p className="flex items-center gap-1.5 text-[12px] font-bold text-primary-hover">
            <Check size={13} /> {t("assist.handoff.created")}
          </p>
          <p className="mt-1 text-[11px] text-category-teal">
            {t("assist.handoff.caseRef", { id: receipt?.case_id || receipt?.handoff_id })}
          </p>
          {receipt?.sla_reference ? (
            <p className="mt-0.5 text-[10px] text-category-teal">{receipt.sla_reference}</p>
          ) : null}
          <button
            type="button"
            onClick={onClose}
            className={`mt-2 inline-flex items-center gap-1.5 rounded-[8px] px-3 py-1.5 text-[11px] font-bold text-white transition ${ACCENT} ${ACCENT_HOVER}`}
          >
            {t("assist.close")}
          </button>
        </div>
      ) : state === "preview" ? (
        <div className="rounded-[12px] border border-border bg-background p-2.5">
          <p className="text-[11px] font-semibold text-foreground">{preview.destination}</p>
          <p className="mt-1 text-[11px] text-foreground-muted">{preview.summary}</p>
          <div className="mt-2.5 flex items-center gap-2">
            <button
              type="button"
              onClick={handleConfirm}
              disabled={state === "busy"}
              className={`inline-flex items-center gap-1.5 rounded-[10px] px-3 py-1.5 text-[11px] font-bold text-white transition disabled:opacity-60 ${ACCENT} ${ACCENT_HOVER}`}
            >
              {t("assist.handoff.confirm")}
            </button>
            <button
              type="button"
              onClick={handleCancel}
              disabled={state === "busy"}
              className="inline-flex items-center gap-1.5 rounded-[10px] border border-border bg-surface px-3 py-1.5 text-[11px] font-semibold text-foreground-muted transition hover:border-error hover:text-error disabled:opacity-60"
            >
              {t("assist.action.cancel")}
            </button>
          </div>
        </div>
      ) : (
        <form onSubmit={handleCreatePreview} className="space-y-2">
          <div>
            <label className="text-[10px] font-bold uppercase tracking-wide text-foreground-muted">
              {t("assist.handoff.destination")}
            </label>
            <select
              value={destination}
              onChange={(e) => setDestination(e.target.value)}
              className="mt-1 w-full rounded-[8px] border border-border bg-surface px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-primary"
            >
              {HANDOFF_DESTINATIONS.map((d) => (
                <option key={d} value={d}>{d.replaceAll("_", " ")}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-[10px] font-bold uppercase tracking-wide text-foreground-muted">
              {t("assist.handoff.reason")}
            </label>
            <input
              value={reasonCode}
              onChange={(e) => setReasonCode(e.target.value)}
              className="mt-1 w-full rounded-[8px] border border-border bg-surface px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-primary"
            />
          </div>
          <div>
            <label className="text-[10px] font-bold uppercase tracking-wide text-foreground-muted">
              {t("assist.handoff.summary")}
            </label>
            <textarea
              value={summary}
              onChange={(e) => setSummary(e.target.value)}
              rows={3}
              placeholder={t("assist.handoff.summaryPlaceholder")}
              className="mt-1 w-full resize-none rounded-[8px] border border-border bg-surface px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-primary"
            />
          </div>
          <button
            type="submit"
            disabled={state === "busy" || !summary.trim()}
            className={`inline-flex w-full items-center justify-center gap-1.5 rounded-[10px] px-3 py-2 text-[11px] font-bold text-white transition disabled:opacity-60 ${ACCENT} ${ACCENT_HOVER}`}
          >
            {state === "busy" ? <Loader2 size={12} className="animate-spin" /> : null}
            {t("assist.handoff.preview")}
          </button>
        </form>
      )}
    </div>
  );
}

function SaveDraftButton({ responseId, content, sessionId, onSaved }) {
  const [open, setOpen] = useState(false);
  const [draftType, setDraftType] = useState("note");
  const [draftContent, setDraftContent] = useState(content || "");
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  if (!responseId) return null;

  async function handleSave(e) {
    e.preventDefault();
    if (!draftContent.trim()) return;
    setBusy(true);
    try {
      await createAssistDraft({
        draft_type: draftType,
        content: draftContent.trim(),
        session_id: sessionId || undefined,
      });
      setSaved(true);
      setTimeout(() => {
        setOpen(false);
        setSaved(false);
      }, 1200);
      onSaved?.();
    } catch {
      // non-blocking
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="mt-1.5 inline-flex items-center gap-1 text-[11px] font-semibold text-foreground-muted transition hover:text-primary"
      >
        <Save size={11} /> {t("assist.drafts.save")}
      </button>
    );
  }

  return (
    <form onSubmit={handleSave} className="mt-2 rounded-[12px] border border-border bg-background p-2.5">
      <div className="flex items-center gap-2">
        <label className="text-[10px] font-bold text-foreground-muted">{t("assist.drafts.type")}</label>
        <select
          value={draftType}
          onChange={(e) => setDraftType(e.target.value)}
          className="rounded-[8px] border border-border bg-surface px-2 py-1 text-[11px] text-foreground outline-none"
        >
          <option value="note">note</option>
          <option value="case_summary">case_summary</option>
          <option value="email">email</option>
        </select>
      </div>
      <textarea
        value={draftContent}
        onChange={(e) => setDraftContent(e.target.value)}
        rows={3}
        className="mt-2 w-full resize-none rounded-[10px] border border-border bg-surface px-2.5 py-2 text-[11px] text-foreground outline-none focus:border-primary"
      />
      <div className="mt-2 flex items-center gap-2">
        <button
          type="submit"
          disabled={busy || !draftContent.trim()}
          className={`inline-flex items-center gap-1.5 rounded-[8px] px-3 py-1.5 text-[11px] font-bold text-white transition disabled:opacity-60 ${ACCENT} ${ACCENT_HOVER}`}
        >
          {busy ? <Loader2 size={11} className="animate-spin" /> : saved ? <Check size={11} /> : null}
          {saved ? t("assist.drafts.saved") : t("assist.drafts.save")}
        </button>
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="rounded-[8px] px-2 py-1.5 text-[11px] font-semibold text-foreground-muted hover:text-foreground"
        >
          {t("assist.action.cancel")}
        </button>
      </div>
    </form>
  );
}

export function MessageBubble({ message, onFeedback, sessionId, onDraftSaved }) {
  const isUser = message.role === "user";
  if (isUser) {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-[16px] rounded-br-[4px] bg-primary px-3.5 py-2.5 text-[13px] leading-relaxed text-white">
          <p className="whitespace-pre-wrap">{message.content}</p>
        </div>
      </div>
    );
  }
  return (
    <div className="flex justify-start">
      <div className="max-w-[90%] rounded-[16px] rounded-bl-[4px] border border-border bg-surface px-3.5 py-2.5 text-[13px] leading-relaxed text-foreground shadow-[0_1px_3px_rgba(0,0,0,0.03)]">
        {message.loading ? (
          <span className="inline-flex items-center gap-2 text-[12px] text-foreground-muted">
            <Loader2 size={13} className="animate-spin text-primary" />
            {t("assist.sse.live")}
          </span>
        ) : (
          <p className="whitespace-pre-wrap">{message.content}</p>
        )}
        {message.actionBlock ? <ActionCard action={message.actionBlock} /> : null}
        {message.draftBlock ? (
          <p className="mt-2 flex items-center gap-1 text-[11px] font-semibold text-primary">
            <FileText size={12} /> {t("assist.drafts.ready")}
          </p>
        ) : null}
        {message.safetyState === "REFUSED" || message.safetyState === "SAFE_FALLBACK" ? (
          <p className="mt-2 flex items-center gap-1 text-[11px] font-semibold text-warning">
            <ShieldCheck size={12} /> {t("assist.refused", { state: message.safetyState.toLowerCase() })}
          </p>
        ) : null}
        <FeedbackRow message={message} onFeedback={onFeedback} />
        {!message.loading ? (
          <SaveDraftButton
            responseId={message.responseId}
            content={message.content}
            sessionId={sessionId}
            onSaved={onDraftSaved}
          />
        ) : null}
      </div>
    </div>
  );
}

function DraftsPanel({ sessionId }) {
  const [drafts, setDrafts] = useState(null);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(null);
  const [draftType, setDraftType] = useState("note");
  const [draftContent, setDraftContent] = useState("");

  async function load() {
    setBusy(true);
    try {
      setDrafts(await listAssistDrafts());
    } catch {
      setDrafts([]);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    load();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function resetForm() {
    setEditing(null);
    setDraftType("note");
    setDraftContent("");
  }

  async function handleSubmit(e) {
    e.preventDefault();
    if (!draftContent.trim()) return;
    setBusy(true);
    try {
      if (editing) {
        await updateAssistDraft(editing.id, { content: draftContent.trim() });
      } else {
        await createAssistDraft({ draft_type: draftType, content: draftContent.trim(), session_id: sessionId || undefined });
      }
      resetForm();
      await load();
    } catch {
      // non-blocking
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete(draft) {
    if (!window.confirm(t("assist.drafts.deleteConfirm"))) return;
    setBusy(true);
    try {
      await deleteAssistDraft(draft.id);
      await load();
    } catch {
      // non-blocking
    } finally {
      setBusy(false);
    }
  }

  if (drafts === null) {
    return (
      <div className="flex flex-1 items-center justify-center p-4">
        <Loader2 size={18} className="animate-spin text-primary" />
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex-1 space-y-2 overflow-y-auto p-3">
        {drafts.length === 0 ? (
          <p className="rounded-[12px] border border-dashed border-border px-3 py-6 text-center text-[12px] text-foreground-muted">
            {t("assist.drafts.empty")}
          </p>
        ) : (
          drafts.map((d) => (
            <div key={d.id} className="rounded-[12px] border border-border bg-surface p-2.5">
              <div className="flex items-center justify-between gap-2">
                <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[9px] font-bold uppercase text-primary">
                  {d.draft_type}
                </span>
                <div className="flex items-center gap-0.5">
                  <button
                    type="button"
                    onClick={() => {
                      setEditing(d);
                      setDraftType(d.draft_type);
                      setDraftContent(d.content);
                    }}
                    title={t("assist.drafts.edit")}
                    className="rounded-[8px] p-1 text-foreground-muted transition hover:text-primary"
                  >
                    <Pencil size={12} />
                  </button>
                  <button
                    type="button"
                    onClick={() => handleDelete(d)}
                    title={t("assist.drafts.delete")}
                    className="rounded-[8px] p-1 text-foreground-muted transition hover:text-error"
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              </div>
              <p className="mt-1.5 line-clamp-3 whitespace-pre-wrap text-[11px] leading-relaxed text-foreground">
                {d.content}
              </p>
              <p className="mt-1 text-[9px] text-foreground-muted">{formatAssistDate(d.updated_at || d.created_at)}</p>
            </div>
          ))
        )}
      </div>
      <form onSubmit={handleSubmit} className="border-t border-border-light p-3">
        <div className="flex items-center gap-2">
          <label className="text-[10px] font-bold text-foreground-muted">{t("assist.drafts.type")}</label>
          <select
            value={draftType}
            onChange={(e) => setDraftType(e.target.value)}
            className="rounded-[8px] border border-border bg-surface px-2 py-1 text-[11px] text-foreground outline-none"
          >
            <option value="note">note</option>
            <option value="case_summary">case_summary</option>
            <option value="email">email</option>
          </select>
        </div>
        <textarea
          value={draftContent}
          onChange={(e) => setDraftContent(e.target.value)}
          rows={3}
          placeholder={t("assist.drafts.content")}
          className="mt-2 w-full resize-none rounded-[10px] border border-border bg-background px-2.5 py-2 text-[11px] text-foreground placeholder-foreground-disabled outline-none focus:border-primary"
        />
        <button
          type="submit"
          disabled={busy || !draftContent.trim()}
          className={`mt-2 inline-flex w-full items-center justify-center gap-1.5 rounded-[10px] px-3 py-2 text-[11px] font-bold text-white transition disabled:opacity-60 ${ACCENT} ${ACCENT_HOVER}`}
        >
          {busy ? <Loader2 size={12} className="animate-spin" /> : editing ? <Pencil size={12} /> : <Plus size={12} />}
          {editing ? t("assist.drafts.edit") : t("assist.drafts.new")}
        </button>
      </form>
    </div>
  );
}

function HistoryPanel({ onResume }) {
  const [sessions, setSessions] = useState(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    setBusy(true);
    try {
      const data = await listAssistSessions({ limit: 50 });
      setSessions(data.sessions || []);
    } catch {
      setSessions([]);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    load();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function handleArchive(id) {
    setBusy(true);
    try {
      await archiveAssistSession(id);
      await load();
    } catch {
      // non-blocking
    } finally {
      setBusy(false);
    }
  }

  if (sessions === null) {
    return (
      <div className="flex flex-1 items-center justify-center p-4">
        <Loader2 size={18} className="animate-spin text-primary" />
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex-1 space-y-2 overflow-y-auto p-3">
        {sessions.length === 0 ? (
          <p className="rounded-[12px] border border-dashed border-border px-3 py-6 text-center text-[12px] text-foreground-muted">
            {t("assist.history.empty")}
          </p>
        ) : (
          sessions.map((s) => (
            <div key={s.id} className="rounded-[12px] border border-border bg-surface p-2.5">
              <div className="flex items-center justify-between gap-2">
                <p className="truncate text-[12px] font-bold text-foreground">{s.title || `Session #${s.id}`}</p>
                <span
                  className={`rounded-full px-2 py-0.5 text-[9px] font-bold uppercase ${
                    s.state === "ARCHIVED" ? "bg-background-secondary text-foreground-muted" : "bg-primary/10 text-primary-hover"
                  }`}
                >
                  {s.state === "ARCHIVED" ? t("assist.history.archived") : t("assist.history.active")}
                </span>
              </div>
              <p className="mt-1 text-[10px] text-foreground-muted">{formatAssistDate(s.created_at)}</p>
              <div className="mt-2 flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => onResume(s)}
                  className={`inline-flex items-center gap-1.5 rounded-[8px] px-2.5 py-1 text-[11px] font-bold text-white transition ${ACCENT} ${ACCENT_HOVER}`}
                >
                  <History size={11} /> {t("assist.history.resume")}
                </button>
                {s.state !== "ARCHIVED" ? (
                  <button
                    type="button"
                    onClick={() => handleArchive(s.id)}
                    disabled={busy}
                    className="rounded-[8px] px-2 py-1 text-[11px] font-semibold text-foreground-muted transition hover:text-error"
                  >
                    {t("assist.history.archive")}
                  </button>
                ) : null}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

export default function AssistLauncher() {
  const { user } = useAuth();
  const headingId = useId();
  const sessionKey = getSessionStorageKey(user?.id);
  const [open, setOpen] = useState(false);
  const [booting, setBooting] = useState(false);
  const [sending, setSending] = useState(false);
  const [notice, setNotice] = useState(null);
  const [ackDone, setAckDone] = useState(false);
  const [ackBusy, setAckBusy] = useState(false);
  const [sessionId, setSessionId] = useState(() => localStorage.getItem(sessionKey) || null);
  const [messages, setMessages] = useState([]);
  const [suggestions, setSuggestions] = useState([]);
  const [input, setInput] = useState("");
  const [error, setError] = useState("");
  const [tab, setTab] = useState("chat");
  const [showHandoff, setShowHandoff] = useState(false);
  const [showAbout, setShowAbout] = useState(false);
  const [pendingResponseId, setPendingResponseId] = useState(null);
  const [locale, setLocaleState] = useState(getAssistLocale());
  const [health, setHealth] = useState("checking");
  const [view, setView] = useState("home");
  const [activeTopicId, setActiveTopicId] = useState(null);
  const [feed, setFeed] = useState(null);
  const [feedState, setFeedState] = useState("loading");
  const scrollRef = useRef(null);
  const abortRef = useRef(null);
  const launcherRef = useRef(null);
  const headingRef = useRef(null);
  const textareaRef = useRef(null);
  const links = DEFAULT_LINKS;

  useEffect(() => {
    if (open && !booting && !sessionId) {
      bootSession();
    }
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (view === "chat") scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, open, tab, view]);

  useEffect(() => {
    if (open) headingRef.current?.focus();
  }, [open]);

  // Probe service health on every open — not only when a new session is
  // booted, since a stored session id skips bootSession entirely.
  useEffect(() => {
    if (!open) return;
    getAssistStatus().then((status) => {
      if (!status || status.status !== "ok") setHealth("unavailable");
      else setHealth(status.knowledge_available ? "available" : "degraded");
    });
  }, [open]);

  // Country coverage is the same public registry feed the website widget
  // uses — loaded once, on first open.
  useEffect(() => {
    if (!open || feed || feedState === "error") return;
    getPublicPayrollCountries(locale).then((f) => {
      setFeed(f);
      setFeedState(f && Array.isArray(f.countries) ? "ready" : "error");
    });
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  function minimize() {
    setOpen(false);
    launcherRef.current?.focus();
  }

  function close() {
    abortRef.current?.abort();
    setShowHandoff(false);
    minimize();
  }

  function changeLocale(code) {
    setAssistLocale(code);
    setLocaleState(code);
  }

  async function bootSession() {
    setBooting(true);
    setError("");
    try {
      const [currentNotice, sugg] = await Promise.all([
        getCurrentAssistNotice(),
        getAssistSuggestions(),
      ]);
      setNotice(currentNotice);
      setSuggestions(sugg);

      const session = await createAssistSession({ title: "Payroll Assist" });
      setSessionId(session.id);
      localStorage.setItem(sessionKey, String(session.id));
    } catch (e) {
      setError(!e?.status ? COPY.connectivity : e.message || t("assist.bootError"));
      setHealth("unavailable");
    } finally {
      setBooting(false);
    }
  }

  async function handleAcknowledge() {
    if (!notice) return;
    setAckBusy(true);
    try {
      await acknowledgeAssistNotice(notice.notice_version);
      setAckDone(true);
    } catch (e) {
      setError(e.message || t("assist.ackError"));
    } finally {
      setAckBusy(false);
    }
  }

  async function handleFeedback(message, rating) {
    if (!message.responseId) return;
    try {
      await submitAssistFeedback(message.responseId, { rating });
      setMessages((prev) => prev.map((m) => (m.id === message.id ? { ...m, rating } : m)));
    } catch {
      // ignore feedback errors — non-blocking
    }
  }

  async function sendMessage(text) {
    const trimmed = (text ?? input).trim();
    if (!trimmed || !sessionId || sending) return;
    setInput("");
    setError("");
    setView("chat");
    const isFirstMessage = messages.length === 0;
    const userMsg = { id: `u-${Date.now()}`, role: "user", content: trimmed };
    setMessages((prev) => [...prev, userMsg]);
    setSending(true);

    // History lists every session as "Payroll Assist" otherwise — every row
    // looked identical with no way to tell sessions apart. Rename once, from
    // the opening message, the same pattern chat apps title conversations by.
    // Fire-and-forget: renaming is cosmetic, never worth blocking or failing
    // the actual send over.
    if (isFirstMessage) {
      const derivedTitle = trimmed.replace(/\s+/g, " ").slice(0, 60) + (trimmed.length > 60 ? "…" : "");
      updateAssistSession(sessionId, { title: derivedTitle }).catch(() => {});
    }

    const pendingId = `a-${Date.now()}`;
    const patch = (updater) => setMessages((prev) => prev.map((m) => (m.id === pendingId ? updater(m) : m)));

    setMessages((prev) => [
      ...prev,
      { id: pendingId, role: "assistant", content: "", loading: true, sources: [] },
    ]);

    const controller = new AbortController();
    abortRef.current = controller;

    async function submitTo(sid) {
      const submit = await submitAssistMessage(sid, trimmed);
      setPendingResponseId(submit.response_id);
      let streamed = "";
      const [response] = await Promise.all([
        getAssistResponse(submit.response_id),
        streamAssistResponseEvents(submit.response_id, {
          signal: controller.signal,
          onEvent: (event) => {
            if (event.event_type === "assistant_response_block" && event.data?.block_type === "text") {
              streamed = event.data.content || streamed;
              patch((m) => ({ ...m, content: streamed || m.content }));
            }
          },
        }).catch(() => {}),
      ]);
      return { response, streamed };
    }

    try {
      let response, streamed;
      try {
        ({ response, streamed } = await submitTo(sessionId));
      } catch (e) {
        // The stored session id can go stale — e.g. a different user logged
        // in on this browser previously (fixed by scoping the storage key
        // per user, but old stale entries may still be lying around), or
        // the session was archived by retention cleanup while this tab was
        // open. Recover once by starting a fresh session instead of
        // leaving the widget permanently stuck on a dead session id.
        if (e?.status === 404) {
          const session = await createAssistSession({ title: "Payroll Assist" });
          setSessionId(session.id);
          localStorage.setItem(sessionKey, String(session.id));
          ({ response, streamed } = await submitTo(session.id));
        } else {
          throw e;
        }
      }

      const textBlock = (response.blocks || []).find((b) => b.block_type === "text");
      const actionBlock = (response.blocks || []).find((b) => b.block_type === "action");
      const draftBlock = (response.blocks || []).find((b) => b.block_type === "draft");
      patch((m) => ({
        id: pendingId,
        role: "assistant",
        content: textBlock?.content || (streamed || t("assist.genError")),
        responseId: response.id,
        safetyState: response.safety_state,
        intentId: response.intent_id,
        engine: response.engine,
        sources: response.sources || [],
        actionBlock: actionBlock?.data || null,
        draftBlock: draftBlock?.data || null,
        rating: null,
        loading: false,
      }));
    } catch (e) {
      if (e?.name === "AbortError") {
        patch((m) => ({ ...m, content: m.content || t("assist.stopped"), loading: false, stopped: true }));
        return;
      }
      // A network failure (backend down, CORS, offline) has no HTTP status —
      // show the recoverable connectivity copy, never the browser's raw
      // "Failed to fetch".
      const networkFailure = !e?.status;
      if (networkFailure) setHealth("unavailable");
      patch((m) => ({
        id: pendingId,
        role: "assistant",
        content: networkFailure ? COPY.connectivity : e.message || t("assist.sendError"),
        loading: false,
      }));
    } finally {
      setSending(false);
      setPendingResponseId(null);
    }
  }

  async function handleStop() {
    if (pendingResponseId) {
      stopAssistResponse(pendingResponseId).catch(() => {});
    }
    abortRef.current?.abort();
  }

  async function handleNewSession() {
    abortRef.current?.abort();
    if (sessionId) {
      try {
        await archiveAssistSession(sessionId);
      } catch {
        // best effort
      }
    }
    localStorage.removeItem(sessionKey);
    setSessionId(null);
    setMessages([]);
    setAckDone(false);
    setNotice(null);
    setError("");
    setTab("chat");
    setView("home");
    setActiveTopicId(null);
    await bootSession();
  }

  async function handleResume(session) {
    setTab("chat");
    setView("chat");
    setSessionId(session.id);
    localStorage.setItem(sessionKey, String(session.id));
    setMessages([]);
    setError("");
    try {
      const msgs = await listAssistMessages(session.id);
      // Every stored message is the user's side — the assistant's reply is a
      // separate AssistResponse linked via response_id, not a second message
      // row. Fetch each linked response in parallel, then interleave them
      // back into conversational order (user, its reply, next user, ...).
      const responseByMessageId = new Map(
        await Promise.all(
          msgs
            .filter((m) => m.response_id)
            .map(async (m) => {
              try {
                const response = await getAssistResponse(m.response_id);
                const textBlock = (response.blocks || []).find((b) => b.block_type === "text");
                const actionBlock = (response.blocks || []).find((b) => b.block_type === "action");
                const draftBlock = (response.blocks || []).find((b) => b.block_type === "draft");
                return [m.id, {
                  id: `r-${m.response_id}`,
                  role: "assistant",
                  content: textBlock?.content || "…",
                  responseId: m.response_id,
                  safetyState: response.safety_state,
                  sources: response.sources || [],
                  actionBlock: actionBlock?.data || null,
                  draftBlock: draftBlock?.data || null,
                  rating: null,
                  loading: false,
                }];
              } catch {
                return [m.id, { id: `r-${m.response_id}`, role: "assistant", content: "…", loading: false }];
              }
            })
        )
      );
      const flattened = [];
      for (const m of msgs) {
        flattened.push({ id: `h-u-${m.id}`, role: "user", content: m.content?.text || m.content || "…" });
        const resp = responseByMessageId.get(m.id);
        if (resp) flattened.push(resp);
      }
      setMessages(flattened);
    } catch {
      setError(t("assist.sendError"));
    }
  }

  const noticeGateShown = notice && notice.required && !notice.acknowledged && !ackDone;

  const tabs = [
    { id: "chat", label: t("assist.tabs.chat"), icon: Sparkles },
    { id: "drafts", label: t("assist.tabs.drafts"), icon: FileText },
    { id: "history", label: t("assist.tabs.history"), icon: History },
  ];

  const locales = Object.entries(ASSIST_LOCALES).map(([code, meta]) => ({ code, label: meta.name }));
  // Server-curated suggestions are the signed-in "popular questions"; the
  // approved public six are the fallback when none are configured.
  const popularQuestions = suggestions.length
    ? suggestions.slice(0, 6).map((s) => ({ id: `${s.intent_id}-${s.position}`, label: s.prompt }))
    : POPULAR_QUESTIONS;
  const hasConversation = messages.length > 0;

  function handleTopicPrompt(prompt) {
    if (prompt.mode === "prefill") {
      setInput(prompt.prefill);
      requestAnimationFrame(() => {
        const el = textareaRef.current;
        if (!el) return;
        el.focus();
        el.setSelectionRange(el.value.length, el.value.length);
      });
      return;
    }
    sendMessage(prompt.label);
  }

  const toolButton = `inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-[10px] text-foreground-muted transition hover:bg-surface-muted hover:text-primary ${FOCUS_RING}`;

  return createPortal(
    <>
      <ConciergeLauncher
        ref={launcherRef}
        open={open}
        onToggle={() => (open ? minimize() : setOpen(true))}
        iconSrc={zoikoPayrollIcon}
        label={open ? t("assist.close") : t("assist.open")}
      />

      {open ? (
        <div
          role="dialog"
          aria-labelledby={headingId}
          lang={locale}
          className={PANEL_CLASS}
          onKeyDown={(e) => {
            if (e.key === "Escape" && !showAbout) {
              e.preventDefault();
              minimize();
            }
          }}
        >
          {showAbout ? <AboutAssistPanel onClose={() => setShowAbout(false)} /> : null}

          <ConciergeHeader
            logoSrc={zoikoPayrollLogo}
            headingId={headingId}
            headingRef={headingRef}
            status={booting ? "checking" : health}
            locales={locales}
            locale={locale}
            onLocaleChange={changeLocale}
            onMinimize={minimize}
            onClose={close}
          />

          {/* Tabs + session tools */}
          <div className="flex items-center gap-1 border-b border-border-light bg-surface px-2 md:px-3">
            <div role="tablist" aria-label={t("assist.title")} className="flex flex-1">
              {tabs.map((tabDef) => {
                const Icon = tabDef.icon;
                return (
                  <button
                    key={tabDef.id}
                    type="button"
                    role="tab"
                    aria-selected={tab === tabDef.id}
                    onClick={() => setTab(tabDef.id)}
                    className={`flex flex-1 items-center justify-center gap-1.5 border-b-2 px-2 py-2.5 text-[12px] font-bold transition ${FOCUS_RING} ${
                      tab === tabDef.id
                        ? "border-primary text-primary"
                        : "border-transparent text-foreground-muted hover:text-foreground"
                    }`}
                  >
                    <Icon size={13} aria-hidden="true" /> {tabDef.label}
                  </button>
                );
              })}
            </div>
            <button
              type="button"
              onClick={() => setShowHandoff((v) => !v)}
              title={t("assist.handoff.title")}
              aria-label={t("assist.handoff.title")}
              aria-pressed={showHandoff}
              className={`${toolButton} ${showHandoff ? "bg-surface-muted text-primary" : ""}`}
            >
              <LifeBuoy size={16} aria-hidden="true" />
            </button>
            <button
              type="button"
              onClick={handleNewSession}
              title={t("assist.newSession")}
              aria-label={t("assist.newSession")}
              className={toolButton}
            >
              <RotateCcw size={16} aria-hidden="true" />
            </button>
            <button
              type="button"
              onClick={() => setShowAbout(true)}
              title={t("assist.about")}
              aria-label={t("assist.about")}
              className={toolButton}
            >
              <Info size={16} aria-hidden="true" />
            </button>
          </div>

          {/* Body */}
          <div className="flex min-h-0 flex-1 flex-col">
            {booting ? (
              <div className="flex flex-1 items-center justify-center">
                <Loader2
                  size={22}
                  className="animate-spin text-primary motion-reduce:animate-none"
                  aria-label={t("assist.thinking")}
                />
              </div>
            ) : noticeGateShown && tab === "chat" ? (
              <div className="flex-1">
                <NoticeGate notice={notice} onAcknowledge={handleAcknowledge} busy={ackBusy} />
              </div>
            ) : tab === "drafts" ? (
              <DraftsPanel sessionId={sessionId} />
            ) : tab === "history" ? (
              <HistoryPanel onResume={handleResume} />
            ) : (
              <>
                {showHandoff ? (
                  <HandoffPanel sessionId={sessionId} onClose={() => setShowHandoff(false)} />
                ) : null}
                <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto overscroll-contain bg-surface">
                  {error ? (
                    <p
                      role="alert"
                      className="mx-4 mt-4 rounded-[12px] bg-error-light px-3 py-2 text-[12px] font-medium text-error md:mx-5"
                    >
                      {error}
                    </p>
                  ) : null}
                  {view === "home" ? (
                    <div className="space-y-4 px-4 py-4 md:px-5">
                      {hasConversation ? (
                        <button
                          type="button"
                          onClick={() => setView("chat")}
                          className={`inline-flex items-center gap-1.5 rounded-[8px] text-[12px] font-semibold text-primary hover:underline ${FOCUS_RING}`}
                        >
                          <ArrowLeft size={14} aria-hidden="true" /> Back to conversation
                        </button>
                      ) : null}
                      <WelcomeBlock
                        iconSrc={zoikoPayrollIcon}
                        compact={hasConversation}
                        body={t("assist.intro", { name: "Zoiko Payroll Assist" })}
                      />
                      <TopicGrid
                        topics={TOPICS}
                        activeTopicId={activeTopicId}
                        onSelectTopic={setActiveTopicId}
                        onBack={() => setActiveTopicId(null)}
                        onPrompt={handleTopicPrompt}
                        disabled={sending || !sessionId}
                      />
                      <CountryCheck
                        feed={feed}
                        feedState={feedState}
                        links={links}
                        disabled={sending || !sessionId}
                        onAsk={(country) => sendMessage(`How does payroll work in ${country.name}?`)}
                      />
                      <div className="border-t border-border-light" aria-hidden="true" />
                      <PopularQuestions
                        questions={popularQuestions}
                        disabled={sending || !sessionId}
                        faqUrl={links.faq}
                        links={links}
                        onPick={(q) => sendMessage(q.label)}
                      />
                      {/* Signed-in users already have an account, so the
                          commercial CTAs are dropped; support routes to the
                          existing governed handoff flow. */}
                      <CtaRow links={{}} onSupport={() => setShowHandoff(true)} supportExpanded={showHandoff} />
                    </div>
                  ) : (
                    <div className="space-y-3 px-4 py-4 md:px-5">
                      <WelcomeBlock iconSrc={zoikoPayrollIcon} compact />
                      <div role="log" aria-label={t("assist.title")} className="space-y-3">
                        {messages.map((m) => (
                          <MessageBubble
                            key={m.id}
                            message={m}
                            onFeedback={handleFeedback}
                            sessionId={sessionId}
                            onDraftSaved={() => {}}
                          />
                        ))}
                      </div>
                      {sending && !messages[messages.length - 1]?.loading ? (
                        <ThinkingBubble iconSrc={zoikoPayrollIcon} />
                      ) : null}
                    </div>
                  )}
                  {/* Screen-reader-only status announcer — separate from the
                      visible streaming text so assistive tech gets one concise
                      state change, not a re-read on every appended character. */}
                  <div aria-live="polite" aria-atomic="true" className="sr-only">
                    {sending
                      ? t("assist.thinking")
                      : messages[messages.length - 1]?.loading
                        ? t("assist.sse.live")
                        : ""}
                  </div>
                </div>

                <ConciergeComposer
                  ref={textareaRef}
                  value={input}
                  onChange={setInput}
                  onSubmit={() => sendMessage()}
                  sending={sending}
                  onStop={handleStop}
                  disabled={!sessionId}
                  maxLength={MAX_MESSAGE_LENGTH}
                  notice={t("assist.footer")}
                  showTopicsButton={view === "chat"}
                  onShowTopics={() => setView("home")}
                />
              </>
            )}
          </div>
        </div>
      ) : null}
    </>,
    document.body
  );
}
