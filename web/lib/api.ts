const BASE = "";

function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const prefix = `${name}=`;
  const match = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(prefix));
  return match ? decodeURIComponent(match.slice(prefix.length)) : null;
}

function csrfHeaders(method?: string): Record<string, string> {
  const normalized = (method ?? "GET").toUpperCase();
  if (["GET", "HEAD", "OPTIONS", "TRACE"].includes(normalized)) return {};
  const token = readCookie("piloci_csrf");
  return token ? { "X-CSRF-Token": token } : {};
}

export type AuthProviderName = "kakao" | "naver" | "google" | "github";

export type ChatCitation = {
  ref: string;
  memory_id: string | null;
  content: string;
  score: number | null;
  tags: string[];
};

export type ChatStreamHandlers = {
  onCitations?: (citations: ChatCitation[]) => void;
  onToken?: (text: string) => void;
  onError?: (message: string) => void;
  onDone?: () => void;
  signal?: AbortSignal;
};

/**
 * Open a streaming chat against the user's selected project.
 *
 * Backend sends SSE with three event types: `citations`, `token`, `done`.
 * This helper parses them and dispatches to the provided callbacks.
 */
export async function chatStream(
  args: { query: string; project_slug: string; top_k?: number; tags?: string[] },
  handlers: ChatStreamHandlers = {}
): Promise<void> {
  const res = await fetch(`${BASE}/api/chat`, {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
      ...csrfHeaders("POST"),
    },
    body: JSON.stringify({ ...args, stream: true }),
    signal: handlers.signal,
  });

  if (!res.ok) {
    const errPayload = await res.json().catch(() => ({ error: "Chat request failed" }));
    handlers.onError?.(errPayload.error ?? "Chat request failed");
    return;
  }
  if (!res.body) {
    handlers.onError?.("Streaming not supported by this browser");
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    // Read until the stream ends. Each SSE message is delimited by \n\n.
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let sep: number;
      while ((sep = buffer.indexOf("\n\n")) !== -1) {
        const block = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        dispatchSseBlock(block, handlers);
      }
    }
    if (buffer.trim().length > 0) {
      dispatchSseBlock(buffer, handlers);
    }
  } finally {
    handlers.onDone?.();
  }
}

function dispatchSseBlock(block: string, handlers: ChatStreamHandlers): void {
  let event = "message";
  let data = "";
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) {
      event = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      data += line.slice(5).trimStart();
    }
  }
  if (!data) return;

  if (event === "citations") {
    try {
      const parsed = JSON.parse(data) as ChatCitation[];
      handlers.onCitations?.(parsed);
    } catch {
      // ignore malformed citations chunk
    }
  } else if (event === "token") {
    try {
      const parsed = JSON.parse(data) as { text?: string };
      if (parsed.text) handlers.onToken?.(parsed.text);
    } catch {
      // ignore malformed token chunk
    }
  } else if (event === "error") {
    try {
      const parsed = JSON.parse(data) as { error?: string };
      handlers.onError?.(parsed.error ?? "stream error");
    } catch {
      handlers.onError?.("stream error");
    }
  }
}
export type AuthProviderStatus = {
  name: AuthProviderName;
  configured: boolean;
  login_path: string;
};

async function request<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...options,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...csrfHeaders(options.method),
      ...options.headers,
    },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: "Request failed" }));
    throw Object.assign(new Error(err.error || "Request failed"), { status: res.status });
  }
  return res.json();
}

