import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import BrandMark from "@/components/BrandMark";

describe("BrandMark Component", () => {
  it("renders the brand name", () => {
    render(<BrandMark />);
    expect(screen.getByText("piLoci")).toBeInTheDocument();
  });

  it("has a link to the home page", () => {
    render(<BrandMark />);
    const link = screen.getByRole("link");
    expect(link).toHaveAttribute("href", "/");
  });
});
