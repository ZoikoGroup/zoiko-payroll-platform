import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { X, Send, Loader2, ShieldCheck } from "lucide-react";
import {
  createPublicAssistSession,
  submitPublicAssistMessage,
  listPublicAssistMessages,
} from "../../service/assistService";
import zoikoPayrollLogo from "../../assets/zoiko-payroll-logo.png";
import zoikoPayrollIcon from "../../assets/zoiko-payroll-icon.png";

// Anonymous-visitor variant of AssistLauncher: no auth, no drafts/history/
// handoff tabs, no per-user session scoping — just one KB-grounded Q&A
// thread per browser tab, backed by the /assist/public/* endpoints.
const SESSION_KEY = "zoiko_payroll_public_assist_session";

export default function PublicAssistWidget() {
  const [open, setOpen] = useState(false);
  const [sessionId, setSessionId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState(null);
  const [booting, setBooting] = useState(false);
  const scrollRef = useRef(null);

  useEffect(() => {
    if (!open || sessionId || booting) return;
    setBooting(true);
    (async () => {
      try {
        const existing = sessionStorage.getItem(SESSION_KEY);
        if (existing) {
          const id = Number(existing);
          const history = await listPublicAssistMessages(id);
          setSessionId(id);
          setMessages(history.map((m) => ({ id: `h-${m.id}`, role: m.role, content: m.content })));
        } else {
          const session = await createPublicAssistSession({ locale: "en" });
          sessionStorage.setItem(SESSION_KEY, String(session.id));
          setSessionId(session.id);
        }
      } catch {
        setError("Assist is temporarily unavailable. Please try again shortly.");
      } finally {
        setBooting(false);
      }
    })();
  }, [open, sessionId, booting]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, sending]);

  async function sendMessage(text) {
    const content = (text ?? input).trim();
    if (!content || sending || !sessionId) return;
    setInput("");
    setError(null);
    setMessages((prev) => [...prev, { id: `u-${Date.now()}`, role: "user", content }]);
    setSending(true);
    try {
      const result = await submitPublicAssistMessage(sessionId, content);
      setMessages((prev) => [
        ...prev,
        { id: `a-${Date.now()}`, role: "assistant", content: result.answer, sources: result.sources },
      ]);
    } catch (err) {
      setError(err?.message || "Something went wrong sending that message.");
    } finally {
      setSending(false);
    }
  }

  return createPortal(
    <>
      <style>{`
        @keyframes publicAssistGlow {
          0%, 100% { opacity: 0.55; transform: scale(1); }
          50% { opacity: 0.9; transform: scale(1.12); }
        }
        .public-assist-glow { animation: publicAssistGlow 2.8s ease-in-out infinite; }
        @media (prefers-reduced-motion: reduce) {
          .public-assist-glow { animation: none; }
        }
      `}</style>
      <div className="fixed bottom-6 right-6 z-[9997] h-14 w-14">
        <div
          aria-hidden="true"
          className={`public-assist-glow pointer-events-none absolute inset-0 rounded-2xl bg-primary blur-xl transition-opacity duration-300 ${
            open ? "opacity-80" : "opacity-55"
          }`}
        />
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-label={open ? "Close Assist" : "Open Zoiko Payroll Assist"}
          className={`relative flex h-14 w-14 items-center justify-center overflow-hidden rounded-2xl bg-[radial-gradient(circle_at_32%_26%,var(--color-primary-hover)_0%,var(--color-primary)_55%,var(--color-primary-active)_100%)] shadow-[inset_0_1px_1px_rgba(255,255,255,0.35),inset_0_-8px_14px_-6px_rgba(0,0,0,0.4),0_16px_30px_-8px_rgba(0,0,0,0.45)] transition-all duration-200 hover:-translate-y-[3px] hover:scale-[1.04] hover:shadow-[inset_0_1px_1px_rgba(255,255,255,0.45),inset_0_-8px_14px_-6px_rgba(0,0,0,0.4),0_20px_36px_-8px_rgba(0,0,0,0.5)] active:translate-y-0 active:scale-100 ${
            open ? "rotate-90 text-white" : ""
          }`}
        >
          {open ? <X size={22} /> : <img src={zoikoPayrollIcon} alt="" className="h-full w-full object-cover" />}
        </button>
      </div>

      {open ? (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Zoiko Payroll Assist"
          className="fixed inset-0 z-[9997] flex flex-col overflow-hidden bg-white sm:inset-auto sm:bottom-24 sm:right-6 sm:h-[560px] sm:max-h-[calc(100dvh-8rem)] sm:w-[min(550px,calc(100vw-2rem))] sm:max-w-[calc(100vw-2rem)] sm:rounded-[22px] sm:border sm:border-border sm:shadow-[0_24px_64px_rgba(0,0,0,0.18)] lg:w-[380px]"
        >
          <div className="flex items-center justify-between border-b border-border bg-white px-4 py-3">
            <div className="flex items-center gap-2.5">
              <img src={zoikoPayrollLogo} alt="" className="h-6 w-auto shrink-0" />
              <div className="h-5 w-px shrink-0 bg-border-light" />
              <p className="text-[13px] font-bold tracking-wide text-primary">Zoiko Payroll Assist</p>
            </div>
            <button
              type="button"
              onClick={() => setOpen(false)}
              title="Close"
              aria-label="Close"
              className="rounded-[10px] p-1.5 text-foreground-muted transition hover:bg-background hover:text-primary"
            >
              <X size={16} />
            </button>
          </div>

          <div className="flex min-h-0 flex-1 flex-col">
            {booting ? (
              <div className="flex flex-1 items-center justify-center">
                <Loader2 size={22} className="animate-spin text-primary" />
              </div>
            ) : (
              <>
                <div ref={scrollRef} className="min-h-0 flex-1 space-y-3 overflow-y-auto bg-background-secondary p-4">
                  {error ? (
                    <p className="rounded-[12px] bg-error-light px-3 py-2 text-[12px] font-medium text-error">{error}</p>
                  ) : null}
                  {messages.length === 0 ? (
                    <div className="rounded-[16px] rounded-bl-[4px] border border-border bg-white px-3.5 py-2.5 text-[13px] leading-relaxed text-foreground">
                      <p>
                        Hi! I'm Zoiko Payroll Assist. Ask me general questions about payroll, payslips, taxes, or
                        how Zoiko Payroll works. Sign in for account-specific help.
                      </p>
                    </div>
                  ) : (
                    messages.map((m) => (
                      <div key={m.id} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
                        <div
                          className={`max-w-[85%] whitespace-pre-wrap rounded-[16px] px-3.5 py-2.5 text-[13px] leading-relaxed ${
                            m.role === "user"
                              ? "rounded-br-[4px] bg-primary text-white"
                              : "rounded-bl-[4px] border border-border bg-white text-foreground"
                          }`}
                        >
                          {m.content}
                          {m.sources?.length ? (
                            <div className="mt-2 flex flex-wrap gap-1">
                              {m.sources.map((s, i) => (
                                <span
                                  key={i}
                                  className="rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-semibold text-primary"
                                >
                                  {s.title}
                                </span>
                              ))}
                            </div>
                          ) : null}
                        </div>
                      </div>
                    ))
                  )}
                  {sending ? (
                    <div className="flex justify-start">
                      <div className="flex items-center gap-2 rounded-[16px] rounded-bl-[4px] border border-border bg-white px-3.5 py-2.5 text-[12px] text-foreground-muted">
                        <Loader2 size={14} className="animate-spin text-primary" />
                        Thinking…
                      </div>
                    </div>
                  ) : null}
                </div>

                <div className="border-t border-border-light p-3">
                  <form
                    onSubmit={(e) => {
                      e.preventDefault();
                      sendMessage();
                    }}
                    className="flex items-end gap-2"
                  >
                    <textarea
                      value={input}
                      onChange={(e) => setInput(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && !e.shiftKey) {
                          e.preventDefault();
                          sendMessage();
                        }
                      }}
                      rows={1}
                      placeholder="Ask a question…"
                      className="max-h-28 flex-1 resize-none rounded-[12px] border border-border bg-background px-3 py-2.5 text-[13px] text-foreground placeholder-foreground-disabled outline-none transition focus:border-primary"
                    />
                    <button
                      type="submit"
                      disabled={!input.trim() || sending}
                      className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-[12px] bg-primary text-white transition hover:bg-primary-hover disabled:opacity-40"
                    >
                      <Send size={16} />
                    </button>
                  </form>
                  <p className="mt-2 flex items-center gap-1 text-[10px] text-foreground-disabled">
                    <ShieldCheck size={11} className="text-primary" />
                    General information only — sign in for account-specific help.
                  </p>
                </div>
              </>
            )}
          </div>
        </div>
      ) : null}
    </>,
    document.body
  );
}
