/**
 * piLoci TypeScript SDK — main client module.
 *
 * Wraps the piLoci REST shim at /api/v1/... using platform fetch (Node 18+).
 * Zero runtime dependencies.
 */

import {
  PilociError,
  PilociAuthError,
  PilociPermissionError,
  PilociValidationError,
  PilociServerError,
} from "./errors.js";
import type {
  PilociClientOptions,
  MemorySaveInput,
  MemoryForgetInput,
  MemorySaveResult,
  MemoryForgetResult,
  RecallInput,
  RecallResult,
  ListProjectsInput,
  ListProjectsResult,
  WhoAmIResult,
  InitInput,
  InitResult,
  RecommendInput,
  RecommendResult,
  ContradictInput,
  ContradictResult,
} from "./types.js";

// Version injected at build time by tsup's `define` option; falls back to
// the literal string so it always resolves at runtime.
declare const __SDK_VERSION__: string;
const SDK_VERSION =
  typeof __SDK_VERSION__ !== "undefined" ? __SDK_VERSION__ : "0.1.0";

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/** Convert camelCase keys one level deep to snake_case. */
function toSnake(obj: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(obj)) {
    const snake = k.replace(/([A-Z])/g, (c) => `_${c.toLowerCase()}`);
    out[snake] = v;
  }
  return out;
}

/** Parse and throw typed errors from a failed Response. */
async function throwFromResponse(res: Response): Promise<never> {
  let body: unknown;
  try {
    body = await res.json();
  } catch {
    body = await res.text().catch(() => null);
  }

  const msg =
    typeof body === "object" && body !== null && "detail" in body
      ? String((body as Record<string, unknown>)["detail"])
      : `HTTP ${res.status}`;

  if (res.status === 401) throw new PilociAuthError(msg, body);
  if (res.status === 403) throw new PilociPermissionError(msg, body);
  if (res.status === 422) {
    const details =
      typeof body === "object" && body !== null && "detail" in body
        ? (body as Record<string, unknown>)["detail"]
        : body;
    throw new PilociValidationError(msg, details, body);
  }
  if (res.status >= 500)
    throw new PilociServerError(msg, res.status, body);
  throw new PilociError(msg, res.status, body);
}

// ---------------------------------------------------------------------------
// Memory namespace
// ---------------------------------------------------------------------------

class MemoryNamespace {
  constructor(
    private readonly http: HttpClient,
    private readonly project?: string
  ) {}

  /** Save a new memory. */
  async save(input: MemorySaveInput): Promise<MemorySaveResult> {
    const wire = toSnake({
      action: "save" as const,
      content: input.content,
      ...(input.tags !== undefined ? { tags: input.tags } : {}),
    });
    const raw = await this.http.post("/api/v1/memory", wire, this.project);
    return {
      success: (raw as Record<string, unknown>)["success"] as boolean,
      action: "save",
      memoryId: (raw as Record<string, unknown>)["memory_id"] as string,
      projectId: (raw as Record<string, unknown>)["project_id"] as string,
      raw,
    };
  }

  /** Remove a memory by ID. */
  async delete(input: MemoryForgetInput): Promise<MemoryForgetResult> {
    const wire = toSnake({
      action: "forget" as const,
      // content is required by the model even for forget; send empty string
      content: "",
      memoryId: input.memoryId,
    });
    const raw = await this.http.post("/api/v1/memory", wire, this.project);
    return {
      success: (raw as Record<string, unknown>)["success"] as boolean,
      action: "forget",
      memoryId: (raw as Record<string, unknown>)["memory_id"] as string,
      raw,
    };
  }
}

// ---------------------------------------------------------------------------
// Projects namespace
// ---------------------------------------------------------------------------

class ProjectsNamespace {
  constructor(private readonly http: HttpClient) {}

