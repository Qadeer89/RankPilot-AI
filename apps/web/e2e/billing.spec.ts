import { expect, test, type Page, type Route } from "@playwright/test";

const ORG = "00000000-0000-4000-8000-000000000001";
const A = "00000000-0000-4000-8000-0000000000a1";
const B = "00000000-0000-4000-8000-0000000000b2";
const C = "00000000-0000-4000-8000-0000000000c3";
const base = `/api/v1/organizations/${ORG}`;

type Json = Record<string, unknown>;

const PLANS = [
  { interval: "month", price_cents: 1500, currency: "USD", trial_days: 7, monthly_equivalent_cents: 1500 },
  { interval: "year", price_cents: 15000, currency: "USD", trial_days: 7, monthly_equivalent_cents: 1250 },
];

function project(id: string, name: string, over: Json = {}): Json {
  return {
    website_id: id, display_name: name, hostname: `${name.toLowerCase().replace(/\s/g, "")}.example`, target_countries: ["PK", "GB"],
    entitlement: { entitled: false, reason: "no_subscription", message: "This project has no subscription. Start a plan to use paid features.", until: null },
    subscription: null, payments: [], can_start_plan: true, trial_available: true, ...over,
  };
}

function subscription(over: Json = {}): Json {
  return {
    id: "sub-1", status: "active", provider: "lemonsqueezy", complimentary: false, interval: "month", price_cents: 1500, currency: "USD",
    trial_started_at: null, trial_ends_at: null, renews_at: "2026-12-16T00:00:00Z", ends_at: null, cancelled_at: null,
    cancellation_scheduled: false, grace_ends_at: null, replacements_used: 0, replacement_limit: 1, replacements_remaining: 1,
    customer_portal_url: "https://store.example/portal", update_payment_url: "https://store.example/pm", ...over,
  };
}

function entitled(reason = "active", message = "Subscription active."): Json {
  return { entitled: true, reason, message, until: null };
}

class FakeBilling {
  calls: { method: string; path: string; body: Json | null }[] = [];
  overview: Json;
  checkoutStatus = 200;
  replaceResult: { status: number; body: Json } = { status: 200, body: { subscription_id: "sub-1", website_id: B, replacements_remaining: 0, sequence: 1 } };
  overviewStatus = 200;
  targets = { replacements_remaining: 1, targets: [{ id: B, display_name: "Beta Site", hostname: "beta.example" }] };
  onOverview: (() => void) | null = null;

  constructor(projects: Json[], enforcement = "off") {
    this.overview = { enforcement, plans: PLANS, annual_saving_cents: 3000, projects };
  }

  requests(method: string, part: string) {
    return this.calls.filter((c) => c.method === method && c.path.includes(part));
  }

  async install(page: Page) {
    await page.addInitScript(() => localStorage.setItem("rankpilot_access_token", "test-token"));
    await page.route("**/mock-checkout**", (route) => route.fulfill({ status: 200, contentType: "text/html", body: "<h1>Payment page</h1>" }));
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
    this.calls.push({ method, path: url.pathname, body });
    const p = url.pathname;
    if (p.endsWith("/me")) return this.json(route, { user: { id: "u1", email: "owner@example.com", is_platform_admin: false }, organizations: [{ id: ORG, name: "Org", slug: "org", role: "owner" }] });
    if (p === `${base}/billing/overview`) {
      this.onOverview?.();
      if (this.overviewStatus !== 200) return this.json(route, { detail: "Tenant access denied" }, this.overviewStatus);
      return this.json(route, this.overview);
    }
    if (method === "POST" && p.endsWith("/billing/checkout")) {
      if (this.checkoutStatus !== 200) return this.json(route, { detail: { code: "provider_error", message: "The payment provider could not start a checkout. Try again shortly." } }, this.checkoutStatus);
      const interval = (body?.interval as string) ?? "month";
      return this.json(route, { checkout_url: `http://localhost:3100/mock-checkout?i=${interval}`, interval, price_cents: interval === "month" ? 1500 : 15000, currency: "USD", with_trial: true, trial_days: 7, first_charge_at: null, expires_at: null });
    }
    if (method === "GET" && p.endsWith("/replacement-targets")) return this.json(route, this.targets);
    if (method === "POST" && p.endsWith("/replace-project")) return this.json(route, this.replaceResult.body, this.replaceResult.status);
    return this.json(route, { detail: `fake: unhandled ${method} ${p}` }, 404);
  }
}

