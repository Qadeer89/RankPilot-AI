import { expect, test, type Page, type Route } from "@playwright/test";
import { FakeApi, SITE } from "./support/fakeApi";

const cors = { "access-control-allow-origin": "*", "access-control-allow-headers": "*", "access-control-allow-methods": "*" };
const SHARED = "https://wa.me/923001234567";
const pages = Array.from({ length: 6 }, (_, i) => ({ id: `p${i}`, website_id: SITE, canonical_url: `https://x.example/blog/${i}`, normalized_url: `https://x.example/blog/${i}`, last_status_code: 200, indexability_state: "indexable", first_seen_at: "2026-11-01T00:00:00Z", last_seen_at: "2026-11-20T00:00:00Z" }));
const finding = (id: string, page: string, rule: string, severity: string, evidence: object) => ({ id, website_id: SITE, page_id: page, rule_code: rule, severity, confidence: 0.6, evidence_json: evidence, first_detected_at: "2026-11-10T00:00:00Z", last_detected_at: "2026-11-23T00:00:00Z", status: "open" });
const findings = [
  ...pages.map((p, i) => finding(`r${i}`, p.id, "EXTERNAL_LINK_REDIRECT", "info", { count: 1, urls: [SHARED] })),
  finding("t1", "p0", "TITLE_TOO_LONG", "info", { length: 74, threshold: 60 }),
  finding("c1", "p1", "THIN_CONTENT", "warning", { word_count: 90, threshold: 300, page_type: "contact" }),
];

async function setup(page: Page) {
  await new FakeApi().install(page);
  const json = (route: Route, body: unknown) => route.request().method() === "OPTIONS" ? route.fulfill({ status: 204, headers: cors }) : route.fulfill({ status: 200, contentType: "application/json", headers: cors, body: JSON.stringify(body) });
  await page.route(/\/websites\/[^/]+\/(crawls|opportunities|connections|reports|health-score|change-records|tasks)(\?.*)?$/, (route: Route) => json(route, []));
  await page.route(/\/websites\/[^/]+\/pages(\?.*)?$/, (route: Route) => json(route, pages));
  await page.route(/\/websites\/[^/]+\/findings(\?.*)?$/, (route: Route) => json(route, findings));
}

test("findings are grouped by rule, explain themselves, and show the evidence on click", async ({ page }: { page: Page }) => {
  await setup(page);
  await page.goto(`/dashboard/websites/${SITE}`);
  await page.getByRole("button", { name: "Findings", exact: true }).click();
  const groups = page.getByTestId("finding-group");
  await expect(groups).toHaveCount(3);
  await expect(groups.first()).toContainText("THIN_CONTENT"); // the warning comes before the info rules
  await expect(groups.nth(1)).toContainText("6 pages"); // six redirect findings, one group

  await groups.nth(1).getByRole("button").first().click();
  await expect(page.getByText("How to fix:").first()).toBeVisible();
  const shared = page.getByTestId("shared-link");
  await expect(shared).toContainText("Likely one shared link, not 6 separate problems");
  await expect(shared).toContainText(SHARED);

  await page.getByTestId("finding-item").first().getByRole("button", { name: "Show details" }).click();
  await expect(page.getByTestId("finding-evidence")).toContainText(SHARED);
});

test("evidence is readable for other rules too", async ({ page }: { page: Page }) => {
  await setup(page);
  await page.goto(`/dashboard/websites/${SITE}`);
  await page.getByRole("button", { name: "Findings", exact: true }).click();
  await page.getByTestId("finding-group").filter({ hasText: "TITLE_TOO_LONG" }).getByRole("button").first().click();
  await page.getByRole("button", { name: "Show details" }).click();
  await expect(page.getByTestId("finding-evidence")).toContainText("The title is 74 characters; search results show about 60.");
});
