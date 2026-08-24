import { api, getAccessToken, API_BASE_URL } from "./api";

// ── Sessions ───────────────────────────────────────────────────────────
export const getAssistStatus = async () => {
  try {
    return await api.get("/api/assist/status");
  } catch {
    return null;
  }
};

export const getAssistCapabilities = async () => {
  const data = await api.get("/api/assist/capabilities");
  return data?.capabilities || [];
};

export const getAssistSuggestions = async () => {
  const data = await api.get("/api/assist/suggestions");
  return data?.suggestions || [];
};

export const getCurrentAssistNotice = async () => {
  try {
    return await api.get("/api/assist/notices/current");
  } catch {
    return null;
  }
};

export const acknowledgeAssistNotice = async (noticeVersion) => {
  return api.post(`/api/assist/notices/${noticeVersion}/acknowledge`);
};

export const listAssistSessions = async ({ skip = 0, limit = 20, status } = {}) => {
  return api.get("/api/assist/sessions", { params: { skip, limit, status } });
};

export const createAssistSession = async ({ context, title } = {}) => {
  const payload = {
    channel: "WEB",
    locale: "en",
    time_zone: "UTC",
    title,
  };
  if (context) payload.context = context;
  return api.post("/api/assist/sessions", payload);
};

export const getAssistSession = async (sessionId) => {
  return api.get(`/api/assist/sessions/${sessionId}`);
};

export const updateAssistSession = async (sessionId, { title, context, caseLink } = {}) => {
  const payload = {};
  if (title !== undefined) payload.title = title;
  if (context !== undefined) payload.context = context;
  if (caseLink !== undefined) payload.case_link = caseLink;
  return api.patch(`/api/assist/sessions/${sessionId}`, payload);
};

export const archiveAssistSession = async (sessionId) => {
  return api.post(`/api/assist/sessions/${sessionId}/archive`);
};

// ── Messages / responses ───────────────────────────────────────────────
let idemCounter = 0;
function nextIdempotencyKey() {
  idemCounter += 1;
  return `ui-${Date.now()}-${idemCounter}`;
}

export const submitAssistMessage = async (sessionId, text, { context, idempotencyKey } = {}) => {
  const payload = {
    content: { type: "TEXT", text },
  };
  if (context) payload.context = context;
  return api.post(`/api/assist/sessions/${sessionId}/messages`, payload, {
    headers: { "Idempotency-Key": idempotencyKey || nextIdempotencyKey() },
  });
};

export const getAssistResponse = async (responseId) => {
  return api.get(`/api/assist/responses/${responseId}`);
};

export const streamAssistResponseEvents = async (responseId, { onEvent, signal } = {}) => {
  const res = await fetch(`${API_BASE_URL}/api/assist/responses/${responseId}/events/stream`, {
    headers: { Authorization: `Bearer ${getAccessToken()}` },
    signal,
  });
  if (!res.ok || !res.body) {
    throw new Error(`stream failed: ${res.status}`);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop();
    for (const part of parts) {
      const dataLine = part.split("\n").find((l) => l.startsWith("data:"));
      if (!dataLine) continue;
      const payload = dataLine.slice(5).trim();
      if (!payload) continue;
      try {
        onEvent?.(JSON.parse(payload));
      } catch {
        /* skip malformed event */
      }
    }
  }
};

export const getAssistResponseSources = async (responseId) => {
  const data = await api.get(`/api/assist/responses/${responseId}/sources`);
  return data?.sources || [];
};

export const listAssistMessages = async (sessionId) => {
  const data = await api.get(`/api/assist/sessions/${sessionId}/messages`, { params: { skip: 0, limit: 200 } });
  return data?.messages || [];
};

export const submitAssistFeedback = async (responseId, { rating, comment, reason_code } = {}) => {
  return api.post(`/api/assist/responses/${responseId}/feedback`, { rating, comment, reason_code });
};

// ── Controlled actions (A3) ────────────────────────────────────────────
export const listAssistAllowedActions = async () => {
  const data = await api.get("/api/assist/actions/allowed");
  return data?.actions || [];
};

export const createAssistActionPreview = async ({ action_id, target, arguments: args, source_response_id }) => {
  return api.post("/api/assist/action-previews", {
    action_id,
    target,
    arguments: args || {},
    source_response_id: source_response_id ?? null,
  });
};

export const confirmAssistAction = async (previewId) => {
  return api.post(`/api/assist/action-previews/${previewId}/confirm`, {});
};

