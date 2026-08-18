import { useEffect, useRef, useState } from "react";
import { Send, ShieldCheck, Sparkles, Loader2 } from "lucide-react";
import {
  acknowledgeAssistNotice,
  getAssistResponse,
  getAssistSuggestions,
  getCurrentAssistNotice,
  submitAssistFeedback,
  submitAssistMessage,
  createAssistSession,
  streamAssistResponseEvents,
} from "../../service/assistService";
import { t } from "./locales";
import { MessageBubble } from "./AssistLauncher";

const ACCENT = "bg-primary";
const ACCENT_HOVER = "hover:bg-primary-hover";

/**
 * Assist, embedded inline on a specific page rather than the floating
 * widget — a session is created bound to `contextObject` so every question
 * is automatically scoped to it (e.g. "is this run ready?" resolves against
 * *this* run without the user needing to say which one).
 */
export default function AssistInlinePanel({ contextObject, title, subtitle }) {
  const [booting, setBooting] = useState(true);
  const [sending, setSending] = useState(false);
  const [notice, setNotice] = useState(null);
  const [ackDone, setAckDone] = useState(false);
  const [ackBusy, setAckBusy] = useState(false);
  const [sessionId, setSessionId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [suggestions, setSuggestions] = useState([]);
  const [input, setInput] = useState("");
  const [error, setError] = useState("");
  const scrollRef = useRef(null);
  const bootedRef = useRef(null);

  useEffect(() => {
    const key = `${contextObject?.type || ""}:${contextObject?.id || ""}`;
    if (bootedRef.current === key) return;
    bootedRef.current = key;
    setMessages([]);
    setSessionId(null);
    bootSession();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [contextObject?.type, contextObject?.id]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

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
      // ContextObjectRef.id is typed as a string on the backend — a raw
      // numeric id (the natural JS type for most ids here) fails Pydantic
      // validation outright, so always coerce it before sending.
      const context = contextObject
        ? { object: { ...contextObject, id: String(contextObject.id) } }
        : undefined;
      const session = await createAssistSession({
        title: title || "Payroll Assist",
        context,
      });
      setSessionId(session.id);
    } catch (e) {
      setError(e.message || t("assist.bootError"));
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
      // non-blocking
    }
  }

  async function sendMessage(text) {
    const trimmed = (text ?? input).trim();
    if (!trimmed || !sessionId || sending) return;
    setInput("");
    setError("");
    setMessages((prev) => [...prev, { id: `u-${Date.now()}`, role: "user", content: trimmed }]);
    setSending(true);

    const pendingId = `a-${Date.now()}`;
    const patch = (updater) => setMessages((prev) => prev.map((m) => (m.id === pendingId ? updater(m) : m)));
    setMessages((prev) => [...prev, { id: pendingId, role: "assistant", content: "", loading: true }]);

    try {
      const submit = await submitAssistMessage(sessionId, trimmed);
      let streamed = "";
      const [response] = await Promise.all([
        getAssistResponse(submit.response_id),
        streamAssistResponseEvents(submit.response_id, {
          onEvent: (event) => {
            if (event.event_type === "assistant_response_block" && event.data?.block_type === "text") {
              streamed = event.data.content || streamed;
              patch((m) => ({ ...m, content: streamed || m.content }));
            }
          },
        }).catch(() => {}),
      ]);
      const textBlock = (response.blocks || []).find((b) => b.block_type === "text");
      patch((m) => ({
        ...m,
        content: textBlock?.content || streamed || t("assist.genError"),
        responseId: response.id,
        safetyState: response.safety_state,
        rating: null,
        loading: false,
      }));
    } catch (e) {
      patch((m) => ({ ...m, content: e.message || t("assist.sendError"), loading: false }));
    } finally {
      setSending(false);
    }
  }

  const noticeGateShown = notice && notice.required && !notice.acknowledged && !ackDone;

  return (
    <div className="flex h-[480px] flex-col rounded-[18px] border border-border bg-surface shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
      <div className="flex items-center gap-2 border-b border-border px-4 py-3">
        <Sparkles size={15} className="text-primary" />
        <p className="text-[13px] font-bold text-foreground">{title || "Ask Assist about this run"}</p>
      </div>

      {booting ? (
        <div className="flex flex-1 items-center justify-center">
          <Loader2 size={20} className="animate-spin text-primary" />
        </div>
      ) : noticeGateShown ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 px-6 text-center">
          <ShieldCheck className="h-6 w-6 text-primary" />
          <p className="text-[13px] font-bold text-foreground">{t("assist.notice.title")}</p>
          <p className="text-[12px] leading-relaxed text-foreground-muted">{notice?.content}</p>
          <button
            type="button"
            onClick={handleAcknowledge}
            disabled={ackBusy}
            className={`inline-flex items-center gap-2 rounded-[10px] px-4 py-2 text-[12px] font-bold text-white ${ACCENT} ${ACCENT_HOVER} disabled:opacity-60`}
          >
            {ackBusy ? <Loader2 size={13} className="animate-spin" /> : null}
            {t("assist.notice.acknowledge")}
          </button>
        </div>
      ) : (
        <>
          <div ref={scrollRef} className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-4">
            {error ? <p className="rounded-[10px] bg-error-light px-3 py-2 text-[12px] text-error">{error}</p> : null}
            {messages.length === 0 ? (
              <div className="flex flex-col gap-3">
                <div className="max-w-[90%] rounded-[14px] rounded-bl-[4px] border border-border bg-white px-3.5 py-2.5 text-[13px] text-foreground">
                  {subtitle || "Ask about this run's readiness, exceptions, or status — I'll answer using only this run's own data."}
                </div>
                {suggestions.length ? (
                  <div className="flex flex-wrap gap-2">
                    {suggestions.slice(0, 3).map((s) => (
                      <button
                        key={s.intent_id + s.position}
                        type="button"
                        onClick={() => sendMessage(s.prompt)}
                        className="rounded-[10px] border border-border bg-white px-2.5 py-1.5 text-left text-[11px] font-medium text-foreground-muted transition hover:border-primary hover:text-primary"
                      >
                        {s.prompt}
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>
            ) : (
              messages.map((m) => (
                <MessageBubble key={m.id} message={m} onFeedback={handleFeedback} sessionId={sessionId} onDraftSaved={() => {}} />
              ))
            )}
          </div>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              sendMessage();
            }}
            className="flex items-center gap-2 border-t border-border px-3 py-3"
          >
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={t("assist.placeholder")}
              disabled={sending}
              className="min-w-0 flex-1 rounded-[10px] border border-border bg-white px-3 py-2 text-[13px] text-foreground outline-none focus:border-primary disabled:opacity-60"
            />
            <button
              type="submit"
              disabled={sending || !input.trim()}
              className={`inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-[10px] text-white transition disabled:opacity-40 ${ACCENT} ${ACCENT_HOVER}`}
            >
              {sending ? <Loader2 size={15} className="animate-spin" /> : <Send size={15} />}
            </button>
          </form>
        </>
      )}
    </div>
  );
}