  /** List all projects for the authenticated user. */
  async list(input: ListProjectsInput = {}): Promise<ListProjectsResult> {
    const params = input.refresh ? "?refresh=true" : "";
    const raw = await this.http.get(`/api/v1/projects${params}`);
    return {
      projects: ((raw as Record<string, unknown>)["projects"] ?? []) as ListProjectsResult["projects"],
      raw,
    };
  }

  /** One-time project setup — returns CLAUDE.md / AGENTS.md content. */
  async init(input: InitInput = {}): Promise<InitResult> {
    const wire = toSnake({
      ...(input.cwd !== undefined ? { cwd: input.cwd } : {}),
      ...(input.projectName !== undefined ? { projectName: input.projectName } : {}),
    });
    const raw = await this.http.post("/api/v1/init", wire);
    const r = raw as Record<string, unknown>;
    return {
      success: r["success"] as boolean,
      projectId: r["project_id"] as string | undefined,
      projectName: r["project_name"] as string | undefined,
      anchor: r["anchor"] as string | undefined,
      files: r["files"] as Record<string, string> | undefined,
      instructions: r["instructions"] as string | undefined,
      error: r["error"] as string | undefined,
      raw,
    };
  }
}

// ---------------------------------------------------------------------------
// Internal HTTP client
// ---------------------------------------------------------------------------

class HttpClient {
  private readonly baseUrl: string;
  private readonly token: string;
  private readonly timeoutMs: number;

  constructor(opts: PilociClientOptions) {
    this.baseUrl = opts.baseUrl.replace(/\/$/, "");
    this.token = opts.token;
    this.timeoutMs = opts.timeoutMs ?? 30_000;
  }

  private buildHeaders(project?: string): Record<string, string> {
    const h: Record<string, string> = {
      Authorization: `Bearer ${this.token}`,
      "Content-Type": "application/json",
      "User-Agent": `piloci-sdk-js/${SDK_VERSION}`,
    };
    if (project) h["X-Piloci-Project"] = project;
    return h;
  }

  private signal(): AbortSignal | undefined {
    if (this.timeoutMs <= 0) return undefined;
    return AbortSignal.timeout(this.timeoutMs);
  }

  async get(path: string, project?: string): Promise<unknown> {
    const res = await fetch(`${this.baseUrl}${path}`, {
      method: "GET",
      headers: this.buildHeaders(project),
      signal: this.signal(),
    });
    if (!res.ok) await throwFromResponse(res);
    return res.json();
  }

  async post(path: string, body: unknown, project?: string): Promise<unknown> {
    const res = await fetch(`${this.baseUrl}${path}`, {
      method: "POST",
      headers: this.buildHeaders(project),
      body: JSON.stringify(body),
      signal: this.signal(),
    });
    if (!res.ok) await throwFromResponse(res);
    return res.json();
  }
}

// ---------------------------------------------------------------------------
// Main Piloci class
// ---------------------------------------------------------------------------

/**
 * piLoci SDK client.
 *
 * ```ts
 * const client = new Piloci({ baseUrl: "https://my.piloci", token: "JWT.xxx" });
 * await client.memory.save({ content: "we use argon2id", tags: ["security"] });
 * const result = await client.recall({ query: "auth decision", limit: 5 });
 * ```
 */
export class Piloci {
  /** Memory operations: save, delete. */
  public readonly memory: MemoryNamespace;
  /** Project operations: list, init. */
  public readonly projects: ProjectsNamespace;

  private readonly http: HttpClient;
  private readonly projectHeader: string | undefined;

  constructor(opts: PilociClientOptions) {
    this.http = new HttpClient(opts);
    this.projectHeader = undefined;
    this.memory = new MemoryNamespace(this.http, this.projectHeader);
    this.projects = new ProjectsNamespace(this.http);
  }

