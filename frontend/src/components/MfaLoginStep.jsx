import { useEffect, useState } from "react";
import QRCode from "qrcode";
import { Check, Copy, KeyRound, ShieldCheck } from "lucide-react";
import { mfaService } from "../service/mfaService";
import { AuthAlert, AuthPrimaryButton } from "./auth/authUi";

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

  const header = (Icon, title, subtitle) => (
    <div className="mb-5">
      <span className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-blue-50 text-blue-700">
        <Icon size={24} aria-hidden="true" />
      </span>
      <h2 className="text-[28px] font-extrabold leading-tight tracking-[-0.02em] text-slate-900">{title}</h2>
      {subtitle && <p className="mt-2 text-[15px] leading-relaxed text-slate-600">{subtitle}</p>}
    </div>
  );

  if (recoveryCodes) {
    return (
      <div className="text-[14px] text-slate-700">
        {header(KeyRound, "Save your recovery codes",
          "Each code works once if you lose your authenticator. They will not be shown again — store them somewhere safe.")}
        <ul className="grid grid-cols-2 gap-2 rounded-lg border border-slate-200 bg-slate-50 p-4 font-mono text-[14px] text-slate-900">
          {recoveryCodes.map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
        <button type="button" onClick={copyCodes}
          className="mt-3 inline-flex items-center gap-1.5 font-medium text-blue-700 hover:text-blue-800">
          {copied ? <Check className="h-4 w-4" aria-hidden="true" /> : <Copy className="h-4 w-4" aria-hidden="true" />}
          {copied ? "Copied" : "Copy codes"}
        </button>
        <label className="my-5 flex cursor-pointer items-center gap-2">
          <input type="checkbox" checked={saved} onChange={(e) => setSaved(e.target.checked)}
            className="h-4 w-4 rounded border-slate-300 accent-blue-600" />
          I have saved my recovery codes
        </label>
        <AuthPrimaryButton type="button" disabled={!saved} onClick={() => onComplete(session)}>
          Continue
        </AuthPrimaryButton>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="text-[14px] text-slate-700">
      {mode === "enroll"
        ? header(ShieldCheck, "Set up two-step verification",
          "Your role requires an authenticator app. Scan the code with Google Authenticator, Microsoft Authenticator or similar, then enter the 6-digit code it shows.")
        : header(ShieldCheck, "Two-step verification",
          `Enter the ${useRecovery ? "recovery code" : "6-digit code from your authenticator app"}.`)}

      {mode === "enroll" && (
        <div className="mb-5 rounded-xl border border-slate-200 bg-slate-50 p-4">
          {qr && <img src={qr} alt="Authenticator QR code" className="mx-auto h-44 w-44 rounded-lg bg-white p-2" />}
          {setup && (
            <p className="mt-3 break-all text-center font-mono text-xs text-slate-700">
              Key: {setup.secret}
            </p>
          )}
        </div>
      )}

      {error && <AuthAlert>{error}</AuthAlert>}

      <input
        autoFocus
        inputMode={useRecovery ? "text" : "numeric"}
        autoComplete="one-time-code"
        value={code}
        onChange={(e) => setCode(e.target.value.trim())}
        aria-label="Authentication code"
        placeholder={useRecovery ? "xxxxx-xxxxx" : "123456"}
        className="mb-5 w-full rounded-lg border border-slate-200 bg-white px-4 py-3 text-center text-[22px] font-semibold tracking-[0.35em] text-slate-900 placeholder:tracking-[0.2em] placeholder:text-slate-300 outline-none focus:border-blue-600 focus:ring-2 focus:ring-blue-600/15"
      />
      <AuthPrimaryButton type="submit" busy={busy} disabled={!code || (mode === "enroll" && !setup)}>
        Verify
      </AuthPrimaryButton>
      <div className="mt-5 flex justify-between text-[14px]">
        {mode === "challenge" ? (
          <button type="button" onClick={() => setUseRecovery((v) => !v)} className="font-medium text-blue-700 hover:text-blue-800">
            {useRecovery ? "Use authenticator code" : "Use a recovery code"}
          </button>
        ) : (
          <span />
        )}
        <button type="button" onClick={onCancel} className="font-medium text-slate-600 hover:text-slate-900">
          Back to sign in
        </button>
      </div>
    </form>
  );
}
