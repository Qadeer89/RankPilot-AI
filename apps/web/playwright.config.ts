import { defineConfig, devices } from "@playwright/test";

// UI tests for the SEO Growth Engine screens. They run the real Next.js app
// in a real browser against a scripted fake API (e2e/support/fakeApi.ts), so
// they need no backend or database and are deterministic. They test the
// frontend's behaviour; they do NOT test the backend or any real provider.
const PORT = Number(process.env.E2E_PORT ?? 3100);

export default defineConfig({
  testDir: "./e2e",
  timeout: 45_000,
  expect: { timeout: 8_000 },
  fullyParallel: true,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: `http://localhost:${PORT}`,
    trace: "off",
    ...devices["Desktop Chrome"],
    viewport: { width: 1300, height: 1000 },
  },
  webServer: {
    command: `npm run dev -- -p ${PORT}`,
    url: `http://localhost:${PORT}/login`,
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