async function open(page: Page, fake: FakeBilling, query = "") {
  await fake.install(page);
  await page.goto(`/dashboard/billing${query}`);
  await expect(page.getByRole("heading", { name: "Billing", exact: true })).toBeVisible();
}

test("an unsubscribed project explains the trial and the price before checkout", async ({ page }) => {
  const fake = new FakeBilling([project(A, "Alpha Site")]);
  await open(page, fake);

  const card = page.getByRole("region", { name: "Billing for Alpha Site" });
  await expect(card.getByText("No plan")).toBeVisible();
  const summary = card.getByTestId("checkout-summary");
  // annual is preselected
  await expect(summary).toContainText("7-day free trial");
  await expect(summary).toContainText("$150 / year");
  await expect(summary).toContainText("Cancel any time");
  await expect(summary).toContainText("Includes every target country");
  await expect(card.getByText("$12.50 a month. Save $30 a year: 2 months free.")).toBeVisible();

  await card.getByRole("radio", { name: /Monthly/ }).click();
  await expect(summary).toContainText("$15 / month");
});

test("starting the trial sends only the plan choice and goes to the payment page", async ({ page }) => {
  const fake = new FakeBilling([project(A, "Alpha Site")]);
  await open(page, fake);
  const card = page.getByRole("region", { name: "Billing for Alpha Site" });
  await card.getByRole("radio", { name: /Monthly/ }).click();
  await card.getByRole("button", { name: "Start free trial" }).click();

  await expect(page.getByRole("heading", { name: "Payment page" })).toBeVisible();
  expect(page.url()).toContain("/mock-checkout?i=month");
  const [call] = fake.requests("POST", "/billing/checkout");
  expect(call.path).toContain(`/websites/${A}/`);
  expect(call.body).toEqual({ interval: "month" }); // no price, no variant
});

test("a failed checkout start shows why and stays on the page", async ({ page }) => {
  const fake = new FakeBilling([project(A, "Alpha Site")]);
  fake.checkoutStatus = 502;
  await open(page, fake);
  await page.getByRole("button", { name: "Start free trial" }).click();
  await expect(page.locator('p[role="alert"]')).toContainText("payment provider could not start a checkout");
  await expect(page.getByRole("button", { name: "Start free trial" })).toBeEnabled();
});

test("a project that already had its trial is not offered another", async ({ page }) => {
  const fake = new FakeBilling([project(A, "Alpha Site", { trial_available: false })]);
  await open(page, fake);
  const card = page.getByRole("region", { name: "Billing for Alpha Site" });
  await expect(card.getByTestId("checkout-summary")).toContainText("already used its free trial");
  await expect(card.getByRole("button", { name: "Start free trial" })).toHaveCount(0);
  await expect(card.getByRole("button", { name: "Subscribe annual" })).toBeVisible();
});

