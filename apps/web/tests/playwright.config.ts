import { defineConfig } from "@playwright/test";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const testDirectory = dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  testDir: testDirectory,
  testMatch: "**/frontend-gate.e2e.ts",
  timeout: 30_000,
  fullyParallel: false,
  use: {
    baseURL: "http://127.0.0.1:4173",
    browserName: "chromium",
    viewport: { width: 1280, height: 800 },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  outputDir: resolve(testDirectory, "artifacts"),
  webServer: {
    command: "env -u npm_config_prefix ./scripts/with-toolchain.sh npm run dev -- --host 127.0.0.1 --port 4173",
    cwd: resolve(testDirectory, ".."),
    port: 4173,
    reuseExistingServer: false,
  },
});
