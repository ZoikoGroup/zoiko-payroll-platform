import { useEffect, useState } from "react";
import QRCode from "qrcode";
import { Loader2, ShieldCheck, Copy, Check } from "lucide-react";
import { mfaService } from "../service/mfaService";

// The second sign-in step (ZP-PRIV B08), used by login and registration.
//   mode="challenge": enter a TOTP or recovery code.
//   mode="enroll":    mandatory setup for privileged roles - scan the QR (or
//                     type the key), confirm one code, then save the recovery
//                     codes, which are shown exactly once.
// onComplete(session) receives the login response (access + refresh token).
export default function MfaLoginStep({ mode, mfaToken, onComplete, onCancel }) {
  const [setup, setSetup] = useState(null);
  const [qr, setQr] = useState(null);
  const [code, setCode] = useState("");
  const [useRecovery, setUseRecovery] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [recoveryCodes, setRecoveryCodes] = useState(null);
  const [session, setSessionData] = useState(null);
  const [saved, setSaved] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (mode !== "enroll") return undefined;
    let cancelled = false;
    mfaService
      .enrollBegin(mfaToken)
      .then(async (data) => {
        if (cancelled) return;
        setSetup(data);
        try {
          setQr(await QRCode.toDataURL(data.otpauthUri, { margin: 1, width: 184 }));
        } catch {
          setQr(null);
        }
      })
      .catch((err) => !cancelled && setError(err.message || "Could not start setup. Please sign in again."));
    return () => {
      cancelled = true;
    };
  }, [mode, mfaToken]);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "enroll") {
        const out = await mfaService.enrollConfirm(mfaToken, code);
        setSessionData(out);
        setRecoveryCodes(out.recovery_codes || []);
      } else {
        const out = await mfaService.challenge(mfaToken, useRecovery ? { recoveryCode: code } : { code });
        onComplete(out);
      }
    } catch (err) {
      setError(err.message || "That code is not valid. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  async function copyCodes() {
    try {
      await navigator.clipboard.writeText(recoveryCodes.join("\n"));
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  const box = "w-full rounded-lg border border-slate-300 px-3 py-2.5 text-center text-lg tracking-widest";

  if (recoveryCodes) {
    return (
      <div className="space-y-4 text-sm text-slate-700">
        <h2 className="text-xl font-bold text-slate-900">Save your recovery codes</h2>
        <p>
          Each code works once if you lose your authenticator. They will not be shown again —
          store them somewhere safe.
        </p>
        <ul className="grid grid-cols-2 gap-2 rounded-lg bg-slate-50 p-3 font-mono text-sm">
          {recoveryCodes.map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
        <button type="button" onClick={copyCodes} className="inline-flex items-center gap-1 text-blue-600 hover:underline">
          {copied ? <Check className="h-4 w-4" aria-hidden="true" /> : <Copy className="h-4 w-4" aria-hidden="true" />}
          {copied ? "Copied" : "Copy codes"}
        </button>
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={saved} onChange={(e) => setSaved(e.target.checked)} />
          I have saved my recovery codes
        </label>
        <button
          type="button"
          disabled={!saved}
          onClick={() => onComplete(session)}
          className="w-full rounded-lg bg-blue-600 py-2.5 font-semibold text-white disabled:opacity-50"
        >
          Continue
        </button>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="space-y-4 text-sm text-slate-700">
      <div className="flex items-center gap-2">
        <ShieldCheck className="h-6 w-6 text-blue-600" aria-hidden="true" />
        <h2 className="text-xl font-bold text-slate-900">
          {mode === "enroll" ? "Set up two-step verification" : "Two-step verification"}
        </h2>
      </div>
      {mode === "enroll" ? (
        <>
          <p>
            Your role requires an authenticator app. Scan the code with Google Authenticator, Microsoft
            Authenticator or similar, then enter the 6-digit code it shows.
          </p>
          {qr && <img src={qr} alt="Authenticator QR code" className="mx-auto h-44 w-44" />}
          {setup && (
            <p className="break-all rounded bg-slate-50 p-2 text-center font-mono text-xs">
              Key: {setup.secret}
            </p>
          )}
        </>
      ) : (
        <p>
          Enter the {useRecovery ? "recovery code" : "6-digit code from your authenticator app"}.
        </p>
      )}
      <input
        autoFocus
        inputMode={useRecovery ? "text" : "numeric"}
        autoComplete="one-time-code"
        value={code}
        onChange={(e) => setCode(e.target.value.trim())}
        aria-label="Authentication code"
        placeholder={useRecovery ? "xxxxx-xxxxx" : "123456"}
        className={box}
      />
      {error && <p role="alert" className="text-red-600">{error}</p>}
      <button
        type="submit"
        disabled={busy || !code || (mode === "enroll" && !setup)}
        className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 py-2.5 font-semibold text-white disabled:opacity-50"
      >
        {busy && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />} Verify
      </button>
      <div className="flex justify-between text-xs">
        {mode === "challenge" ? (
          <button type="button" onClick={() => setUseRecovery((v) => !v)} className="text-blue-600 hover:underline">
            {useRecovery ? "Use authenticator code" : "Use a recovery code"}
          </button>
        ) : (
          <span />
        )}
        <button type="button" onClick={onCancel} className="text-slate-500 hover:underline">
          Back to sign in
        </button>
      </div>
    </form>
  );
}
