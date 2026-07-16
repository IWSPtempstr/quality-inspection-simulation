import { setupServer } from "msw/node";
import { fixtureHandlers } from "@/mocks/handlers";

export const server = setupServer(...fixtureHandlers);
