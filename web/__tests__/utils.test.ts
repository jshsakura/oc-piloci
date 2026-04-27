import { describe, it, expect } from "vitest";
import { cn } from "@/lib/utils";

describe("cn utility", () => {
  it("should merge class names", () => {
    expect(cn("a", "b")).toBe("a b");
  });

  it("should merge tailwind classes correctly", () => {
    expect(cn("px-2 py-2", "px-4")).toBe("py-2 px-4");
  });

  it("should handle conditional classes", () => {
    expect(cn("base", true && "active", false && "hidden")).toBe("base active");
  });
});
