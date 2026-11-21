import { expect, test, type Page, type Route } from "@playwright/test";
import { FakeApi, SITE } from "./support/fakeApi";

const PLAN = { candidates: [{ url: "https://x.example/a", live_title: "Knee Pain | Brand | Brand", new_title: "Knee Pain | Brand" }], skipped_already_pending: 0, skipped: {}, reason_none: null, pages_with_applied_titles: 74, stopped_early: false };

test("title repair is done from the app: check read-only, then create tasks that wait for approval", async ({ page }: { page: Page }) => {
  const api = new FakeApi();
  await api.install(page);
  const calls: string[] = [];
  const cors = { "access-control-allow-origin": "*", "access-control-allow-headers": "*", "access-control-allow-methods": "*" };
  let created = false;
  const newTask = { id: "n1", website_id: SITE, opportunity_id: null, task_type: "set_title", status: "pending", risk_tier: 1, approval_status: "pending", proposed_change_json: { target_url: "https://x.example/a", value: "Knee Pain" } };
  await page.route(/\/websites\/[^/]+\/tasks(\?.*)?$/, (route: Route) =>
    route.request().method() === "OPTIONS" ? route.fulfill({ status: 204, headers: cors }) : route.fulfill({ status: 200, contentType: "application/json", headers: cors, body: JSON.stringify(created ? [newTask] : []) }));
  // the project page also loads these lists; empty is fine for this test
  await page.route(/\/websites\/[^/]+\/(crawls|pages|findings|opportunities|connections|reports|health-score)(\?.*)?$/, (route: Route) =>
    route.request().method() === "OPTIONS" ? route.fulfill({ status: 204, headers: cors }) : route.fulfill({ status: 200, contentType: "application/json", headers: cors, body: "[]" }));
  // registered after the fake API, so these routes take priority for the title-repair endpoints only
  await page.route("**/api/v1/**/title-repair/**", async (route: Route) => {
    const req = route.request();
    const p = new URL(req.url()).pathname;
    const h = { "access-control-allow-origin": "*", "access-control-allow-headers": "*", "access-control-allow-methods": "*" };
    if (req.method() === "OPTIONS") return route.fulfill({ status: 204, headers: h });
    calls.push(`${req.method()} ${p.split("/title-repair/")[1]}`);
    if (p.endsWith("/tasks") && req.method() === "POST") created = true;
    await new Promise((r) => setTimeout(r, 600)); // a slow server, so the progress messages have time to be seen
    const body = p.endsWith("/plan") ? PLAN : { created: 1, plan: PLAN, message: "Tasks were created and are waiting for your approval in the Tasks tab. Nothing has been changed on your website." };
    return route.fulfill({ status: 200, contentType: "application/json", headers: h, body: JSON.stringify(body) });
  });
  await page.goto(`/dashboard/websites/${SITE}`);
  await page.getByRole("button", { name: "Tasks", exact: true }).click();
  const card = page.getByRole("region", { name: "Fix doubled brand in titles" });
  await expect(card).toContainText("Nothing changes on your website until you approve");
  await card.getByRole("button", { name: "Check pages (read-only)" }).click();
  await expect(page.getByTestId("repair-busy")).toContainText("Checking the live pages one by one");
  await expect(page.getByTestId("repair-plan")).toContainText("Live now: Knee Pain | Brand | Brand");
  await expect(page.getByTestId("repair-plan")).toContainText("New title: Knee Pain | Brand");
  expect(calls).toEqual(["POST plan"]);
  await card.getByRole("button", { name: /Create 1 approval task/ }).click();
  await expect(page.getByTestId("repair-busy")).toContainText("Creating the tasks");
  await expect(page.getByTestId("repair-done")).toContainText("waiting for your approval");
  expect(calls).toEqual(["POST plan", "POST tasks"]);
  await expect(page.getByRole("button", { name: "Needs your approval (1)" })).toBeVisible(); // the list jumps to the new tasks
  await expect(page.getByText("https://x.example/a").last()).toBeVisible();
  await expect(page.getByTestId("repair-busy")).toHaveCount(0);
  expect(api.calls.some((c) => c.path.endsWith("/execute") || c.path.endsWith("/approve"))).toBe(false);
});
