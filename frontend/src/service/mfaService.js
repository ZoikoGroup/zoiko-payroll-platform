// MFA + step-up API (ZP-PRIV B08). Login-time steps use the single-use
// mfaToken the login response returns; the rest use the session.
import { api, setSession, getStoredUser } from "./api";

export const mfaService = {
  challenge: (mfaToken, { code, recoveryCode }) =>
    api.post("/api/auth/mfa/challenge", { mfaToken, code, recoveryCode }, { auth: false }),
  enrollBegin: (mfaToken) => api.post("/api/auth/mfa/enroll/begin", { mfaToken }, { auth: false }),
  enrollConfirm: (mfaToken, code) => api.post("/api/auth/mfa/enroll/confirm", { mfaToken, code }, { auth: false }),

  status: () => api.get("/api/auth/mfa/status"),
  setupBegin: () => api.post("/api/auth/mfa/setup/begin", {}),
  setupConfirm: async (code) => {
    const out = await api.post("/api/auth/mfa/setup/confirm", { code });
    if (out?.accessToken) setSession({ accessToken: out.accessToken, user: getStoredUser() });
    return out;
  },
  stepUp: async ({ code, recoveryCode }) => {
    const out = await api.post("/api/auth/mfa/step-up", { code, recoveryCode }, { stepUpRetry: false });
    if (out?.accessToken) setSession({ accessToken: out.accessToken, user: getStoredUser() });
    return out;
  },
  regenerateRecoveryCodes: () => api.post("/api/auth/mfa/recovery-codes", {}),
  disable: () => api.post("/api/auth/mfa/disable", {}),
};
