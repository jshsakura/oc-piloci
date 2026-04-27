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
