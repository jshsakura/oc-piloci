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

export interface TeamSummary {
  id: string;
  name: string;
  owner_id: string;
  created_at: string;
}

export interface TeamMember {
  user_id: string;
  email: string;
  role: "owner" | "member" | string;
  joined_at: string;
}

export interface TeamDetail extends TeamSummary {
  description?: string | null;
  avatar?: string | null;
  color?: string | null;
  members: TeamMember[];
}

export interface TeamInvite {
  id: string;
  team_id?: string;
  team_name?: string;
  invitee_email?: string;
  status?: string;
  token?: string;
  expires_at: string;
  created_at?: string;
}

export interface TeamDocumentSummary {
  id: string;
  team_id?: string;
  path: string;
  content_hash: string;
  version: number;
  author_email?: string;
  updated_at?: string;
  created_at?: string;
}

export interface TeamDocumentPull {
  added: Array<TeamDocumentSummary & { content: string }>;
  modified: Array<TeamDocumentSummary & { content: string }>;
  deleted: Array<{ path: string }>;
  unchanged: Array<{ path: string; content_hash: string }>;
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
  /** Cross-platform alternative: ``pip install -U oc-piloci && python -m piloci install <install_url>`` (Windows). */
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

export interface ProjectKnack {
  instinct_id: string;
  trigger: string;
  action: string;
  domain: string;
  evidence_note: string;
  confidence: number;
  instinct_count: number;
  created_at: number;
}

export interface ProjectKnacksResponse {
  project: { id: string; slug: string; name: string };
  knacks: ProjectKnack[];
}

export interface ProjectSessionMeta {
  ingest_id: string;
  session_id?: string | null;
  client: string;
  size_bytes: number;
  created_at: string;
  processed_at?: string | null;
  memories_extracted: number;
  error?: string | null;
}

export interface ProjectSessionsResponse {
  project: { id: string; slug: string; name: string };
  sessions: ProjectSessionMeta[];
}

export interface RawSessionDetail {
  ingest_id: string;
  session_id?: string | null;
  client: string;
  transcript: string;
  created_at: string;
  processed_at?: string | null;
  memories_extracted: number;
  error?: string | null;
}

export interface DashboardSummary {
  recent_memories: {
    memory_id: string;
    content: string;
    tags: string[];
    project_slug: string;
    project_name: string;
    created_at: number;
    updated_at: number;
  }[];
  top_instincts: {
    instinct_id: string;
    trigger: string;
    action: string;
    domain: string;
    confidence: number;
    instinct_count: number;
    project_slug: string;
    project_name: string;
  }[];
  recent_sessions: {
    ingest_id: string;
    project_slug?: string | null;
    project_name?: string | null;
    created_at: string;
    processed_at?: string | null;
    memories_extracted: number;
    client: string;
  }[];
  activity: { date: string; count: number }[];
  top_tags: { tag: string; count: number }[];
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

// ----- Lazy distillation pipeline -----

export interface DistillationStatus {
  counts: {
    pending: number;
    distilled: number;
    filtered: number;
    failed: number;
    archived: number;
  };
  lag: {
    oldest_pending_at: string | null;
    seconds_behind: number | null;
  };
  last_distilled_at: string | null;
  processing_path_30d: Record<string, number>;
  thresholds: {
    max_pending_backlog: number;
    overflow_threshold: number;
    temp_ceiling_c: number;
    load_ceiling_1m: number;
  };
  current: {
    cpu_temp_c: number | null;
    load_avg_1m: number | null;
  };
  schedule: {
    idle_window: string | null;
    next_idle_at: string | null;
  };
  enabled: boolean;
}

export interface ProjectFreshness {
  project_id: string;
  pending_count: number;
  last_distilled_at: string | null;
  oldest_pending_age_seconds: number | null;
}

export interface DistillationPreferences {
  distillation_idle_window: string | null;
  distillation_temp_ceiling_c: number | null;
  distillation_load_ceiling_1m: number | null;
  distillation_overflow_threshold: number | null;
  external_budget_monthly_usd: number | null;
}

export interface BudgetUsage {
  month_start_utc: string;
  spent_usd: number;
  remaining_usd: number | null;
  cap_usd: number | null;
  by_provider: Array<{
    provider: string;
    calls: number;
    tokens_in: number;
    tokens_out: number;
    cost_usd: number;
  }>;
}

// Private weekly retrospective. Server scopes the row to the caller — the
// client never sends a user_id and never sees another user's digest.
export interface WeeklyDigestStats {
  sessions: number;
  feedback_count: number;
  reaction_count: number;
  top_projects: Array<{ name: string; sessions: number }>;
}

export interface WeeklyDigest {
  digest_id: string;
  week_start: string; // YYYY-MM-DD (Monday)
  summary: string;
  stats: WeeklyDigestStats;
  generated_at: string;
}

export interface WeeklyDigestResponse {
  digest: WeeklyDigest | null;
  note?: string;
}
