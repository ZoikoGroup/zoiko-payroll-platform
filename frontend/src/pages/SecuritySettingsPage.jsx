import { useCallback, useEffect, useState } from "react";
import QRCode from "qrcode";
import { Loader2, ShieldCheck } from "lucide-react";
import { mfaService } from "../service/mfaService";

// Security Settings (ZP-PRIV B08 / C.3): two-step verification for the
// signed-in user. Disabling (only where the role allows it) and replacing
// recovery codes need a fresh step-up; the API client opens the step-up
// dialog automatically when the server asks for one.
const card = "rounded-xl border border-border-light bg-surface p-5 shadow-sm space-y-3";
const btn = "inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium disabled:opacity-50";

function RecoveryCodes({ codes, onDone }) {
  const [saved, setSaved] = useState(false);
  return (
    <div className="space-y-3 text-sm">
      <p className="font-medium text-foreground">Save these recovery codes now — they will not be shown again.</p>
      <ul className="grid grid-cols-2 gap-2 rounded-lg bg-surface-muted p-3 font-mono">
        {codes.map((c) => <li key={c}>{c}</li>)}
      </ul>
      <label className="flex items-center gap-2 text-foreground">
        <input type="checkbox" checked={saved} onChange={(e) => setSaved(e.target.checked)} /> I have saved them
      </label>
      <button type="button" disabled={!saved} onClick={onDone} className={`${btn} bg-blue-600 text-white`}>Done</button>
    </div>
  );
}

export default function SecuritySettingsPage() {
  const [status, setStatus] = useState(null);
  const [setup, setSetup] = useState(null);
  const [qr, setQr] = useState(null);
  const [code, setCode] = useState("");
  const [codes, setCodes] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    try {
      setStatus(await mfaService.status());
    } catch (err) {
      setError(err.message || "Could not load your security settings.");
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load]);

  async function run(fn) {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (err) {
      setError(err.message || "That did not work.");
    } finally {
      setBusy(false);
    }
  }

  const begin = () => run(async () => {
    const data = await mfaService.setupBegin();
    setSetup(data);
    setQr(await QRCode.toDataURL(data.otpauthUri, { margin: 1, width: 184 }).catch(() => null));
  });
  const confirm = () => run(async () => {
    const out = await mfaService.setupConfirm(code);
    setSetup(null);
    setCode("");
    setCodes(out.recoveryCodes);
    await load();
  });
  const regenerate = () => run(async () => {
    const out = await mfaService.regenerateRecoveryCodes();
    setCodes(out.recoveryCodes);
    await load();
  });
  const disable = () => run(async () => {
    await mfaService.disable();
    await load();
  });

  return (
    <div className="mx-auto max-w-2xl space-y-5 p-4 sm:p-6">
      <div className="flex items-center gap-2">
        <ShieldCheck className="h-6 w-6 text-blue-600" aria-hidden="true" />
        <h1 className="text-2xl font-bold text-foreground">Security settings</h1>
      </div>
      {error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-800">{error}</p>}
      {!status ? (
        <p className="text-sm text-foreground-secondary">Loading…</p>
      ) : codes ? (
        <div className={card}><RecoveryCodes codes={codes} onDone={() => setCodes(null)} /></div>
      ) : (
        <div className={card}>
          <h2 className="text-lg font-semibold text-foreground">Two-step verification</h2>
          <p className="text-sm text-foreground-secondary">
            {status.enrolled
              ? `On since ${status.enrolledAt ? new Date(status.enrolledAt).toLocaleDateString() : "—"}. ${status.recoveryCodesRemaining} recovery codes left.`
              : "Off. Add an authenticator app to protect your account."}
            {status.required && " Your role requires it."}
          </p>
          {!status.enrolled && !setup && (
            <button type="button" className={`${btn} bg-blue-600 text-white`} disabled={busy} onClick={begin}>
              Set up authenticator
            </button>
          )}
          {setup && (
            <div className="space-y-3 text-sm">
              <p className="text-foreground">Scan the code, or type the key into your authenticator app, then enter the 6-digit code.</p>
              {qr && <img src={qr} alt="Authenticator QR code" className="h-44 w-44" />}
              <p className="break-all rounded bg-surface-muted p-2 font-mono text-xs">Key: {setup.secret}</p>
              <input className="w-40 rounded-lg border border-border-light bg-surface px-3 py-2 text-center tracking-widest"
                inputMode="numeric" autoComplete="one-time-code" value={code}
                onChange={(e) => setCode(e.target.value.trim())} aria-label="Authentication code" />
              <button type="button" className={`${btn} bg-blue-600 text-white`} disabled={busy || code.length !== 6} onClick={confirm}>
                {busy && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />} Confirm
              </button>
            </div>
          )}
          {status.enrolled && (
            <div className="flex flex-wrap gap-2">
              <button type="button" className={`${btn} border border-border-light text-foreground`} disabled={busy} onClick={regenerate}>
                New recovery codes
              </button>
              {!status.required && (
                <button type="button" className={`${btn} bg-red-600 text-white`} disabled={busy} onClick={disable}>
                  Turn off
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
