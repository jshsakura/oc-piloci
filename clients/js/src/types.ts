/**
 * TypeScript interfaces mirroring the piLoci backend Pydantic models.
 * Field names use camelCase in the TS API; the client converts to snake_case
 * on the wire. The `raw` escape hatch carries the untyped server response.
 */

// ---------------------------------------------------------------------------
// Memory tool  (mirrors MemoryInput in memory_tools.py)
// ---------------------------------------------------------------------------

export type MemoryAction = "save" | "forget";

export interface MemorySaveInput {
  /** Memory content to save. Max 200 000 chars. */
  content: string;
  /** 1–3 optional tags to attach. */
  tags?: string[];
}

export interface MemoryForgetInput {
  /** The memory ID to remove. Obtain from recall first. */
  memoryId: string;
}

export interface MemorySaveResult {
  success: boolean;
  action: "save";
  memoryId: string;
  projectId: string;
  raw: unknown;
}

export interface MemoryForgetResult {
  success: boolean;
  action: "forget";
  memoryId: string;
  raw: unknown;
}

// ---------------------------------------------------------------------------
// Recall tool  (mirrors RecallInput in memory_tools.py)
// ---------------------------------------------------------------------------

export interface RecallInput {
  /** Search query. Required unless fetchIds is provided. */
  query?: string;
  /** Fetch full content for these memory IDs (skips search). */
  fetchIds?: string[];
  /** Save results as a markdown file on the server. Returns file path. */
  toFile?: boolean;
  /** Include user profile summary. Default true. */
  includeProfile?: boolean;
  /** Filter by tags. */
  tags?: string[];
  /** Max results in preview mode (1–50). Default 5. */
  limit?: number;
}

export interface MemoryPreview {
  id: string;
  score: number;
  tags: string[];
  excerpt: string;
  length: number;
  createdAt?: string;
}

export interface RecallPreviewResult {
  memories: MemoryPreview[];
  mode: "preview";
  total: number;
  profile?: unknown;
  raw: unknown;
}

export interface RecallFullResult {
  memories: unknown[];
  mode: "full";
  fetched: number;
  profile?: unknown;
  raw: unknown;
}

export interface RecallFileResult {
  file: string;
  count: number;
  totalChars: number;
  mode: "file";
  previews: MemoryPreview[];
  raw: unknown;
}

export type RecallResult = RecallPreviewResult | RecallFullResult | RecallFileResult;

// ---------------------------------------------------------------------------
// listProjects (mirrors ListProjectsInput in memory_tools.py)
// ---------------------------------------------------------------------------

export interface ListProjectsInput {
  /** Force re-fetch from DB instead of 5-min cache. */
  refresh?: boolean;
}

export interface ProjectInfo {
  id: string;
  name: string;
  slug: string;
  cwd?: string;
}

export interface ListProjectsResult {
  projects: ProjectInfo[];
  raw: unknown;
}

// ---------------------------------------------------------------------------
// whoAmI (mirrors WhoAmIInput — no fields)
// ---------------------------------------------------------------------------

export interface WhoAmIResult {
  userId: string;
  projectId?: string;
  email?: string;
  scope?: string;
  sessionId?: string;
  client?: unknown;
  raw: unknown;
}

// ---------------------------------------------------------------------------
// init (mirrors InitInput in memory_tools.py)
// ---------------------------------------------------------------------------

export interface InitInput {
  /** Current working directory path. Pass process.cwd(). */
  cwd?: string;
  /** Project display name. Defaults to directory name. */
  projectName?: string;
}

export interface InitResult {
  success: boolean;
  projectId?: string;
  projectName?: string;
  anchor?: string;
  files?: Record<string, string>;
  instructions?: string;
  error?: string;
  raw: unknown;
}

// ---------------------------------------------------------------------------
// recommend (mirrors RecommendInput in instinct_tools.py)
// ---------------------------------------------------------------------------

export interface RecommendInput {
  /** Filter by domain: code-style, testing, git, debugging, etc. */
  domain?: string;
  /** Minimum confidence threshold (0.0–0.9). */
  minConfidence?: number;
  /** Only return instincts promoted to skill suggestions. */
  promotedOnly?: boolean;
  /** Max results (1–20). Default 10. */
  limit?: number;
}

export interface InstinctInfo {
  instinct_id: string;
  domain: string;
  pattern: string;
  confidence: number;
  count: number;
  suggested_skills?: string[];
  [key: string]: unknown;
}

export interface RecommendResult {
  instincts: InstinctInfo[];
  total: number;
  hint: string;
  raw: unknown;
}

// ---------------------------------------------------------------------------
// contradict (mirrors ContradictInput in instinct_tools.py)
// ---------------------------------------------------------------------------

export interface ContradictInput {
  /** instinct_id to decay (obtain from recommend). */
  instinctId: string;
}

export interface ContradictResult {
  success: boolean;
  action?: string;
  instinctId?: string;
  error?: string;
  raw: unknown;
}

// ---------------------------------------------------------------------------
// Client constructor options
// ---------------------------------------------------------------------------

export interface PilociClientOptions {
  /** Base URL of your piLoci instance, e.g. "https://my.piloci". */
  baseUrl: string;
  /** JWT token. Generate one in /settings → Tokens. */
  token: string;
  /**
   * Request timeout in milliseconds. Default 30 000 (30 s).
   * Set to 0 to disable.
   */
  timeoutMs?: number;
}
