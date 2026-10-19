import { useEffect, useRef, useState } from "react";
import { ShieldCheck, Loader2 } from "lucide-react";
import Modal from "./Modal";
import { mfaService } from "../service/mfaService";
import { registerStepUpHandler } from "../utils/stepUp";

// One instance, mounted in main.jsx. Opens whenever an API call answers
// 403 STEP_UP_REQUIRED (ZP-PRIV B08): the user enters a fresh authenticator
// code (or a recovery code), the fresh access token is stored, and the
// original request is retried by the API client.
export default function StepUpAuthModal() {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [code, setCode] = useState("");
  const [useRecovery, setUseRecovery] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const resolver = useRef(null);

  useEffect(
    () =>
      registerStepUpHandler(
        (why) =>
          new Promise((resolve) => {
            resolver.current = resolve;
            setReason(why || "");
            setCode("");
            setError(null);
            setUseRecovery(false);
            setOpen(true);
          }),
      ),
    [],
  );

  function finish(result) {
    setOpen(false);
    const resolve = resolver.current;
    resolver.current = null;
    if (resolve) resolve(result);
  }

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await mfaService.stepUp(useRecovery ? { recoveryCode: code } : { code });
      finish(true);
    } catch (err) {
      setError(err.message || "That code is not valid.");
    } finally {
      setBusy(false);
    }
  }

  if (!open) return null;
  return (
    <Modal title="Confirm it's you" onClose={() => finish(false)} maxWidth="max-w-sm">
      <form onSubmit={submit} className="space-y-4">
        <div className="flex items-start gap-3 text-sm text-slate-600 dark:text-slate-300">
          <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-blue-600" aria-hidden="true" />
          <p>
            {reason || "This action needs a fresh authentication code."} Enter the
            {useRecovery ? " recovery code" : " 6-digit code from your authenticator app"}.
          </p>
        </div>
        <input
          autoFocus
          inputMode={useRecovery ? "text" : "numeric"}
          autoComplete="one-time-code"
          value={code}
          onChange={(e) => setCode(e.target.value.trim())}
          placeholder={useRecovery ? "xxxxx-xxxxx" : "123456"}
          aria-label={useRecovery ? "Recovery code" : "Authentication code"}
          className="w-full rounded-lg border border-slate-300 px-3 py-2 text-center text-lg tracking-widest dark:border-slate-600 dark:bg-slate-900 dark:text-white"
        />
        {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
        <div className="flex items-center justify-between gap-2">
          <button
            type="button"
            onClick={() => setUseRecovery((v) => !v)}
            className="text-xs text-blue-600 hover:underline"
          >
            {useRecovery ? "Use authenticator code" : "Use a recovery code"}
          </button>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => finish(false)}
              className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm dark:border-slate-600 dark:text-slate-200"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={busy || !code}
              className="inline-flex items-center gap-1 rounded-lg bg-blue-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
            >
              {busy && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />} Verify
            </button>
          </div>
        </div>
      </form>
    </Modal>
  );
}