export const cancelAssistAction = async (previewId) => {
  return api.post(`/api/assist/action-previews/${previewId}/cancel`);
};

export const stopAssistResponse = async (responseId) => {
  return api.post(`/api/assist/responses/${responseId}/stop`);
};

// ── Drafts / handoffs ──────────────────────────────────────────────────
export const createAssistHandoffPreview = async ({
  destination, reason_code, summary, included_evidence_ids, excluded_data_classes,
  source_response_id, source_session_id,
}) => {
  return api.post("/api/assist/handoff-previews", {
    destination,
    reason_code,
    summary,
    included_evidence_ids: included_evidence_ids || [],
    excluded_data_classes: excluded_data_classes || [],
    source_response_id: source_response_id ?? null,
    source_session_id: source_session_id ?? null,
  });
};

export const getAssistHandoffPreview = async (previewId) => {
  return api.get(`/api/assist/handoff-previews/${previewId}`);
};

export const confirmAssistHandoff = async (previewId) => {
  return api.post(`/api/assist/handoff-previews/${previewId}/confirm`);
};

export const cancelAssistHandoff = async (previewId) => {
  return api.post(`/api/assist/handoff-previews/${previewId}/cancel`);
};

export const getAssistHandoff = async (handoffId) => {
  return api.get(`/api/assist/handoffs/${handoffId}`);
};
export const createAssistDraft = async ({ draft_type, content, session_id }) => {
  return api.post("/api/assist/drafts", { draft_type, content, session_id });
};

export const listAssistDrafts = async ({ skip = 0, limit = 100, state } = {}) => {
  const data = await api.get("/api/assist/drafts", { params: { skip, limit, state } });
  return data?.drafts || [];
};

export const updateAssistDraft = async (draftId, { content, state } = {}) => {
  return api.patch(`/api/assist/drafts/${draftId}`, { content, state });
};

export const deleteAssistDraft = async (draftId) => {
  return api.delete(`/api/assist/drafts/${draftId}`);
};

// ── Admin / audit (payroll operator) ───────────────────────────────────
export const listAssistAuditEvents = async ({ skip = 0, limit = 50, event_type, session_id } = {}) => {
  const data = await api.get("/api/assist/admin/audit-events", {
    params: { skip, limit, event_type, session_id },
  });
  return data;
};

export const listAdminAssistSessions = async ({ skip = 0, limit = 50, status } = {}) => {
  const data = await api.get("/api/assist/admin/sessions", {
    params: { skip, limit, status },
  });
  return data;
};

export const getAssistRetentionSummary = async () => {
  return api.get("/api/assist/admin/retention");
};

export const runAssistRetentionCleanup = async () => {
  return api.post("/api/assist/admin/retention/run");
};

export const listAssistModelExecutions = async ({ skip = 0, limit = 50, response_id } = {}) => {
  const data = await api.get("/api/assist/admin/model-executions", {
    params: { skip, limit, response_id },
  });
  return data;
};

// ── Knowledge base management (admin) ─────────────────────────────────
export const listAssistKbItems = async ({ state, content_type } = {}) => {
  const data = await api.get("/api/assist/knowledge/items", {
    params: { state, content_type },
  });
  return Array.isArray(data) ? data : [];
};

export const createAssistKbItem = async (payload) => {
  return api.post("/api/assist/knowledge/items", payload);
};

export const updateAssistKbItem = async (itemId, payload) => {
  return api.patch(`/api/assist/knowledge/items/${itemId}`, payload);
};

export const publishAssistKbItem = async (itemId, { reviewer_notes } = {}) => {
  return api.post(`/api/assist/knowledge/items/${itemId}/publish`, { reviewer_notes });
};

export const listAssistKbSources = async () => {
  const data = await api.get("/api/assist/knowledge/sources");
  return data || [];
};

// ── Public (unauthenticated / website) mode ────────────────────────────
// Never attaches a bearer token, even if one happens to be in localStorage
// (e.g. an admin has the authenticated app open in another tab on the same
// origin) — anonymous visitors must never be treated as a logged-in user.
export const createPublicAssistSession = async ({ locale = "en" } = {}) => {
  return api.post("/api/assist/public/sessions", { locale }, { auth: false });
};

export const submitPublicAssistMessage = async (sessionId, text) => {
  return api.post(`/api/assist/public/sessions/${sessionId}/messages`, { text }, { auth: false });
};

export const listPublicAssistMessages = async (sessionId) => {
  return api.get(`/api/assist/public/sessions/${sessionId}/messages`, { auth: false });
};
