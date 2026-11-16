import { expect, test, type Page, type Route } from "@playwright/test";

type Json = Record<string, unknown>;

const OVERVIEW = {
  range: { start: "2026-10-18T00:00:00Z", end: "2026-11-17T00:00:00Z" },
  users: { total: 12, new: 3, active: 11, suspended: 1 },
  projects: { total: 10, subscribed: 6, unsubscribed: 4, suspended: 0 },
  subscriptions: { by_status: { active: 3, past_due: 1, trialing: 1 }, by_interval_live: { month: 3, year: 2 }, total: 5, complimentary: 1 },
  revenue: {
    gross_collected_cents: { USD: 19500 }, refunds_cents: { USD: 1500 }, net_cents: { USD: 18000 }, new_subscription_revenue_cents: { USD: 16500 },
    failed_payments: { count: 1, amount_cents: { USD: 1500 } }, recovered_payments: 0,
    recurring: { mrr_cents: { USD: 4250 }, arr_cents: { USD: 51000 }, past_due_mrr_cents: { USD: 1500 }, paying_subscriptions: 3 },
  },
  trials: { started: 4, active: 1, conversion_rate: 0.6667 },
  replacements: { total: 2, admin_overrides: 1 },
};

const USERS = (q: string) => {
  const all = [
    { id: "u-1", email: "alice@example.com", status: "active", email_verified: true, created_at: "2026-10-01T00:00:00Z", workspaces: 1, projects: 2 },
    { id: "u-2", email: "bob@example.com", status: "disabled", email_verified: false, created_at: "2026-10-02T00:00:00Z", workspaces: 1, projects: 0 },
  ];
  const items = all.filter((u) => u.email.includes(q));
  return { items, page: 1, page_size: 25, total: items.length, pages: 1 };
};

class FakeAdmin {
  calls: { method: string; path: string; query: URLSearchParams; body: Json | null }[] = [];
  user: Json = { id: "a1", email: "qaqadeer@gmail.com", is_platform_admin: true, is_super_admin: true, email_verified: true };
  actionError: { status: number; detail: Json } | null = null;
  usersDown = false;
  revenue = {
    gross_collected_cents: { USD: 19500 }, refunds_cents: { USD: 1500 }, net_cents: { USD: 18000 }, new_subscription_revenue_cents: { USD: 16500 },
    by_interval_cents: { month: { USD: 4500 }, year: { USD: 15000 } }, failed_payments: { count: 1, amount_cents: { USD: 1500 } }, recovered_payments: 0,
    churn: { cancelled: 1, base: 4, rate: 0.25 }, series: [{ date: "2026-11-15", collected_cents: { USD: 1500 } }, { date: "2026-11-16", collected_cents: { USD: 18000 } }],
    recurring: { mrr_cents: { USD: 4250 }, arr_cents: { USD: 51000 }, past_due_mrr_cents: { USD: 1500 }, paying_subscriptions: 3 },
  };

  requests(method: string, part: string) {
    return this.calls.filter((c) => c.method === method && c.path.includes(part));
  }

  async install(page: Page) {
    await page.addInitScript(() => localStorage.setItem("rankpilot_access_token", "test-token"));
    await page.route("**/api/v1/**", (route) => this.handle(route));
  }

  private json(route: Route, body: unknown, status = 200) {
    return route.fulfill({ status, contentType: "application/json", headers: { "access-control-allow-origin": "*", "access-control-allow-headers": "*", "access-control-allow-methods": "*" }, body: JSON.stringify(body) });
  }

