// Messages for the fixed error codes the API's provider callbacks put in the
// URL (?error=&reason=&provider=). The URL never carries free text, so a
// crafted link can't put its own wording on the sign-in or registration page.

const GOOGLE_ERROR_MESSAGES = {
  google_cancelled: "Google sign-in was cancelled.",
  google_state_invalid: "Your Google sign-in expired or was started in another tab. Please try again.",
  google_sign_in_failed: "Google sign-in failed. Please try again.",
};

// Fixed reason codes from the API's Google callback — the URL never carries
// free text, so a crafted link can't put its own wording on this page.
const GOOGLE_FAILURE_REASONS = {
  email_unverified: "Your Google account's email isn't verified. Please sign in with email and password.",
  account_deactivated: "Your account has been deactivated.",
  organization_suspended: "Your organization has been suspended. Please contact support.",
  access_ended: "This temporary support access has ended.",
};

// Microsoft / Apple sign-in failures (?error=oauth_*&provider=&reason=).
// The provider is looked up in a fixed list, so the URL can't name its own.
const OAUTH_PROVIDER_NAMES = { microsoft: "Microsoft", apple: "Apple" };

function oauthErrorMessage(params) {
  const name = OAUTH_PROVIDER_NAMES[params.get("provider")];
  if (!name) return null;
  const reason = params.get("reason");
  switch (params.get("error")) {
    case "oauth_cancelled":
      return `${name} sign-in was cancelled.`;
    case "oauth_state_invalid":
      return `Your ${name} sign-in expired or was started in another tab. Please try again.`;
    case "oauth_failed":
      if (reason === "email_missing") {
        return `Your ${name} account didn't share an email address. Please sign in with your work email.`;
      }
      return GOOGLE_FAILURE_REASONS[reason] && reason !== "email_unverified"
        ? GOOGLE_FAILURE_REASONS[reason]
        : `${name} sign-in failed. Please try again.`;
    default:
      return null;
  }
}

export function readSignInError(search) {
  const params = new URLSearchParams(search);
  const fallback = GOOGLE_ERROR_MESSAGES[params.get("error")];
  if (fallback) return GOOGLE_FAILURE_REASONS[params.get("reason")] || fallback;
  return oauthErrorMessage(params);
}
