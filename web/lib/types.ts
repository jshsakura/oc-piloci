export interface User {
  user_id: string;
  email: string;
  is_admin?: boolean;
  approval_status?: "pending" | "approved" | "rejected";
  oauth_provider?: string;
}

export interface Project {
  id: string;
  slug: string;
  name: string;
  description?: string | null;
  memory_count: number;
  instinct_count?: number;
  session_count?: number;
  last_active_at?: string | null;
  last_analyzed_at?: string | null;
  created_at: string;
}

export interface Memory {
  id: string;
  content: string;
  tags: string[];
  metadata: Record<string, unknown>;
  score?: number;
  created_at: number;
  updated_at: number;
}

interface McpServerConfig {
  mcpServers: {
    piloci: {
      type: string;
      url: string;
      headers: { Authorization: string };
    };
  };
}

export interface TokenSetup {
  mcp_config: McpServerConfig;
  hook_config: {
    hooks: {
      SessionStart: Array<{
        matcher: string;
        hooks: Array<{ type: string; command: string }>;
      }>;
    };
  };
  hook_config_json?: { token: string; ingest_url: string; analyze_url?: string };
  hook_script?: string;
  claude_md?: string;
  /** One-time install code that exchanges for the bash installer (single-use, ~10 min TTL). */
  install_code?: string;
  /** Full URL clients pipe to bash. Token is never embedded — only the short code is. */
  install_url?: string;
  /** Ready-to-paste one-liner: ``curl -sSL <install_url> | bash`` (Linux/macOS). */
  install_command?: string;
  /** Cross-platform alternative: ``uvx oc-piloci install <install_url>`` (Windows). */
  install_command_windows?: string;
}

export interface ApiToken {
  token_id: string;
  name: string;
  scope: "project" | "user";
  project_id?: string;
  created_at: string;
  last_used_at?: string;
  expires_at?: string | null;
  installed_at?: string | null;
  client_kinds?: string[];
  hostname?: string | null;
}

export interface LLMProvider {
  id: string;
  name: string;
  base_url: string;
  model: string;
  enabled: boolean;
  priority: number;
  api_key_masked?: string | null;
  created_at: string;
  updated_at: string;
}

export interface CreatedToken {
  token: string;
  token_id: string;
  name: string;
  setup?: TokenSetup;
}

export interface AuditLog {
  id: number;
  action: string;
  ip_address?: string;
  user_agent?: string;
  meta_data?: string;
  created_at: string;
}

export interface ApiError {
  error: string;
}

export interface AdminUser {
  id: string;
  email: string;
  name?: string;
  is_admin: boolean;
  is_active: boolean;
  approval_status: "pending" | "approved" | "rejected";
  reviewed_by?: string;
  reviewed_at?: string;
  rejection_reason?: string;
  created_at: string;
  last_login_at?: string;
  oauth_provider?: string;
  totp_enabled?: boolean;
}

export interface VaultNote {
  memory_id: string;
  title: string;
  path: string;
  created_at: string;
  updated_at: string;
  tags: string[];
  links: string[];
  excerpt: string;
  markdown?: string;
}

export interface GraphNode {
  id: string;
  label: string;
  kind: "project" | "note" | "tag" | "topic";
  path?: string;
  slug?: string;
}

export interface GraphEdge {
  source: string;
  target: string;
  kind: "contains" | "tagged" | "links";
}

export interface ProjectWorkspace {
  project: Project;
  workspace: {
    root: string;
    generated_at: string;
    stats: {
      notes: number;
      nodes: number;
      edges: number;
      tags: number;
    };
    notes: VaultNote[];
    graph: {
      nodes: GraphNode[];
      edges: GraphEdge[];
    };
    preview?: boolean;
    note_limit?: number;
  };
}