  private async handle(route: Route) {
    const req = route.request();
    const url = new URL(req.url());
    const method = req.method();
    if (method === "OPTIONS") return this.json(route, {}, 204);
    let body: Json | null = null;
    try { body = req.postDataJSON() as Json | null; } catch { body = null; }
    this.calls.push({ method, path: url.pathname, query: url.searchParams, body });
    const p = url.pathname;
    if (p.endsWith("/me")) return this.json(route, { user: this.user, organizations: [{ id: "o1", name: "Org", slug: "org", role: "owner" }] });
    if (p.endsWith("/auth/send-verification-email")) return this.json(route, { message: "Verification email sent." });
    if (!p.includes("/admin/")) return this.json(route, { detail: `fake: unhandled ${p}` }, 404);
    if (method !== "GET") {
      if (this.actionError) return this.json(route, { detail: this.actionError.detail }, this.actionError.status);
      return this.json(route, { ok: true });
    }
    if (p.endsWith("/admin/overview")) return this.json(route, OVERVIEW);
    if (p.endsWith("/admin/users")) {
      if (this.usersDown) {
        return this.json(route, { detail: "Database unavailable" }, 500);
      }
      return this.json(route, USERS(url.searchParams.get("q") ?? ""));
    }
    if (p.endsWith("/admin/revenue")) return this.json(route, this.revenue);
    if (p.endsWith("/admin/ai-costs")) return this.json(route, { cost_basis: "estimated", runs: 0, failed_runs: 0, input_tokens: 0, output_tokens: 0, estimated_cost_usd: 0, by_project: [], by_model: [], daily: [], daily_warning_usd: 50 });
    if (p.endsWith("/admin/health")) return this.json(route, { overall: "warning", checked_at: "2026-11-16T10:00:00Z", checks: [{ name: "database", state: "ok", detail: "Query succeeded." }, { name: "billing_webhooks", state: "warning", detail: "1 failed event(s) awaiting retry." }] });
    if (p.endsWith("/admin/settings")) return this.json(route, { items: [{ key: "price_monthly_cents", label: "Monthly price (cents)", description: "Displayed for NEW checkouts.", sensitive: true, value: 1500, default: 1500, source: "environment" }], notes: ["Prices only affect NEW checkouts."] });
    return this.json(route, { items: [], page: 1, page_size: 25, total: 0, pages: 1 });
  }
}

async function open(page: Page, fake: FakeAdmin, tab = "") {
  await fake.install(page);
  await page.goto(`/dashboard/admin${tab ? `?tab=${tab}` : ""}`);
}

test("a regular user sees no admin data and the page makes no admin requests", async ({ page }) => {
  const fake = new FakeAdmin();
  fake.user = { id: "u9", email: "someone@example.com", is_platform_admin: false, is_super_admin: false, email_verified: true };
  await open(page, fake);
  await expect(page.getByTestId("not-authorised")).toBeVisible();
  expect(fake.calls.filter((c) => c.path.includes("/admin/"))).toHaveLength(0);
  await expect(page.getByRole("link", { name: "Admin Dashboard" })).toHaveCount(0);
});