test("each project shows its own independent subscription", async ({ page }) => {
  const fake = new FakeBilling([
    project(A, "Alpha Site", { entitlement: entitled(), can_start_plan: false,
      subscription: subscription(), payments: [{ id: "p1", amount_cents: 1500, currency: "USD", status: "paid", refunded_cents: 0, billing_reason: "initial", paid_at: "2026-11-16T00:00:00Z", created_at: null }] }),
    project(B, "Beta Site", { entitlement: entitled("trial", "Free trial active."), can_start_plan: false,
      subscription: subscription({ id: "sub-2", status: "trialing", interval: "year", price_cents: 15000, trial_ends_at: "2026-11-23T00:00:00Z", renews_at: "2026-11-23T00:00:00Z" }) }),
    project(C, "Gamma Site"),
  ]);
  await open(page, fake);

  const a = page.getByRole("region", { name: "Billing for Alpha Site" });
  await expect(a.getByText("Monthly · $15 / month")).toBeVisible();
  await expect(a.getByText("Active", { exact: true })).toBeVisible();
  await expect(a.getByRole("link", { name: "Manage billing" })).toHaveAttribute("href", "https://store.example/portal");
  await expect(a.getByRole("table", { name: "Payments for Alpha Site" })).toContainText("$15");

  const b = page.getByRole("region", { name: "Billing for Beta Site" });
  await expect(b.getByText("Annual · $150 / year")).toBeVisible();
  await expect(b.getByText("Free trial", { exact: true })).toBeVisible();
  await expect(b.getByText("Trial ends")).toBeVisible();
  await expect(b.getByText("First charge")).toBeVisible();

  const c = page.getByRole("region", { name: "Billing for Gamma Site" });
  await expect(c.getByText("No plan")).toBeVisible();
  await expect(c.getByRole("link", { name: "Manage billing" })).toHaveCount(0);
});

test("a cancelled subscription says access continues until the end date", async ({ page }) => {
  const fake = new FakeBilling([project(A, "Alpha Site", {
    entitlement: entitled("cancelled_until_end", "Subscription cancelled; access continues until the end of the paid period."), can_start_plan: false,
    subscription: subscription({ status: "cancelled", cancellation_scheduled: true, ends_at: "2026-12-01T00:00:00Z" }),
  })]);
  await open(page, fake);
  const card = page.getByRole("region", { name: "Billing for Alpha Site" });
  await expect(card.getByText("Cancelled, access until")).toBeVisible();
  await expect(card.getByText("Dec 1, 2026")).toBeVisible();
  await expect(card.getByText("Next billing")).toHaveCount(0);
});

test("a past-due subscription offers to update the payment method", async ({ page }) => {
  const fake = new FakeBilling([project(A, "Alpha Site", {
    entitlement: entitled("grace_period", "Payment failed; access continues while payment is retried."), can_start_plan: false,
    subscription: subscription({ status: "past_due" }),
  })]);
  await open(page, fake);
  await expect(page.getByRole("link", { name: "Update payment method" })).toHaveAttribute("href", "https://store.example/pm");
  await expect(page.getByText("Payment past due")).toBeVisible();
});

