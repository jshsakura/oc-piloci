/**
 * @piloci/sdk — vitest test suite
 *
 * Mocks globalThis.fetch — no HTTP traffic, no msw dependency.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  Piloci,
  PilociAuthError,
  PilociPermissionError,
  PilociValidationError,
  PilociServerError,
  PilociError,
} from "../src/index.js";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function mockFetch(status: number, body: unknown) {
  const res = {
    ok: status >= 200 && status < 300,
    status,
    json: vi.fn().mockResolvedValue(body),
    text: vi.fn().mockResolvedValue(JSON.stringify(body)),
  };
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(res));
  return res;
}

function lastFetchCall() {
  const calls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls;
  return calls[calls.length - 1] as [string, RequestInit];
}

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.unstubAllGlobals();
});

const BASE = "https://my.piloci";
const TOKEN = "test.jwt.token";

function client(extra?: { timeoutMs?: number }) {
  return new Piloci({ baseUrl: BASE, token: TOKEN, ...extra });
}

// ---------------------------------------------------------------------------
// 1. memory.save — happy path
// ---------------------------------------------------------------------------

describe("memory.save", () => {
  it("posts to /api/v1/memory with snake_case body and returns camelCase result", async () => {
    mockFetch(200, {
      success: true,
      action: "save",
      memory_id: "mem-123",
      project_id: "proj-abc",
    });

    const result = await client().memory.save({
      content: "we decided to use argon2id",
      tags: ["security"],
    });

    expect(result.success).toBe(true);
    expect(result.memoryId).toBe("mem-123");
    expect(result.projectId).toBe("proj-abc");

    const [, init] = lastFetchCall();
    const body = JSON.parse(init.body as string);
    expect(body.action).toBe("save");
    expect(body.content).toBe("we decided to use argon2id");
    expect(body.tags).toEqual(["security"]);
  });
});

// ---------------------------------------------------------------------------
// 2. memory.delete — happy path
// ---------------------------------------------------------------------------

describe("memory.delete", () => {
  it("posts action=forget with memory_id snake_case", async () => {
    mockFetch(200, { success: true, action: "forget", memory_id: "mem-999" });

    const result = await client().memory.delete({ memoryId: "mem-999" });

    expect(result.success).toBe(true);
    expect(result.action).toBe("forget");
    expect(result.memoryId).toBe("mem-999");

    const [, init] = lastFetchCall();
    const body = JSON.parse(init.body as string);
    expect(body.action).toBe("forget");
    expect(body.memory_id).toBe("mem-999");
  });
});

// ---------------------------------------------------------------------------
// 3. recall — preview mode happy path + camelCase conversion
// ---------------------------------------------------------------------------

describe("recall", () => {
  it("returns preview result and converts created_at to createdAt", async () => {
    mockFetch(200, {
      mode: "preview",
      total: 2,
      memories: [
        { id: "m1", score: 0.92, tags: ["security"], excerpt: "argon2id...", length: 120, created_at: "2026-01-01T00:00:00Z" },
        { id: "m2", score: 0.81, tags: [], excerpt: "bcrypt...", length: 60, created_at: null },
      ],
    });

    const result = await client().recall({ query: "what auth did we pick?", limit: 5 });

    expect(result.mode).toBe("preview");
    if (result.mode !== "preview") return;
    expect(result.total).toBe(2);
    expect(result.memories[0].id).toBe("m1");
    expect(result.memories[0].score).toBe(0.92);
    expect(result.memories[0].createdAt).toBe("2026-01-01T00:00:00Z");

    const [url, init] = lastFetchCall();
    expect(url).toBe(`${BASE}/api/v1/recall`);
    const body = JSON.parse(init.body as string);
    expect(body.query).toBe("what auth did we pick?");
    expect(body.limit).toBe(5);
  });

  it("sends fetchIds as fetch_ids", async () => {
    mockFetch(200, { mode: "full", fetched: 1, memories: [{ memory_id: "m1", content: "full" }] });

    const result = await client().recall({ fetchIds: ["m1"] });
    expect(result.mode).toBe("full");

    const [, init] = lastFetchCall();
    const body = JSON.parse(init.body as string);
    expect(body.fetch_ids).toEqual(["m1"]);
  });

  it("handles file mode response", async () => {
    mockFetch(200, {
      mode: "file",
      file: "/data/recall_20260101.md",
      count: 3,
      total_chars: 800,
      previews: [],
    });

    const result = await client().recall({ query: "auth", toFile: true });
    expect(result.mode).toBe("file");
    if (result.mode !== "file") return;
    expect(result.file).toBe("/data/recall_20260101.md");
    expect(result.totalChars).toBe(800);
  });
});

// ---------------------------------------------------------------------------
// 4. projects.list — happy path
// ---------------------------------------------------------------------------

describe("projects.list", () => {
  it("GET /api/v1/projects and returns projects array", async () => {
    mockFetch(200, { projects: [{ id: "p1", name: "piLoci", slug: "piloci" }] });

    const result = await client().projects.list();
    expect(result.projects).toHaveLength(1);
    expect(result.projects[0].slug).toBe("piloci");

    const [url, init] = lastFetchCall();
    expect(url).toBe(`${BASE}/api/v1/projects`);
    expect(init.method).toBe("GET");
  });

  it("appends ?refresh=true when refresh option set", async () => {
    mockFetch(200, { projects: [] });
    await client().projects.list({ refresh: true });
    const [url] = lastFetchCall();
    expect(url).toContain("?refresh=true");
  });
});

// ---------------------------------------------------------------------------
// 5. whoami — happy path
// ---------------------------------------------------------------------------

describe("whoami", () => {
  it("GET /api/v1/whoami and maps fields", async () => {
    mockFetch(200, {
      userId: "u-1",
      projectId: "p-1",
      email: "test@example.com",
      scope: "project",
      sessionId: "sess-1",
      client: { name: "claude" },
    });

    const result = await client().whoami();
    expect(result.userId).toBe("u-1");
    expect(result.email).toBe("test@example.com");
    expect(result.scope).toBe("project");

    const [url, init] = lastFetchCall();
    expect(url).toBe(`${BASE}/api/v1/whoami`);
    expect(init.method).toBe("GET");
  });
});

// ---------------------------------------------------------------------------
// 6. projects.init — happy path
// ---------------------------------------------------------------------------

describe("projects.init", () => {
  it("POST /api/v1/init with snake_case body", async () => {
    mockFetch(200, {
      success: true,
      project_id: "p-new",
      project_name: "MyProject",
      anchor: "## piLoci Memory",
      files: { "CLAUDE.md": "content" },
      instructions: "append or create",
    });

    const result = await client().projects.init({ cwd: "/home/pi/myproject", projectName: "MyProject" });
    expect(result.success).toBe(true);
    expect(result.projectId).toBe("p-new");
    expect(result.files?.["CLAUDE.md"]).toBe("content");

    const [, init] = lastFetchCall();
    const body = JSON.parse(init.body as string);
    expect(body.cwd).toBe("/home/pi/myproject");
    expect(body.project_name).toBe("MyProject");
  });
});

// ---------------------------------------------------------------------------
// 7. recommend — happy path
// ---------------------------------------------------------------------------

describe("recommend", () => {
  it("POST /api/v1/recommend with snake_case params", async () => {
    mockFetch(200, {
      instincts: [{ instinct_id: "i-1", domain: "testing", pattern: "use vitest", confidence: 0.8, count: 5 }],
      total: 1,
      hint: "use contradict to lower confidence",
    });

    const result = await client().recommend({ minConfidence: 0.5, limit: 5 });
    expect(result.total).toBe(1);
    expect(result.instincts[0].instinct_id).toBe("i-1");

    const [, init] = lastFetchCall();
    const body = JSON.parse(init.body as string);
    expect(body.min_confidence).toBe(0.5);
    expect(body.limit).toBe(5);
  });
});

// ---------------------------------------------------------------------------
// 8. contradict — happy path
// ---------------------------------------------------------------------------

describe("contradict", () => {
  it("POST /api/v1/contradict with instinct_id snake_case", async () => {
    mockFetch(200, { success: true, action: "confidence_decayed", instinct_id: "i-1" });

    const result = await client().contradict({ instinctId: "i-1" });
    expect(result.success).toBe(true);
    expect(result.instinctId).toBe("i-1");

    const [, init] = lastFetchCall();
    const body = JSON.parse(init.body as string);
    expect(body.instinct_id).toBe("i-1");
  });
});

// ---------------------------------------------------------------------------
// 9. Error mapping — 401 → PilociAuthError
// ---------------------------------------------------------------------------

describe("error mapping", () => {
  it("401 throws PilociAuthError", async () => {
    mockFetch(401, { detail: "Token expired" });
    await expect(client().whoami()).rejects.toBeInstanceOf(PilociAuthError);
  });

  it("403 throws PilociPermissionError with helpful message", async () => {
    mockFetch(403, { detail: "project_id required" });
    const err = await client().recall({ query: "x" }).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(PilociPermissionError);
    expect((err as PilociPermissionError).status).toBe(403);
  });

  it("422 throws PilociValidationError carrying details", async () => {
    const detail = [{ loc: ["body", "content"], msg: "field required" }];
    mockFetch(422, { detail });
    const err = await client().memory.save({ content: "" }).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(PilociValidationError);
    expect((err as PilociValidationError).details).toEqual(detail);
  });

  it("500 throws PilociServerError", async () => {
    mockFetch(500, { detail: "Internal Server Error" });
    const err = await client().whoami().catch((e: unknown) => e);
    expect(err).toBeInstanceOf(PilociServerError);
    expect((err as PilociServerError).status).toBe(500);
  });

  it("503 throws PilociServerError with correct status", async () => {
    mockFetch(503, { detail: "Service Unavailable" });
    const err = await client().projects.list().catch((e: unknown) => e);
    expect(err).toBeInstanceOf(PilociServerError);
    expect((err as PilociServerError).status).toBe(503);
  });

  it("404 throws base PilociError", async () => {
    mockFetch(404, { detail: "Not found" });
    const err = await client().whoami().catch((e: unknown) => e);
    expect(err).toBeInstanceOf(PilociError);
    expect((err as PilociError).status).toBe(404);
  });
});

// ---------------------------------------------------------------------------
// 10. Authorization header is set
// ---------------------------------------------------------------------------

describe("auth header", () => {
  it("sends Authorization: Bearer <token> on every request", async () => {
    mockFetch(200, { projects: [] });
    await client().projects.list();
    const [, init] = lastFetchCall();
    const headers = init.headers as Record<string, string>;
    expect(headers["Authorization"]).toBe(`Bearer ${TOKEN}`);
  });
});

// ---------------------------------------------------------------------------
// 11. User-Agent header
// ---------------------------------------------------------------------------

describe("User-Agent header", () => {
  it("sets User-Agent to piloci-sdk-js/<version>", async () => {
    mockFetch(200, { projects: [] });
    await client().projects.list();
    const [, init] = lastFetchCall();
    const headers = init.headers as Record<string, string>;
    expect(headers["User-Agent"]).toMatch(/^piloci-sdk-js\//);
  });
});

// ---------------------------------------------------------------------------
// 12. Optional X-Piloci-Project header
// ---------------------------------------------------------------------------

describe("X-Piloci-Project header", () => {
  it("sends X-Piloci-Project when project arg is provided to recall", async () => {
    mockFetch(200, { mode: "preview", total: 0, memories: [] });
    await client().recall({ query: "test" }, "my-project-slug");
    const [, init] = lastFetchCall();
    const headers = init.headers as Record<string, string>;
    expect(headers["X-Piloci-Project"]).toBe("my-project-slug");
  });

  it("does not send X-Piloci-Project header when project arg is omitted", async () => {
    mockFetch(200, { mode: "preview", total: 0, memories: [] });
    await client().recall({ query: "test" });
    const [, init] = lastFetchCall();
    const headers = init.headers as Record<string, string>;
    expect(headers["X-Piloci-Project"]).toBeUndefined();
  });

  it("sends X-Piloci-Project for recommend and contradict", async () => {
    mockFetch(200, { instincts: [], total: 0, hint: "" });
    await client().recommend({}, "proj-slug");
    const [, initRec] = lastFetchCall();
    expect((initRec.headers as Record<string, string>)["X-Piloci-Project"]).toBe("proj-slug");

    mockFetch(200, { success: true, instinct_id: "i-1" });
    await client().contradict({ instinctId: "i-1" }, "proj-slug");
    const [, initCon] = lastFetchCall();
    expect((initCon.headers as Record<string, string>)["X-Piloci-Project"]).toBe("proj-slug");
  });
});

// ---------------------------------------------------------------------------
// 13. Timeout configuration
// ---------------------------------------------------------------------------

describe("timeout configuration", () => {
  it("uses AbortSignal.timeout with configured timeoutMs", async () => {
    // AbortSignal.timeout is a static method on AbortSignal available in Node 18+
    const timeoutSpy = vi.spyOn(AbortSignal, "timeout");
    mockFetch(200, { projects: [] });

    await client({ timeoutMs: 5000 }).projects.list();
    expect(timeoutSpy).toHaveBeenCalledWith(5000);
    timeoutSpy.mockRestore();
  });

  it("does not set signal when timeoutMs is 0", async () => {
    const timeoutSpy = vi.spyOn(AbortSignal, "timeout");
    mockFetch(200, { projects: [] });

    await client({ timeoutMs: 0 }).projects.list();
    expect(timeoutSpy).not.toHaveBeenCalled();
    timeoutSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// 14. baseUrl trailing slash is stripped
// ---------------------------------------------------------------------------

describe("baseUrl normalization", () => {
  it("strips trailing slash from baseUrl", async () => {
    mockFetch(200, { projects: [] });
    const c = new Piloci({ baseUrl: "https://my.piloci/", token: TOKEN });
    await c.projects.list();
    const [url] = lastFetchCall();
    expect(url).toBe("https://my.piloci/api/v1/projects");
  });
});
