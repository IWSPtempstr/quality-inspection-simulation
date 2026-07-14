import { defineConfig } from "@playwright/test";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const testDirectory = dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  testDir: testDirectory,
  testMatch: "demo-acceptance.e2e.ts",
  timeout: 30_000,
  use: { baseURL: "http://127.0.0.1:5174", browserName: "chromium", viewport: { width: 1280, height: 800 } },
  webServer: {
    command: "env -u npm_config_prefix ./scripts/with-toolchain.sh npm run dev:demo -- --host 127.0.0.1 --port 5174",
    cwd: resolve(testDirectory, ".."),
    port: 5174,
    reuseExistingServer: true,
  },
});