  /**
   * Search memories by semantic similarity.
   *
   * @param input - RecallInput (camelCase)
   * @param project - Optional project header override (X-Piloci-Project)
   */
  async recall(input: RecallInput, project?: string): Promise<RecallResult> {
    const wire = toSnake({
      ...(input.query !== undefined ? { query: input.query } : {}),
      ...(input.fetchIds !== undefined ? { fetchIds: input.fetchIds } : {}),
      ...(input.toFile !== undefined ? { toFile: input.toFile } : {}),
      ...(input.includeProfile !== undefined
        ? { includeProfile: input.includeProfile }
        : {}),
      ...(input.tags !== undefined ? { tags: input.tags } : {}),
      ...(input.limit !== undefined ? { limit: input.limit } : {}),
    });
    const raw = await this.http.post("/api/v1/recall", wire, project);
    const r = raw as Record<string, unknown>;
    const mode = r["mode"] as string;

    if (mode === "file") {
      return {
        file: r["file"] as string,
        count: r["count"] as number,
        totalChars: r["total_chars"] as number,
        mode: "file",
        previews: (r["previews"] ?? []) as RecallResult extends { previews: infer P } ? P : never,
        raw,
      };
    }
    if (mode === "full") {
      return {
        memories: (r["memories"] ?? []) as unknown[],
        mode: "full",
        fetched: r["fetched"] as number,
        profile: r["profile"],
        raw,
      };
    }
    // default: preview
    const previews = ((r["memories"] ?? []) as Record<string, unknown>[]).map(
      (m) => ({
        id: m["id"] as string,
        score: m["score"] as number,
        tags: (m["tags"] ?? []) as string[],
        excerpt: m["excerpt"] as string,
        length: m["length"] as number,
        createdAt: m["created_at"] as string | undefined,
      })
    );
    return {
      memories: previews,
      mode: "preview",
      total: r["total"] as number,
      profile: r["profile"],
      raw,
    };
  }

  /** Return current user information. */
  async whoami(): Promise<WhoAmIResult> {
    const raw = await this.http.get("/api/v1/whoami");
    const r = raw as Record<string, unknown>;
    return {
      userId: r["userId"] as string,
      projectId: r["projectId"] as string | undefined,
      email: r["email"] as string | undefined,
      scope: r["scope"] as string | undefined,
      sessionId: r["sessionId"] as string | undefined,
      client: r["client"],
      raw,
    };
  }

  /**
   * Surface high-confidence behavioral instincts.
   *
   * @param input - RecommendInput (camelCase)
   * @param project - Optional project header override (X-Piloci-Project)
   */
  async recommend(
    input: RecommendInput = {},
    project?: string
  ): Promise<RecommendResult> {
    const wire = toSnake({
      ...(input.domain !== undefined ? { domain: input.domain } : {}),
      ...(input.minConfidence !== undefined
        ? { minConfidence: input.minConfidence }
        : {}),
      ...(input.promotedOnly !== undefined
        ? { promotedOnly: input.promotedOnly }
        : {}),
      ...(input.limit !== undefined ? { limit: input.limit } : {}),
    });
    const raw = await this.http.post("/api/v1/recommend", wire, project);
    const r = raw as Record<string, unknown>;
    return {
      instincts: (r["instincts"] ?? []) as RecommendResult["instincts"],
      total: r["total"] as number,
      hint: r["hint"] as string,
      raw,
    };
  }

  /**
   * Mark an instinct as wrong — decays its confidence score.
   *
   * @param input - ContradictInput (camelCase)
   * @param project - Optional project header override (X-Piloci-Project)
   */
  async contradict(
    input: ContradictInput,
    project?: string
  ): Promise<ContradictResult> {
    const wire = toSnake({ instinctId: input.instinctId });
    const raw = await this.http.post("/api/v1/contradict", wire, project);
    const r = raw as Record<string, unknown>;
    return {
      success: r["success"] as boolean,
      action: r["action"] as string | undefined,
      instinctId: r["instinct_id"] as string | undefined,
      error: r["error"] as string | undefined,
      raw,
    };
  }
}
