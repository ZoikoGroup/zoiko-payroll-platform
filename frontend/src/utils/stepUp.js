// Step-up authentication bridge (ZP-PRIV B08).
//
// The backend answers 403 STEP_UP_REQUIRED when a sensitive action (approving
// support access, exports, credential resets, field reveals ...) needs a
// second factor from the last 5 minutes. Both API clients call
// requestStepUp(); the StepUpAuthModal (mounted once in main.jsx) registers
// itself as the handler, asks for a code, swaps in the fresh access token and
// resolves - the client then retries the original request once.

let handler = null;
let pending = null;

export function registerStepUpHandler(fn) {
  handler = fn;
  return () => {
    if (handler === fn) handler = null;
  };
}

// Resolves true when the user completed step-up, false if they cancelled.
export function requestStepUp(reason) {
  if (!handler) return Promise.resolve(false);
  if (!pending) {
    pending = Promise.resolve(handler(reason)).finally(() => {
      pending = null;
    });
  }
  return pending;
}

export const STEP_UP_REQUIRED = "STEP_UP_REQUIRED";
