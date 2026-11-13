import { useEffect, useState } from "react";
import { Clock, Loader2 } from "lucide-react";
import Modal from "./Modal";
import {
  SESSION_WARNING_MS,
  endSession,
  getSessionDeadline,
  markUserActivity,
  tryRefreshToken,
} from "../service/api";

function formatRemaining(ms) {
  const total = Math.max(0, Math.ceil(ms / 1000));
  const minutes = Math.floor(total / 60);
  const seconds = String(total % 60).padStart(2, "0");
  return `${minutes}:${seconds}`;
}

// One instance, mounted in main.jsx. Privileged sessions (org admin, super
// admin, ...) end on the server after PRIVILEGED_REFRESH_IDLE_MINUTES without
// a token refresh. Active users are refreshed automatically by
// service/api.js; this warns an idle user shortly before the deadline so they
// can stay signed in instead of losing unsaved work to a silent sign-out.
export default function SessionTimeoutWarning() {
  const [now, setNow] = useState(() => Date.now());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  const deadline = getSessionDeadline();
  const remaining = deadline ? deadline - now : null;
  const expired = remaining !== null && remaining <= 0;
  const warning = remaining !== null && remaining > 0 && remaining <= SESSION_WARNING_MS;

  useEffect(() => {
    // The server will refuse this session's refresh token from now on; end
    // it cleanly so the user lands on sign-in with the "session expired"
    // notice rather than on a page whose requests start failing.
    if (expired) endSession("idle_timeout");
  }, [expired]);

  async function staySignedIn() {
    setBusy(true);
    setError(null);
    markUserActivity();
    const result = await tryRefreshToken();
    setBusy(false);
    if (!result?.ok && !result?.invalidSession) {
      setError("Couldn't reach the server. Check your connection and try again.");
    }
  }

  if (!warning) return null;

  return (
    <Modal title="Your session is about to expire" onClose={staySignedIn} maxWidth="max-w-sm">
      <div className="space-y-4">
        <div className="flex items-start gap-3 text-sm text-foreground-muted">
          <Clock className="mt-0.5 h-5 w-5 shrink-0 text-warning" aria-hidden="true" />
          <p>
            For your security you will be signed out after a period of inactivity. You will be signed out in{" "}
            <span className="font-semibold text-foreground tabular-nums" aria-live="polite">
              {formatRemaining(remaining)}
            </span>
            .
          </p>
        </div>
        {error && <p role="alert" className="text-sm text-error">{error}</p>}
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={() => endSession("signed_out")}
            className="rounded-lg border border-border bg-surface-muted px-4 py-2 text-sm font-semibold text-foreground-muted transition hover:border-primary hover:text-primary"
          >
            Sign out
          </button>
          <button
            type="button"
            onClick={staySignedIn}
            disabled={busy}
            autoFocus
            className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-bold text-white transition hover:bg-primary-hover disabled:opacity-60"
          >
            {busy ? <Loader2 size={14} className="animate-spin" aria-hidden="true" /> : null}
            Stay signed in
          </button>
        </div>
      </div>
    </Modal>
  );
}
