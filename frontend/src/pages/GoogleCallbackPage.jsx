import { useEffect } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import { setSession, getStoredUser } from "../api/client";
import { api } from "../service/api";
import { useAuth } from "../context/AuthContext";
import { ROLE_DEFAULT_REDIRECT } from "../config/roles";

/**
 * Reached via backend redirect after Google OAuth consent:
 *   /auth/google/callback?access_token=...&refresh_token=...
 *
 * Stores the session in localStorage, loads the user profile, then sends
 * the user to their role's default dashboard. Clears the token query params
 * from the URL so they aren't left in the address bar / history.
 */
export default function GoogleCallbackPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { login } = useAuth();

  useEffect(() => {
    let cancelled = false;

    const run = async () => {
      const accessToken = searchParams.get("access_token");
      const refreshToken = searchParams.get("refresh_token");

      if (!accessToken) {
        navigate("/login", { replace: true });
        return;
      }

      setSession({ accessToken, refreshToken });

      try {
        const user = await api.get("/auth/me");
        if (user) {
          // api.get("/auth/me") returns the UserResponse shape (matches
          // LoginResponse.user). login() stores it in context + localStorage.
          if (cancelled) return;
          login(user);
        }
      } catch {
        // If /auth/me fails we still have a valid session; send them to the
        // dashboard and let the app recover.
      }

      // Drop the token params from the URL without a full reload.
      window.history.replaceState(null, "", window.location.pathname);

      const role = getStoredUser()?.role;
      const target = ROLE_DEFAULT_REDIRECT[role] || "/dashboard";
      navigate(target, { replace: true });
    };

    run();
    return () => {
      cancelled = true;
    };
  }, [searchParams, navigate, login]);

  return null;
}
