import { expect, test, type Page, type Route } from "@playwright/test";
import { FakeApi, SITE } from "./support/fakeApi";

const cors = { "access-control-allow-origin": "*", "access-control-allow-headers": "*", "access-control-allow-methods": "*" };
const mk = (id: string, approval: string, status = "pending") => ({ id, website_id: SITE, opportunity_id: null, task_type: "set_title", status, risk_tier: 1, approval_status: approval, proposed_change_json: { target_url: `https://x.example/${id}`, value: `Title ${id}` } });

async function setup(page: Page, initial: ReturnType<typeof mk>[]) {
  const api = new FakeApi();
  await api.install(page);
  const state = { tasks: initial, calls: [] as string[] };
  const json = (route: Route, body: unknown) => route.request().method() === "OPTIONS" ? route.fulfill({ status: 204, headers: cors }) : route.fulfill({ status: 200, contentType: "application/json", headers: cors, body: JSON.stringify(body) });
  await page.route(/\/websites\/[^/]+\/(crawls|pages|findings|opportunities|connections|reports|health-score|change-records)(\?.*)?$/, (route: Route) => json(route, []));
  await page.route(/\/websites\/[^/]+\/tasks(\?.*)?$/, (route: Route) => json(route, state.tasks));
  await page.route(/\/tasks\/([^/]+)\/(approve|execute)$/, (route: Route) => {
    const m = route.request().url().match(/\/tasks\/([^/]+)\/(approve|execute)$/)!;
    if (route.request().method() === "POST") {
      state.calls.push(`${m[2]} ${m[1]}`);
      state.tasks = state.tasks.map((t) => (t.id === m[1] ? { ...t, ...(m[2] === "approve" ? { approval_status: "approved" } : { status: "completed" }) } : t));
      if (m[1] === "bad" && m[2] === "execute") return route.fulfill({ status: 409, contentType: "application/json", headers: cors, body: JSON.stringify({ detail: "blocked by the kill switch" }) });
    }
    return json(route, m[2] === "execute" ? { id: `c-${m[1]}`, website_id: SITE, page_id: null, seo_task_id: m[1], connector_type: "sanity", before_state_json: {}, after_state_json: {}, actor_type: "system", executed_at: "2026-11-21T10:00:00Z", validation_status: "passed" } : state.tasks.find((t) => t.id === m[1]));
  });
  return state;
}

test("several approved tasks can be executed in one go, after a single confirmation, one after another", async ({ page }: { page: Page }) => {
  const state = await setup(page, [mk("a", "approved"), mk("b", "approved"), mk("c", "approved")]);
  await page.goto(`/dashboard/websites/${SITE}`);
  await page.getByRole("button", { name: "Tasks", exact: true }).click();
  const bar = page.getByTestId("bulk-bar");
  await expect(bar.getByRole("button", { name: "Execute selected (0)" })).toBeDisabled();
  await bar.getByLabel("Select all (3)").check();
  await bar.getByRole("button", { name: "Execute selected (3)" }).click();
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toContainText("Execute 3 change(s) now?");
  await expect(dialog).toContainText("one after another");
  expect(state.calls).toEqual([]); // nothing runs before the confirmation
  await dialog.getByRole("button", { name: "Confirm" }).click();
  await expect.poll(() => state.calls.length).toBe(3);
  expect(state.calls).toEqual(["execute a", "execute b", "execute c"]);
  await expect(page.getByText("3 of 3 executed.")).toBeVisible();
});

test("a failing task in a bulk run is reported and does not stop the others", async ({ page }: { page: Page }) => {
  const state = await setup(page, [mk("a", "approved"), mk("bad", "approved"), mk("c", "approved")]);
  await page.goto(`/dashboard/websites/${SITE}`);
  await page.getByRole("button", { name: "Tasks", exact: true }).click();
  await page.getByTestId("bulk-bar").getByLabel("Select all (3)").check();
  await page.getByRole("button", { name: "Execute selected (3)" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Confirm" }).click();
  await expect(page.getByText(/2 of 3 executed; 1 failed/)).toBeVisible();
  expect(state.calls).toEqual(["execute a", "execute bad", "execute c"]);
});

test("tasks waiting for approval can be approved in bulk too, and only the selected ones", async ({ page }: { page: Page }) => {
  const state = await setup(page, [mk("a", "pending"), mk("b", "pending"), mk("c", "pending")]);
  await page.goto(`/dashboard/websites/${SITE}`);
  await page.getByRole("button", { name: "Tasks", exact: true }).click();
  await page.getByLabel("Select https://x.example/a").check();
  await page.getByLabel("Select https://x.example/c").check();
  await page.getByRole("button", { name: "Approve selected (2)" }).click();
  await expect(page.getByRole("alertdialog")).toContainText("Approve 2 change(s)?");
  await page.getByRole("alertdialog").getByRole("button", { name: "Confirm" }).click();
  await expect(page.getByText("2 of 2 approved.")).toBeVisible();
  expect(state.calls).toEqual(["approve a", "approve c"]);
});
