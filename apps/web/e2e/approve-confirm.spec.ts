import { expect, test, type Page, type Route } from "@playwright/test";
import { FakeApi, SITE } from "./support/fakeApi";

const cors = { "access-control-allow-origin": "*", "access-control-allow-headers": "*", "access-control-allow-methods": "*" };
const pending = { id: "t1", website_id: SITE, opportunity_id: null, task_type: "set_title", status: "pending", risk_tier: 1, approval_status: "pending", proposed_change_json: { target_url: "https://x.example/a", value: "Knee Pain | Brand" } };

test("approving a task asks for confirmation first, and only a confirmed approval reaches the server", async ({ page }: { page: Page }) => {
  const api = new FakeApi();
  await api.install(page);
  const approvals: string[] = [];
  const json = (route: Route, body: unknown) => route.request().method() === "OPTIONS" ? route.fulfill({ status: 204, headers: cors }) : route.fulfill({ status: 200, contentType: "application/json", headers: cors, body: JSON.stringify(body) });
  await page.route(/\/websites\/[^/]+\/(crawls|pages|findings|opportunities|connections|reports|health-score|change-records)(\?.*)?$/, (route: Route) => json(route, []));
  await page.route(/\/websites\/[^/]+\/tasks(\?.*)?$/, (route: Route) => json(route, [{ ...pending, ...(approvals.length ? { approval_status: "approved" } : {}) }]));
  await page.route(/\/tasks\/t1\/approve$/, (route: Route) => { if (route.request().method() === "POST") approvals.push("approve"); return json(route, { ...pending, approval_status: "approved" }); });
  await page.goto(`/dashboard/websites/${SITE}`);
  await page.getByRole("button", { name: "Tasks", exact: true }).click();
  await page.getByRole("button", { name: "Approve", exact: true }).click();
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toContainText("Approve this change?");
  await expect(dialog).toContainText("https://x.example/a");
  await expect(dialog).toContainText("Nothing is written to your website until you press Execute");
  expect(approvals).toEqual([]); // nothing was sent yet
  await dialog.getByRole("button", { name: "Cancel" }).click();
  expect(approvals).toEqual([]);
  await page.getByRole("button", { name: "Approve", exact: true }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Confirm" }).click();
  await expect.poll(() => approvals.length).toBe(1);
});
