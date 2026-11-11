import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { getAccessToken, getStoredUser, setStoredUser, clearSession } from "../api/client";
import { AUTH_INVALID_EVENT, resetSessionInvalidNotice } from "../service/api";

// Pages that never need a session — a dead session is not redirected from these.
const PUBLIC_PATHS = ["/login", "/register", "/trial-register", "/forgot-password", "/reset-password", "/accept-invite"];
import { ROLES, VALID_ROLES } from "../config/roles";

export const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => getStoredUser());
  const navigate = useNavigate();
  const location = useLocation();

  // service/api.js fires AUTH_INVALID_EVENT when a token refresh is rejected
  // (the session expired or was revoked). Without this listener the tokens
  // were cleared but the page stayed put, every request failing with
  // "Your session has expired" until the user found the login page alone.
  useEffect(() => {
    const onSessionInvalid = () => {
      clearSession();
      setUser(null);
      if (PUBLIC_PATHS.some((p) => location.pathname.startsWith(p))) return;
      navigate("/login", { replace: true, state: { from: location, sessionExpired: true } });
    };
    window.addEventListener(AUTH_INVALID_EVENT, onSessionInvalid);
    return () => window.removeEventListener(AUTH_INVALID_EVENT, onSessionInvalid);
  }, [location, navigate]);

  useEffect(() => {
    if (!getAccessToken()) {
      setUser(null);
      return;
    }
    setUser(getStoredUser());
  }, []);

  const login = useCallback(async (loggedInUser) => {
    resetSessionInvalidNotice();
    setStoredUser(loggedInUser);
    setUser(loggedInUser);
    return loggedInUser;
  }, []);

  const logout = useCallback(async () => {
    clearSession();
    setUser(null);
  }, []);

  const role = user?.role && VALID_ROLES.includes(user.role) ? user.role : null;

  const hasRole = (roles) => {
    if (!role) return false;
    if (!Array.isArray(roles)) return role === roles;
    return roles.includes(role);
  };

  const value = {
    user,
    role,
    isAuthenticated: Boolean(getAccessToken()),
    login,
    logout,
    hasRole,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
