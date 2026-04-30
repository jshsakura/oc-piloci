const BASE = "";

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

  // Projects
  listProjects: () => request<import("./types").Project[]>("/api/projects"),
  createProject: (slug: string, name: string, description?: string) =>
    request("/api/projects", { method: "POST", body: JSON.stringify({ slug, name, description }) }),
  projectWorkspace: (slug: string) =>
    request<import("./types").ProjectWorkspace>(`/api/projects/slug/${slug}/workspace/preview`),
  deleteProject: (id: string) =>
    request(`/api/projects/${id}`, { method: "DELETE", body: JSON.stringify({ confirm: true }) }),

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
};
