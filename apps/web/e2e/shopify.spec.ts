import { expect, test, type Page, type Route } from "@playwright/test";
import { SITE } from "./support/fakeApi";

const ORG = "00000000-0000-4000-8000-000000000001";
type Json = Record<string, unknown>;

class Fake {
  synced = false;
  proposals: Json[] = [];
  calls: string[] = [];
  summary() { return this.synced ? { products: 1, collections: 0, products_with_issues: 1, issue_counts: {}, last_synced_at: "2026-11-18T10:00:00Z" } : { products: 0, collections: 0, products_with_issues: 0, issue_counts: {}, last_synced_at: null }; }
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
    this.calls.push(`${req.method()} ${p.split("/shopify")[1] ?? p}`);
    if (p.endsWith("/me")) return this.json(route, { user: { id: "u1", email: "o@example.com", is_platform_admin: false, is_super_admin: false, email_verified: true }, organizations: [{ id: ORG, name: "Org", slug: "org", role: "owner" }] });
    if (p.endsWith("/shopify/summary")) return this.json(route, this.summary());
    if (p.endsWith("/shopify/sync")) { this.synced = true; return this.json(route, { products: 1, collections: 0, summary: this.summary() }); }
    if (p.endsWith("/shopify/catalog")) return this.json(route, { items: this.synced ? [{ id: "r1", external_id: "1", handle: "mug", url: null, title: "Ceramic Mug", seo_title: "Mug", meta_description: "", captured_at: "x", issues: [{ code: "META_MISSING", severity: "warning", message: "No meta description is set.", field: "meta_description" }] }] : [], total: 1 });
    if (p.endsWith("/propose")) { this.proposals = [{ id: "pr1", external_id: "1", title: "Ceramic Mug", field: "seo_title", before_value: "Mug", proposed_value: "Hand-Glazed Ceramic Mug", rationale: "r", status: "draft", verified: null, failure: null, label: "AI-written draft. It is only sent to your store after you approve it." }]; return this.json(route, { items: this.proposals }); }
    if (p.endsWith("/shopify/proposals")) return this.json(route, { items: this.proposals });
    if (p.endsWith("/decision")) { this.proposals[0] = { ...this.proposals[0], status: "approved" }; return this.json(route, this.proposals[0]); }
    if (p.endsWith("/apply")) { this.proposals[0] = { ...this.proposals[0], status: "applied", verified: true }; return this.json(route, this.proposals[0]); }
    return this.json(route, { detail: `fake: unhandled ${p}` }, 404);
  }
}

test("nothing reaches the store until the person approves and applies; the result is confirmed by read-back", async ({ page }) => {
  const fake = new Fake();
  await fake.install(page);
  await page.goto(`/dashboard/websites/${SITE}/shopify`);
  await expect(page.getByTestId("not-synced")).toBeVisible();
  await page.getByRole("button", { name: /Read my store/ }).click();
  await expect(page.getByTestId("summary")).toContainText("Products with issues");
  await expect(page.getByTestId("product")).toContainText("No meta description is set.");
  await page.getByRole("button", { name: "Draft SEO text with AI" }).click();
  const card = page.getByTestId("proposal");
  await expect(card).toContainText("only sent to your store after you approve it");
  expect(fake.calls.some((c) => c.includes("/apply"))).toBe(false);
  await card.getByRole("button", { name: "Approve" }).click();
  expect(fake.calls.some((c) => c.includes("/apply"))).toBe(false);
  await card.getByRole("button", { name: "Apply to store" }).click();
  await expect(card).toContainText("Confirmed by reading the live value back.");
  await expect(card.getByRole("button", { name: "Undo" })).toBeVisible();
});
