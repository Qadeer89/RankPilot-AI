import { expect, test, type Page, type Route } from "@playwright/test";

const cors = { "access-control-allow-origin": "*" };

async function stubPricing(page: Page, ok = true) {
  // Server-rendered fetches cannot be intercepted by the browser, so these tests assert the page works both ways.
  await page.route("**/api/v1/public/pricing", (r: Route) => r.fulfill({ status: ok ? 200 : 500, headers: cors, contentType: "application/json", body: "{}" }));
}

test("a new visitor sees what the product is, how it works, and can reach login and sign-up", async ({ page }: { page: Page }) => {
  await stubPricing(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("SEO that finds, fixes and proves its own work");
  await expect(page.getByRole("heading", { name: "How it works" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Honest by design" })).toBeVisible();
  await expect(page.getByText("We never promise rankings or traffic")).toBeVisible();
  const nav = page.getByRole("navigation", { name: "Main" });
  for (const name of ["Features", "How it works", "Pricing", "FAQ"]) await expect(nav.getByRole("link", { name })).toBeVisible();
  await expect(page.getByRole("link", { name: "Log in" }).first()).toHaveAttribute("href", "/login");
  await expect(page.getByRole("link", { name: "Get started" })).toHaveAttribute("href", "/register");
  await expect(page.locator("details").first()).toBeVisible();
});

test("a signed-in visitor gets a dashboard link instead of login buttons", async ({ page }: { page: Page }) => {
  await page.addInitScript(() => localStorage.setItem("rankpilot_access_token", "t"));
  await page.goto("/");
  await expect(page.getByRole("link", { name: "Open dashboard" })).toHaveAttribute("href", "/dashboard");
});

test("features, pricing, privacy, terms and contact pages exist and are linked from the footer", async ({ page }: { page: Page }) => {
  await page.goto("/");
  const footer = page.getByRole("contentinfo");
  for (const [name, path, heading] of [["Features", "/features", /Everything you need/], ["Pricing", "/pricing", /Simple pricing/], ["Privacy policy", "/privacy", /Privacy policy/], ["Terms of service", "/terms", /Terms of service/], ["Contact", "/contact", /Contact us/]] as const) {
    await footer.getByRole("link", { name }).click();
    await expect(page).toHaveURL(new RegExp(`${path}$`));
    await expect(page.getByRole("heading", { level: 1 })).toContainText(heading);
  }
});

test("the privacy policy states the Google read-only and limited-use commitments", async ({ page }: { page: Page }) => {
  await page.goto("/privacy");
  await expect(page.getByText("read-only")).toBeVisible();
  await expect(page.getByText(/Limited Use/)).toBeVisible();
  await expect(page.getByRole("link", { name: "Google API Services User Data Policy" })).toBeVisible();
});

test("the home page works on a phone: menu opens, no sideways scroll", async ({ page }: { page: Page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await page.goto("/");
  await page.getByRole("button", { name: "Menu" }).click();
  await expect(page.getByRole("navigation", { name: "Mobile" }).getByRole("link", { name: "Pricing" })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});

test("the dashboard still requires login", async ({ page }: { page: Page }) => {
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/login/);
});
