import { useEffect, useRef } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import { API_BASE, setSession, getStoredUser } from "../api/client";
import { api } from "../service/api";
import { useAuth } from "../context/AuthContext";
import { ROLE_DEFAULT_REDIRECT } from "../config/roles";

/**
 * /auth/google/callback is reached twice in one Google sign-in:
 *
 *  1. From Google (GOOGLE_REDIRECT_URI) with ?code=&state= — forwarded as a
 *     full-page navigation to the API's /api/auth/google/callback, which owns
 *     the state cookie and exchanges the code. The API then either signs the
 *     user in (back here, step 2), sends a registered user with MFA to the
 *     login page's second-factor step, or sends a new Google identity to
 *     /register?pending=<token>.
 *  2. From the API with #access_token=&refresh_token= (URL fragment: never
 *     sent to a server). Stores the session, loads the profile, opens the
 *     role's dashboard and clears the tokens from the address bar.
 */
export default function GoogleCallbackPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { login } = useAuth();
  // The tokens are read from the URL once and kept here: the URL is cleared
  // straight after, and React StrictMode (development) runs this effect a
  // second time — re-reading the then-empty URL used to send a successful
  // sign-in to /login?error=google_sign_in_failed.
  const tokensRef = useRef(null);
  const forwardedRef = useRef(false);

  useEffect(() => {
    let cancelled = false;

    const run = async () => {
      // Step 1: Google's redirect — hand the code to the API.
      // Once only: Google's code is single-use, a second exchange fails.
      if (searchParams.get("code") || searchParams.get("error")) {
        if (!forwardedRef.current) {
          forwardedRef.current = true;
          window.location.replace(`${API_BASE}/api/auth/google/callback${window.location.search}`);
        }
        return;
      }

      // Step 2: the API's redirect with the session (fragment; the query
      // string is accepted too for links issued before this change).
      if (!tokensRef.current) {
        const fragment = new URLSearchParams(window.location.hash.replace(/^#/, ""));
        tokensRef.current = {
          accessToken: fragment.get("access_token") || searchParams.get("access_token"),
          refreshToken: fragment.get("refresh_token") || searchParams.get("refresh_token"),
        };
        // Drop the tokens from the URL / history before doing anything else.
        window.history.replaceState(null, "", window.location.pathname);
      }
      const { accessToken, refreshToken } = tokensRef.current;

      if (!accessToken) {
        navigate("/login?error=google_sign_in_failed", { replace: true });
        return;
      }

      setSession({ accessToken, refreshToken });

      try {
        const user = await api.get("/api/auth/me");
        if (cancelled) return;
        // UserResponse shape (matches LoginResponse.user); login() stores it
        // in context + localStorage.
        if (user) await login(user);
      } catch {
        // The session is valid; the dashboard reloads the profile itself.
      }
      if (cancelled) return;

      const role = getStoredUser()?.role;
      navigate(ROLE_DEFAULT_REDIRECT[role] || "/dashboard", { replace: true });
    };

    run();
    return () => {
      cancelled = true;
    };
  }, [searchParams, navigate, login]);

  return (
    <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center" }}>
      <p style={{ color: "#64748B", fontSize: 15 }}>Signing you in with Google…</p>
    </div>
  );
}
