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
  description?: string;
  memory_count: number;
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
  mcp_config_sse: McpServerConfig;
  hook_config: {
    hooks: {
      Stop: Array<{
        matcher: string;
        hooks: Array<{ type: string; command: string }>;
      }>;
    };
  };
}

export interface ApiToken {
  token_id: string;
  name: string;
  scope: "project" | "user";
  project_id?: string;
  created_at: string;
  last_used_at?: string;
  expires_at?: string | null;
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
