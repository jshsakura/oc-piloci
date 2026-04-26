const BASE = "";

export type AuthProviderName = "kakao" | "naver" | "google" | "github";
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
  createToken: (name: string, scope: "project" | "user", project_id?: string) =>
    request("/api/tokens", { method: "POST", body: JSON.stringify({ name, scope, project_id }) }),
  revokeToken: (id: string) =>
    request(`/api/tokens/${id}`, { method: "DELETE" }),

  // 2FA / TOTP
  enable2fa: () =>
    request<{ qr: string; secret: string }>("/api/account/2fa/enable", { method: "POST" }),
  confirm2fa: (code: string) =>
    request<{ backup_codes: string[] }>("/api/account/2fa/confirm", { method: "POST", body: JSON.stringify({ code }) }),
  disable2fa: (password: string, code: string) =>
    request("/api/account/2fa/disable", { method: "POST", body: JSON.stringify({ password, code }) }),
};