test("an unverified Super Admin is asked to verify their email", async ({ page }) => {
  const fake = new FakeAdmin();
  fake.user = { id: "a1", email: "qaqadeer@gmail.com", is_platform_admin: true, is_super_admin: false, email_verified: false };
  await open(page, fake);
  await page.getByRole("button", { name: "Send verification email" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Verification email sent." })).toBeVisible();
  expect(fake.calls.filter((c) => c.path.includes("/admin/"))).toHaveLength(0);
});

test("the overview shows recurring revenue and cash collected as separate figures", async ({ page }) => {
  const fake = new FakeAdmin();
  await open(page, fake);
  const region = page.getByRole("region", { name: "Overview" });
  await expect(region.getByText("$42.50", { exact: true })).toBeVisible(); // MRR
  await expect(region.getByText("$510", { exact: true })).toBeVisible(); // ARR
  await expect(region.getByText("$195", { exact: true })).toBeVisible(); // gross cash
  await expect(region.getByText("$180", { exact: true })).toBeVisible(); // net
  await expect(region.getByText("Cash, not MRR")).toBeVisible();
  await expect(region.getByText("66.7%")).toBeVisible();
  await expect(page.getByRole("link", { name: "Admin Dashboard" })).toBeVisible();
});

test("changing the period asks the server for that period", async ({ page }) => {
  const fake = new FakeAdmin();
  await open(page, fake);
  await expect(page.getByRole("region", { name: "Overview" }).getByText("Total users")).toBeVisible();
  await page.getByLabel("Period").selectOption("custom");
  await page.getByLabel("From", { exact: true }).fill("2026-10-01");
  await page.getByLabel("To", { exact: true }).fill("2026-10-31");
  await expect.poll(() => fake.requests("GET", "/admin/overview").some((c) => c.query.get("range") === "custom" && c.query.get("start") === "2026-10-01" && c.query.get("end") === "2026-10-31")).toBe(true);
});

test("user search is sent to the server and an empty result is explained", async ({ page }) => {
  const fake = new FakeAdmin();
  await open(page, fake, "users");
  await expect(page.getByText("alice@example.com")).toBeVisible();
  await page.getByLabel("Search email").fill("zzz");
  await expect(page.getByTestId("state-empty")).toBeVisible();
  expect(fake.requests("GET", "/admin/users").some((c) => c.query.get("q") === "zzz")).toBe(true);
});

test("a failed load shows an error with a working retry", async ({ page }) => {
  const fake = new FakeAdmin();
  fake.usersDown = true;
  await open(page, fake, "users");
  await expect(page.getByTestId("state-error")).toContainText("Database unavailable");
  fake.usersDown = false;
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByText("alice@example.com")).toBeVisible();
});

test("suspending a user needs a reason and a confirmation, then reports to the server", async ({ page }) => {
  const fake = new FakeAdmin();
  await open(page, fake, "users");
  await page.getByRole("row", { name: /alice@example.com/ }).getByRole("button", { name: "Suspend" }).click();
  const dialog = page.getByRole("dialog", { name: /Suspend alice/ });
  const submit = dialog.getByRole("button", { name: "Suspend user" });
  await expect(submit).toBeDisabled();
  await dialog.getByLabel(/Reason/).fill("abuse report #42");
  await expect(submit).toBeDisabled(); // still needs the confirmation
  await dialog.getByLabel(/I understand and confirm/).check();
  await submit.click();
  await expect(dialog).toBeHidden();
  const [call] = fake.requests("POST", "/admin/users/u-1/suspend");
  expect(call.body).toEqual({ reason: "abuse report #42", confirm: true });
});

test("a refused action keeps the dialog open and shows why", async ({ page }) => {
  const fake = new FakeAdmin();
  fake.actionError = { status: 409, detail: { code: "cannot_suspend_self", message: "The Super Admin account cannot be suspended from the dashboard." } };
  await open(page, fake, "users");
  await page.getByRole("row", { name: /alice@example.com/ }).getByRole("button", { name: "Suspend" }).click();
  const dialog = page.getByRole("dialog", { name: /Suspend alice/ });
  await dialog.getByLabel(/Reason/).fill("test");
  await dialog.getByLabel(/I understand and confirm/).check();
  await dialog.getByRole("button", { name: "Suspend user" }).click();
  await expect(dialog.getByTestId("dialog-error")).toContainText("cannot be suspended");
  await expect(dialog).toBeVisible();
});

test("revenue analytics lists MRR, ARR, churn and charts daily cash", async ({ page }) => {
  const fake = new FakeAdmin();
  await open(page, fake, "revenue");
  const region = page.getByRole("region", { name: "Revenue analytics" });
  await expect(region.getByText("$42.50", { exact: true })).toBeVisible();
  await expect(region.getByText("25.0%")).toBeVisible();
  await expect(region.getByRole("img", { name: /Daily cash collected in USD/ })).toBeVisible();
});

test("a setting change sends the new value with its reason", async ({ page }) => {
  const fake = new FakeAdmin();
  await open(page, fake, "settings");
  await expect(page.getByText("Prices only affect NEW checkouts.")).toBeVisible();
  await page.getByRole("button", { name: "Change" }).click();
  const dialog = page.getByRole("dialog", { name: /Change Monthly price/ });
  await dialog.getByLabel("New value").fill("1900");
  await dialog.getByLabel(/Reason/).fill("pricing experiment");
  await dialog.getByLabel(/I understand and confirm/).check();
  await dialog.getByRole("button", { name: "Save change" }).click();
  const [call] = fake.requests("PUT", "/admin/settings/price_monthly_cents");
  expect(call.body).toEqual({ reason: "pricing experiment", confirm: true, value: 1900 });
});

test("system health shows each check and its state", async ({ page }) => {
  const fake = new FakeAdmin();
  await open(page, fake, "health");
  const region = page.getByRole("region", { name: "System health" });
  await expect(region.getByRole("row", { name: /billing webhooks.*warning/ })).toBeVisible();
  await expect(region.getByRole("row", { name: /database.*ok/ })).toBeVisible();
});
