import { describe, it, expect, vi, beforeEach } from "vitest";
import { api } from "@/lib/api";

global.fetch = vi.fn();

describe("api service", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("listAuthProviders should fetch from correct endpoint", async () => {
    const mockProviders = { providers: [{ name: "kakao", configured: true, login_path: "/auth/kakao" }] };
    (fetch as any).mockResolvedValue({
      ok: true,
      json: async () => mockProviders,
    });

    const result = await api.listAuthProviders();
    expect(fetch).toHaveBeenCalledWith("/api/auth/providers", expect.anything());
    expect(result).toEqual(mockProviders);
  });

  it("login should post to /auth/login", async () => {
    const mockUser = { id: "1", email: "test@example.com", name: "Test User" };
    (fetch as any).mockResolvedValue({
      ok: true,
      json: async () => mockUser,
    });

    const result = await api.login("test@example.com", "password");
    expect(fetch).toHaveBeenCalledWith("/auth/login", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ email: "test@example.com", password: "password" }),
    }));
    expect(result).toEqual(mockUser);
  });

  it("should throw error when response is not ok", async () => {
    (fetch as any).mockResolvedValue({
      ok: false,
      status: 401,
      json: async () => ({ error: "Unauthorized" }),
    });

    await expect(api.login("test@example.com", "wrong")).rejects.toThrow("Unauthorized");
  });
});

describe("api.chatStream", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  function makeStreamResponse(blocks: string[]): Response {
    const encoder = new TextEncoder();
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        for (const block of blocks) {
          controller.enqueue(encoder.encode(block));
        }
        controller.close();
      },
    });
    return new Response(stream, {
      status: 200,
      headers: { "Content-Type": "text/event-stream" },
    });
  }

  it("dispatches citations, tokens, and done in order", async () => {
    (fetch as any).mockResolvedValue(
      makeStreamResponse([
        'event: citations\ndata: [{"ref":"m1","memory_id":"a","content":"x","score":0.5,"tags":[]}]\n\n',
        'event: token\ndata: {"text":"hello"}\n\n',
        'event: token\ndata: {"text":" world"}\n\n',
        "event: done\ndata: {}\n\n",
      ])
    );

    const tokens: string[] = [];
    let citationsCount = 0;
    let doneCalled = false;

    await api.chatStream(
      { query: "hi", project_slug: "demo" },
      {
        onCitations: (c) => {
          citationsCount = c.length;
        },
        onToken: (t) => tokens.push(t),
        onDone: () => {
          doneCalled = true;
        },
      }
    );

    expect(citationsCount).toBe(1);
    expect(tokens).toEqual(["hello", " world"]);
    expect(doneCalled).toBe(true);
  });

  it("calls onError when an error event arrives mid-stream", async () => {
    (fetch as any).mockResolvedValue(
      makeStreamResponse([
        'event: token\ndata: {"text":"a"}\n\n',
        'event: error\ndata: {"error":"boom"}\n\n',
      ])
    );

    const tokens: string[] = [];
    let errorMessage: string | undefined;

    await api.chatStream(
      { query: "hi", project_slug: "demo" },
      {
        onToken: (t) => tokens.push(t),
        onError: (m) => {
          errorMessage = m;
        },
      }
    );

    expect(tokens).toEqual(["a"]);
    expect(errorMessage).toBe("boom");
  });

  it("surfaces error response body when status is not OK", async () => {
    (fetch as any).mockResolvedValue({
      ok: false,
      status: 503,
      json: async () => ({ error: "chat provider misconfigured" }),
    });

    let errorMessage: string | undefined;
    await api.chatStream(
      { query: "hi", project_slug: "demo" },
      {
        onError: (m) => {
          errorMessage = m;
        },
      }
    );

    expect(errorMessage).toContain("misconfigured");
  });

  it("handles SSE blocks split across chunks", async () => {
    (fetch as any).mockResolvedValue(
      makeStreamResponse([
        // first chunk: incomplete event
        'event: token\ndata: {"text":"par',
        // second chunk: completes previous event and adds another
        't1"}\n\nevent: token\ndata: {"text":"part2"}\n\n',
      ])
    );

    const tokens: string[] = [];
    await api.chatStream(
      { query: "hi", project_slug: "demo" },
      { onToken: (t) => tokens.push(t) }
    );

    expect(tokens).toEqual(["part1", "part2"]);
  });
});