test("replacing the project needs a target and two confirmations, then shows the allowance used", async ({ page }) => {
  const fake = new FakeBilling([
    project(A, "Alpha Site", { entitlement: entitled(), can_start_plan: false, subscription: subscription() }),
    project(B, "Beta Site"),
  ]);
  await open(page, fake);
  await page.getByRole("button", { name: "Replace project" }).click();

  const dialog = page.getByRole("dialog", { name: "Replace project" });
  await expect(dialog).toContainText("can be done once per subscription and cannot be undone");
  const submit = dialog.getByRole("button", { name: "Replace project" });
  await expect(submit).toBeDisabled();
  await dialog.getByLabel("New project").selectOption(B);
  await expect(submit).toBeDisabled();
  await dialog.getByLabel(/I understand this replacement is permanent/).check();
  await expect(submit).toBeDisabled(); // still needs the second confirmation
  await dialog.getByLabel(/Move the subscription from/).check();
  await expect(submit).toBeEnabled();

  fake.overview = { ...fake.overview, projects: [
    project(A, "Alpha Site"),
    project(B, "Beta Site", { entitlement: entitled(), can_start_plan: false, subscription: subscription({ replacements_used: 1, replacements_remaining: 0 }) }),
  ] };
  await submit.click();

  await expect(page.getByRole("status").filter({ hasText: "one-time replacement has been used" })).toBeVisible();
  const [call] = fake.requests("POST", "/replace-project");
  expect(call.body).toEqual({ target_website_id: B, confirm: true, acknowledge_permanent: true });
  const beta = page.getByRole("region", { name: "Billing for Beta Site" });
  await expect(beta.getByText("Used", { exact: true })).toBeVisible();
  await expect(beta.getByRole("button", { name: "Replace project" })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Billing for Alpha Site" }).getByText("No plan")).toBeVisible();
});

test("a refused replacement shows the reason and changes nothing", async ({ page }) => {
  const fake = new FakeBilling([project(A, "Alpha Site", { entitlement: entitled(), can_start_plan: false, subscription: subscription() })]);
  fake.replaceResult = { status: 409, body: { detail: { code: "replacement_exhausted", message: "This subscription's one-time project replacement has already been used. Contact support if you need an exception." } } };
  await open(page, fake);
  await page.getByRole("button", { name: "Replace project" }).click();
  const dialog = page.getByRole("dialog", { name: "Replace project" });
  await dialog.getByLabel("New project").selectOption(B);
  await dialog.getByLabel(/I understand/).check();
  await dialog.getByLabel(/Move the subscription from/).check();
  await dialog.getByRole("button", { name: "Replace project" }).click();
  await expect(dialog.getByRole("alert")).toContainText("already been used");
  await expect(dialog).toBeVisible();
});

test("with no free project to move to, the dialog says so", async ({ page }) => {
  const fake = new FakeBilling([project(A, "Alpha Site", { entitlement: entitled(), can_start_plan: false, subscription: subscription() })]);
  fake.targets = { replacements_remaining: 1, targets: [] };
  await open(page, fake);
  await page.getByRole("button", { name: "Replace project" }).click();
  await expect(page.getByRole("dialog")).toContainText("no other project in this workspace without its own subscription");
});

test("returning from checkout waits for the verified confirmation instead of trusting the redirect", async ({ page }) => {
  await page.clock.install();
  const fake = new FakeBilling([project(A, "Alpha Site")]);
  await open(page, fake, `?checkout=return&project=${A}`);

  await expect(page.getByText("Confirming your payment with the payment provider")).toBeVisible();
  await expect(page.getByRole("region", { name: "Billing for Alpha Site" }).getByText("No plan")).toBeVisible(); // nothing unlocked by the redirect alone

  fake.overview = { ...fake.overview, projects: [project(A, "Alpha Site", { entitlement: entitled("trial", "Free trial active."), can_start_plan: false,
    subscription: subscription({ status: "trialing", trial_ends_at: "2026-11-23T00:00:00Z" }) })] };
  await page.clock.fastForward(3500);

  await expect(page.getByText("Your subscription is confirmed.")).toBeVisible();
  await expect(page.getByText("Confirming your payment with the payment provider")).toHaveCount(0);
});

test("if the confirmation never arrives the page says so rather than waiting forever", async ({ page }) => {
  await page.clock.install();
  const fake = new FakeBilling([project(A, "Alpha Site")]);
  await open(page, fake, `?checkout=return&project=${A}`);
  await expect(page.getByRole("region", { name: "Billing for Alpha Site" })).toBeVisible(); // loaded, so polling has started
  await page.clock.runFor(70_000); // runs every poll, not just the first
  await expect(page.getByText("We have not received the payment confirmation yet")).toBeVisible();
});

test("the enforcement notice only appears while billing is not enforced", async ({ page }) => {
  await new FakeBilling([project(A, "Alpha Site")], "off").install(page);
  await page.goto("/dashboard/billing");
  await expect(page.getByText("Billing is not enforced yet")).toBeVisible();

  const enforced = await page.context().newPage();
  await new FakeBilling([project(A, "Alpha Site")], "enforce").install(enforced);
  await enforced.goto("/dashboard/billing");
  await expect(enforced.getByRole("heading", { name: "Billing", exact: true })).toBeVisible();
  await expect(enforced.getByText("Billing is not enforced yet")).toHaveCount(0);
});

test("someone without billing access sees the refusal, not billing data", async ({ page }) => {
  const fake = new FakeBilling([project(A, "Alpha Site")]);
  fake.overviewStatus = 403;
  await open(page, fake);
  await expect(page.locator('p[role="alert"]')).toContainText("Tenant access denied");
  await expect(page.getByRole("region", { name: /Billing for/ })).toHaveCount(0);
});