export const api = {
  // Auth
  listAuthProviders: () => request<{ providers: AuthProviderStatus[] }>("/api/auth/providers"),
  signup: (email: string, password: string, name: string) =>
    request("/auth/signup", { method: "POST", body: JSON.stringify({ email, password, name }) }),
  login: (email: string, password: string) =>
    request("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),
  logout: () => request("/auth/logout", { method: "POST" }),

  // Dashboard summary
  dashboardSummary: () =>
    request<import("./types").DashboardSummary>("/api/dashboard/summary"),

  // Projects
  listProjects: () => request<import("./types").Project[]>("/api/projects"),
  createProject: (slug: string, name: string, description?: string) =>
    request("/api/projects", { method: "POST", body: JSON.stringify({ slug, name, description }) }),
  updateProject: (id: string, patch: { name?: string; description?: string | null }) =>
    request<import("./types").Project>(`/api/projects/${id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  projectWorkspace: (slug: string) =>
    request<import("./types").ProjectWorkspace>(`/api/projects/slug/${slug}/workspace`),
  projectKnacks: (slug: string) =>
    request<import("./types").ProjectKnacksResponse>(`/api/projects/slug/${slug}/knacks`),
  projectSessions: (slug: string) =>
    request<import("./types").ProjectSessionsResponse>(`/api/projects/slug/${slug}/sessions`),
  rawSession: (ingest_id: string) =>
    request<import("./types").RawSessionDetail>(`/api/raw-sessions/${ingest_id}`),
  deleteProject: (id: string) =>
    request(`/api/projects/${id}`, { method: "DELETE", body: JSON.stringify({ confirm: true }) }),

  // Teams
  listTeams: () => request<import("./types").TeamSummary[]>("/api/teams"),
  createTeam: (name: string) =>
    request<import("./types").TeamSummary>("/api/teams", {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
  getTeam: (teamId: string) => request<import("./types").TeamDetail>(`/api/teams/${teamId}`),
  updateTeam: (
    teamId: string,
    patch: { name?: string; description?: string | null; avatar?: string | null; color?: string | null },
  ) =>
    request<import("./types").TeamDetail>(`/api/teams/${teamId}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  deleteTeam: (teamId: string) => request(`/api/teams/${teamId}`, { method: "DELETE" }),
  listPendingInvites: () => request<import("./types").TeamInvite[]>("/api/invites/pending"),
  respondInvite: (inviteId: string, action: "accept" | "reject") =>
    request<{ status: string; team_id: string }>(`/api/invites/${inviteId}/respond`, {
      method: "POST",
      body: JSON.stringify({ action }),
    }),
  createTeamInvite: (teamId: string, invitee_email: string) =>
    request<import("./types").TeamInvite>(`/api/teams/${teamId}/invites`, {
      method: "POST",
      body: JSON.stringify({ invitee_email }),
    }),
  listTeamInvites: (teamId: string) =>
    request<import("./types").TeamInvite[]>(`/api/teams/${teamId}/invites`),
  cancelTeamInvite: (teamId: string, inviteId: string) =>
    request(`/api/teams/${teamId}/invites/${inviteId}`, { method: "DELETE" }),
  removeTeamMember: (teamId: string, userId: string) =>
    request(`/api/teams/${teamId}/members/${userId}`, { method: "DELETE" }),
  createTeamDocument: (teamId: string, input: { path: string; content: string; parent_hash?: string | null }) =>
    request<import("./types").TeamDocumentSummary>(`/api/teams/${teamId}/documents`, {
      method: "POST",
      body: JSON.stringify(input),
    }),
  listTeamDocuments: (teamId: string) =>
    request<import("./types").TeamDocumentSummary[]>(`/api/teams/${teamId}/documents`),
  pullTeamDocuments: (teamId: string, manifest: Record<string, string>) =>
    request<import("./types").TeamDocumentPull>(`/api/teams/${teamId}/documents/pull`, {
      method: "POST",
      body: JSON.stringify({ manifest }),
    }),
  updateTeamDocument: (teamId: string, docId: string, input: { content: string; parent_hash?: string | null }) =>
    request<import("./types").TeamDocumentSummary>(`/api/teams/${teamId}/documents/${docId}`, {
      method: "PUT",
      body: JSON.stringify(input),
    }),
  deleteTeamDocument: (teamId: string, docId: string) =>
    request(`/api/teams/${teamId}/documents/${docId}`, { method: "DELETE" }),

  // Auth
  forgotPassword: (email: string) =>
    request("/auth/forgot-password", { method: "POST", body: JSON.stringify({ email }) }),
  resetPassword: (token: string, new_password: string) =>
    request("/auth/reset-password", { method: "POST", body: JSON.stringify({ token, new_password }) }),
  me: () => request<import("./types").User>('/api/me'),
  changePassword: (current_password: string, new_password: string) =>
    request('/api/account/password', { method: 'POST', body: JSON.stringify({ current_password, new_password }) }),

  // Audit
  listAudit: (limit = 50, offset = 0, action?: string) =>
    request<import("./types").AuditLog[]>(`/api/audit?limit=${limit}&offset=${offset}${action ? `&action=${action}` : ''}`),

  // LLM Providers (external OpenAI-compatible fallbacks)
  listLLMProviders: () =>
    request<import("./types").LLMProvider[]>("/api/llm-providers"),
  createLLMProvider: (input: {
    name: string;
    base_url: string;
    model: string;
    api_key: string;
    enabled?: boolean;
    priority?: number;
  }) =>
    request<import("./types").LLMProvider>("/api/llm-providers", {
      method: "POST",
      body: JSON.stringify(input),
    }),
  updateLLMProvider: (
    id: string,
    patch: Partial<{
      name: string;
      base_url: string;
      model: string;
      api_key: string;
      enabled: boolean;
      priority: number;
    }>,
  ) =>
    request<import("./types").LLMProvider>(`/api/llm-providers/${id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  deleteLLMProvider: (id: string) =>
    request(`/api/llm-providers/${id}`, { method: "DELETE" }),

  // Tokens
  listTokens: () => request<import("./types").ApiToken[]>("/api/tokens"),
  createToken: (name: string, scope: "project" | "user", project_id?: string, expire_days?: number | null) =>
    request("/api/tokens", { method: "POST", body: JSON.stringify({ name, scope, project_id, expire_days }) }),
  revokeToken: (id: string) =>
    request(`/api/tokens/${id}`, { method: "DELETE" }),

  // 2FA / TOTP
  enable2fa: () =>
    request<{ qr: string; secret: string }>("/api/account/2fa/enable", { method: "POST" }),
  confirm2fa: (code: string) =>
    request<{ backup_codes: string[] }>("/api/account/2fa/confirm", { method: "POST", body: JSON.stringify({ code }) }),
  disable2fa: (password: string, code: string) =>
    request("/api/account/2fa/disable", { method: "POST", body: JSON.stringify({ password, code }) }),

  // OAuth
  disconnectProvider: (provider: AuthProviderName) =>
    request<{ status: string }>(`/auth/${provider}/disconnect`, { method: "POST" }),

  // Chat (SSE streaming)
  chatStream: chatStream,

  // Data portability — per-user export/import
  exportUserData: async (): Promise<{ blob: Blob; filename: string }> => {
    const res = await fetch(`${BASE}/api/data/export`, {
      method: "GET",
      credentials: "include",
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: "Export failed" }));
      throw Object.assign(new Error(err.error || "Export failed"), { status: res.status });
    }
    const blob = await res.blob();
    const cd = res.headers.get("content-disposition") || "";
    const match = cd.match(/filename="?([^";]+)"?/);
    const filename = match?.[1] || "piloci-export.zip";
    return { blob, filename };
  },
  importUserData: async (
    file: File,
    opts: { reembed?: boolean } = {}
  ): Promise<{
    imported: boolean;
    projects_imported: number;
    projects_renamed: number;
    memories_imported: number;
    profiles_imported: number;
    re_embedded: boolean;
  }> => {
    const qs = opts.reembed ? "?reembed=true" : "";
    const res = await fetch(`${BASE}/api/data/import${qs}`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/zip" },
      body: file,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: "Import failed" }));
      throw Object.assign(new Error(err.error || "Import failed"), { status: res.status });
    }
    return res.json();
  },

  // Admin
  adminListUsers: (status?: string) =>
    request<import("./types").AdminUser[]>(`/api/admin/users${status ? `?status=${status}` : ""}`),
  adminApproveUser: (userId: string) =>
    request(`/api/admin/users/${userId}/approve`, { method: "POST" }),
  adminRejectUser: (userId: string, reason?: string) =>
    request(`/api/admin/users/${userId}/reject`, { method: "POST", body: JSON.stringify({ reason }) }),
  adminToggleAdmin: (userId: string) =>
    request(`/api/admin/users/${userId}/toggle-admin`, { method: "POST" }),
  adminToggleActive: (userId: string) =>
    request(`/api/admin/users/${userId}/toggle-active`, { method: "POST" }),
  adminDeleteUser: (userId: string) =>
    request(`/api/admin/users/${userId}`, { method: "DELETE" }),

  // Lazy distillation observability + control
  distillationStatus: () =>
    request<import("./types").DistillationStatus>("/api/distillation/status"),
  projectFreshness: (projectId: string) =>
    request<import("./types").ProjectFreshness>(
      `/api/projects/${projectId}/freshness`,
    ),
  runDistillationNow: () =>
    request<{ woken: boolean; note: string }>("/api/distillation/run-now", {
      method: "POST",
    }),
  budgetUsage: () =>
    request<import("./types").BudgetUsage>("/api/budget/usage"),
  getDistillationPreferences: () =>
    request<import("./types").DistillationPreferences>("/api/preferences"),
  updateDistillationPreferences: (
    body: Partial<import("./types").DistillationPreferences>,
  ) =>
    request<import("./types").DistillationPreferences>("/api/preferences", {
      method: "PATCH",
      body: JSON.stringify(body),
    }),

  // Weekly digest — private retrospective. Server filters by caller id; we
  // never pass a user_id from the client.
  getWeeklyDigest: (week?: string) =>
    request<import("./types").WeeklyDigestResponse>(
      `/api/digests/weekly${week ? `?week=${encodeURIComponent(week)}` : ""}`,
    ),
  regenerateWeeklyDigest: (week?: string) =>
    request<import("./types").WeeklyDigestResponse>(
      `/api/digests/weekly/regenerate${week ? `?week=${encodeURIComponent(week)}` : ""}`,
      { method: "POST" },
    ),
};
