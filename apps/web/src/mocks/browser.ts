import { setupWorker } from "msw/browser";
import { fixtureHandlers } from "@/mocks/handlers";

export const worker = setupWorker(...fixtureHandlers);

export function startDemoWorker() {
  return worker.start({ onUnhandledRequest: "error" });
}
