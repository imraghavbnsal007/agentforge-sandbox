import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ShowcaseBanner } from "@/components/ShowcaseBanner";

afterEach(cleanup);

describe("portfolio demo banner", () => {
  it("names the mode unmistakably", () => {
    render(<ShowcaseBanner />);
    expect(screen.getByText("Portfolio Demo Mode")).toBeDefined();
  });

  it("says what is disabled, so a missing button is not a mystery", () => {
    render(<ShowcaseBanner />);
    const banner = screen.getByRole("status").textContent ?? "";
    expect(banner).toMatch(/sample repository/i);
    expect(banner).toMatch(/publishing to github/i);
    expect(banner).toMatch(/disabled/i);
  });

  it("is announced rather than purely decorative", () => {
    render(<ShowcaseBanner />);
    expect(screen.getByRole("status")).toBeDefined();
  });
});
