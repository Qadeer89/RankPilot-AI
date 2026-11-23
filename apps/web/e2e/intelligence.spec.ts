import { expect, test, type Page, type Route } from "@playwright/test";
import { SITE } from "./support/fakeApi";

const ORG = "00000000-0000-4000-8000-000000000001";
const TECH = { computed_at: "2026-11-23T10:00:00Z", formula_version: "technical-health-v1", score: 66.7, coverage: 0.9, available: true, data_source: "Verified (fetched from your site) + RankPilot calculated",
  checks: [{ key: "open_graph", label: "Open Graph tags (social previews)", status: "warn", detail: "Missing: og:image.", group: "technical" }, { key: "hreflang", label: "hreflang annotations", status: "not_tested", detail: "None found.", group: "technical" },
           { key: "hdr_hsts", label: "HSTS header", status: "warn", detail: "Not sent.", group: "security_hygiene" }] };

class Fake {
  ran = false; kinds: string[] = [];
  async install(page: Page) {
    await page.addInitScript(() => localStorage.setItem("rankpilot_access_token", "test-token"));
    await page.route("**/api/v1/**", (r) => this.handle(r));
  }
  private json(route: Route, body: unknown, status = 200) {
    return route.fulfill({ status, contentType: "application/json", headers: { "access-control-allow-origin": "*", "access-control-allow-headers": "*", "access-control-allow-methods": "*" }, body: JSON.stringify(body) });
  }
  private async handle(route: Route) {
    const req = route.request();
    if (req.method() === "OPTIONS") return this.json(route, {}, 204);
    const p = new URL(req.url()).pathname;
    if (p.endsWith("/me")) return this.json(route, { user: { id: "u1", email: "o@example.com", is_platform_admin: false, is_super_admin: false, email_verified: true }, organizations: [{ id: ORG, name: "Org", slug: "org", role: "owner" }] });
    const m = p.match(/\/intelligence\/(\w+?)(\/run)?$/);
    if (m) {
      this.kinds.push(`${req.method()} ${m[1]}`);
      if (m[2]) { this.ran = true; return this.json(route, TECH); }
      if (m[1] === "technical" && this.ran) return this.json(route, { latest: TECH, history: [], empty_reason: null });
      return this.json(route, { latest: null, history: [], empty_reason: "Not run yet. Run it to see results." });
    }
    return this.json(route, { detail: `fake: unhandled ${p}` }, 404);
  }
}

test("each analysis starts empty, runs on demand, and shows tested vs not tested honestly", async ({ page }) => {
  const fake = new Fake();
  await fake.install(page);
  await page.goto(`/dashboard/websites/${SITE}/intelligence`);
  await expect(page.getByRole("heading", { name: "SEO Intelligence" })).toBeVisible();
  await expect(page.getByTestId("intel-empty")).toContainText("Not run yet");
  await page.getByRole("tab", { name: "Technical" }).click();
  await expect(page.getByTestId("intel-empty")).toBeVisible();
  await page.getByRole("button", { name: "Run technical checks" }).click();
  const rows = page.getByTestId("tech-checks");
  await expect(rows.getByRole("row", { name: /hreflang/ })).toContainText("Not tested");
  await expect(rows.getByRole("row", { name: /HSTS/ })).toContainText("hygiene, not a ranking factor");
  await expect(page.getByTestId("intel-score")).toHaveText("Score 66.7");
  expect(fake.kinds).toContain("POST technical");
});
