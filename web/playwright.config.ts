import { defineConfig, devices } from "@playwright/test";

// End-to-end: the real API and the built app, with a fake network (tests/e2e_server.py).
// Build first: `pnpm build`. Nothing here touches the internet.
const PORT = 8799;

export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: "retain-on-failure",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", use: { ...devices["Pixel 7"] } },
  ],
  webServer: {
    command: `cd .. && uv run python -m tests.e2e_server --port ${PORT}`,
    url: `http://127.0.0.1:${PORT}/api/options`,
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
