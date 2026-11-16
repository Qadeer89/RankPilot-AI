import { expect, test } from "@playwright/test";

// The test server runs with NEXT_PUBLIC_APP_ENV unset (= development): it must never invite indexing.
test("a non-production frontend disallows all crawling and marks pages noindex", async ({ page, request }) => {
  const robots = await request.get("/robots.txt");
  expect(await robots.text()).toMatch(/Disallow: \//);
  const sitemap = await request.get("/sitemap.xml");
  expect(await sitemap.text()).not.toContain("<loc>");
  await page.goto("/login");
  await expect(page.locator('meta[name="robots"]')).toHaveAttribute("content", /noindex/);
});
