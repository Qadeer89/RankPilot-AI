import { expect, test, type Page, type Route } from "@playwright/test";
import { FakeApi, SITE } from "./support/fakeApi";

const cors = { "access-control-allow-origin": "*", "access-control-allow-headers": "*", "access-control-allow-methods": "*" };
const task = (id: string, url: string) => ({ id, website_id: SITE, opportunity_id: null, task_type: "set_title", status: "completed", risk_tier: 1, approval_status: "approved", proposed_change_json: { target_url: url, value: "New title" } });
const change = (taskId: string, recrawl: Record<string, unknown>) => ({ id: `c-${taskId}`, website_id: SITE, page_id: null, seo_task_id: taskId, connector_type: "sanity", before_state_json: {}, after_state_json: { recrawl }, actor_type: "system", executed_at: "2026-11-20T10:00:00Z", validation_status: "passed" });

test("each completed task says whether the live page was confirmed, is being re-checked, or still shows the old value", async ({ page }: { page: Page }) => {
  const api = new FakeApi();
  await api.install(page);
  const json = (route: Route, body: unknown) => route.request().method() === "OPTIONS" ? route.fulfill({ status: 204, headers: cors }) : route.fulfill({ status: 200, contentType: "application/json", headers: cors, body: JSON.stringify(body) });
  await page.route(/\/websites\/[^/]+\/(crawls|pages|findings|opportunities|connections|reports|health-score)(\?.*)?$/, (route: Route) => json(route, []));
  await page.route(/\/websites\/[^/]+\/tasks(\?.*)?$/, (route: Route) => json(route, [task("t1", "https://x.example/a"), task("t2", "https://x.example/b"), task("t3", "https://x.example/c"), task("t4", "https://x.example/d")]));
  await page.route(/\/websites\/[^/]+\/change-records(\?.*)?$/, (route: Route) => json(route, [
    change("t1", { status: "validated" }),
    change("t2", { status: "queued", attempt: 2, note: "The live page still showed the old value, which can be a cached copy. Checking again shortly." }),
    change("t3", { status: "mismatch", attempt: 3, note: "The live page still showed the old value after 3 checks." }),
  ]));
  await page.goto(`/dashboard/websites/${SITE}`);
  await page.getByRole("button", { name: "Tasks", exact: true }).click();
  const lines = page.getByTestId("live-check");
  await expect(lines).toHaveCount(4);
  await expect(lines.nth(0)).toContainText("change confirmed");
  await expect(lines.nth(1)).toContainText("checking (attempt 2)");
  await expect(lines.nth(1)).toContainText("cached copy");
  await expect(lines.nth(2)).toContainText("still showed the old value after 3 checks");
  await expect(lines.nth(3)).toContainText("not checked yet");
  // the validation result is a badge, not plain text
  const badges = page.getByTestId("validation-badge");
  await expect(badges.first()).toContainText("Validation passed");
  await expect(badges.first().locator("span").first()).toBeVisible();
  await expect(page.getByText("last execution validation")).toHaveCount(0);
});
