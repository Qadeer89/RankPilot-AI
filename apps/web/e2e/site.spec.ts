import { expect, test, type Page } from "@playwright/test";

test("a new visitor sees what the product is, how it works, and can reach sign-up and login", async ({ page }: { page: Page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Turn SEO insights into measurable growth");
  await expect(page.getByText("never guarantees rankings", { exact: false })).toBeVisible();
  await expect(page.getByRole("heading", { name: "How RankPilot works" })).toBeVisible();
  for (const j of ["Discover", "Analyze", "Plan", "Implement", "Validate", "Measure", "Improve"]) await expect(page.getByRole("list", { name: "The RankPilot workflow" }).getByText(j)).toBeVisible();
  const nav = page.getByRole("navigation", { name: "Main" });
  for (const [name, href] of [["Features", "/features"], ["How it works", "/how-it-works"], ["Pricing", "/pricing"], ["FAQ", "/faq"]] as const) await expect(nav.getByRole("link", { name })).toHaveAttribute("href", href);
  await expect(page.getByRole("link", { name: "Log in" }).first()).toHaveAttribute("href", "/login");
  await expect(page.getByRole("link", { name: "Start free" }).first()).toHaveAttribute("href", "/register");
  await expect(page.getByRole("link", { name: "Explore features" })).toHaveAttribute("href", "/features");
  await expect(page.getByRole("heading", { name: "Your next SEO improvement starts here." })).toBeVisible();
});

test("the product screenshots load and are labelled as sample data", async ({ page }: { page: Page }) => {
  await page.goto("/");
  const imgs = page.locator("figure img");
  await expect(imgs).toHaveCount(5);
  await page.locator("figure").last().scrollIntoViewIfNeeded();
  for (let i = 0; i < 5; i++) {
    await imgs.nth(i).scrollIntoViewIfNeeded();
    await expect.poll(() => imgs.nth(i).evaluate((el: HTMLImageElement) => el.complete && el.naturalWidth > 0)).toBe(true);
    await expect(imgs.nth(i)).toHaveAttribute("alt", /.{20,}/);
  }
  await expect(page.getByText("Sample data for a fictional site.").first()).toBeVisible();
});

test("only real integrations are listed, and Shopify is labelled beta", async ({ page }: { page: Page }) => {
  await page.goto("/");
  const section = page.getByRole("region", { name: "Connects to what you already use" });
  for (const n of ["Google Search Console", "Google Analytics 4", "WordPress", "Webflow", "Sanity", "GitHub", "Shopify", "Slack"]) await expect(section.locator("strong", { hasText: n })).toBeVisible();
  await expect(section.getByText("Beta")).toHaveCount(1);
});

test("a signed-in visitor gets a dashboard link instead of login buttons", async ({ page }: { page: Page }) => {
  await page.addInitScript(() => localStorage.setItem("rankpilot_access_token", "t"));
  await page.goto("/");
  await expect(page.getByRole("link", { name: "Open dashboard" })).toHaveAttribute("href", "/dashboard");
});

test("every public page exists, has one h1 and a canonical + social metadata, and is linked from the footer", async ({ page }: { page: Page }) => {
  const pages: [string, string, RegExp][] = [["/features", "Features", /Everything you need/], ["/how-it-works", "How it works", /From a website address/], ["/pricing", "Pricing", /Pricing/], ["/faq", "FAQ", /Frequently asked/], ["/about", "About", /show their working/], ["/contact", "Contact", /Contact us/], ["/privacy", "Privacy policy", /Privacy policy/], ["/terms", "Terms of service", /Terms of service/]];
  await page.goto("/");
  const footer = page.getByRole("contentinfo");
  for (const [path, name, heading] of pages) {
    await footer.getByRole("link", { name, exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`${path}$`));
    await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
    await expect(page.getByRole("heading", { level: 1 })).toContainText(heading);
    await page.goto(path); // a fresh load, so only this page's own tags are present
    await expect(page.locator('link[rel="canonical"]')).toHaveCount(1);
    await expect(page.locator('link[rel="canonical"]')).toHaveAttribute("href", new RegExp(`${path}$`));
    await expect(page.locator('meta[property="og:title"]')).toHaveAttribute("content", /RankPilot AI|SEO|Pricing|Privacy|Terms|Contact|features|FAQ|questions|about|works/i);
    await expect(page.locator('meta[name="twitter:card"]')).toHaveAttribute("content", "summary_large_image");
    await expect(page.locator('meta[name="description"]')).toHaveAttribute("content", /.{40,}/);
  }
});

test("pricing never shows a price that has not been approved, and says so plainly", async ({ page }: { page: Page }) => {
  await page.goto("/pricing");
  await expect(page.getByText("Pricing is being finalized.")).toBeVisible();
  await expect(page.getByText("Create an account to explore RankPilot.")).toBeVisible();
  await expect(page.getByRole("link", { name: "Create an account" }).first()).toHaveAttribute("href", "/register");
  expect(await page.locator("main").innerText()).not.toMatch(/\$\d/);
  // no trial or payment promises appear before a plan is approved
  await expect(page.getByText("A payment method is collected when you start a trial", { exact: false })).toHaveCount(0);
});

test("the privacy policy states the Google read-only and limited-use commitments", async ({ page }: { page: Page }) => {
  await page.goto("/privacy");
  await expect(page.getByText("read-only").first()).toBeVisible();
  await expect(page.getByText(/Limited Use/)).toBeVisible();
  await expect(page.getByRole("link", { name: "Google API Services User Data Policy" })).toBeVisible();
});

test("robots.txt and sitemap.xml are served, and account pages are not indexable", async ({ page, request }: { page: Page; request: import("@playwright/test").APIRequestContext }) => {
  const robots = await request.get("/robots.txt");
  expect(robots.ok()).toBe(true);
  const sitemap = await request.get("/sitemap.xml");
  expect(sitemap.ok()).toBe(true);
  // the test server is a non-production environment, so its sitemap is empty (see environment.spec.ts); production lists the pages
  expect(await sitemap.text()).toContain("urlset");
  for (const p of ["/login", "/register"]) {
    await page.goto(p);
    await expect(page.locator('meta[name="robots"]')).toHaveAttribute("content", /noindex/);
  }
});

test("structured data on the home page has no ratings or reviews", async ({ page }: { page: Page }) => {
  await page.goto("/");
  const json = await page.locator('script[type="application/ld+json"]').first().textContent();
  expect(json).toContain("SoftwareApplication");
  expect(json).not.toMatch(/aggregateRating|review|ratingValue/i);
});

test("the home page works on a phone: menu opens, no sideways scroll", async ({ page }: { page: Page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await page.goto("/");
  await page.getByRole("button", { name: "Menu" }).click();
  await expect(page.getByRole("navigation", { name: "Mobile" }).getByRole("link", { name: "Pricing" })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});

test("the pages hold together on a tablet width too", async ({ page }: { page: Page }) => {
  await page.setViewportSize({ width: 820, height: 1000 });
  for (const p of ["/", "/features", "/pricing", "/how-it-works"]) {
    await page.goto(p);
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
  }
});

test("the dashboard still requires login", async ({ page }: { page: Page }) => {
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/login/);
});

test("keyboard users can skip to the content", async ({ page }: { page: Page }) => {
  await page.goto("/");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to content" })).toBeFocused();
});
