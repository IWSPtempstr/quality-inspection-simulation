import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@/styles/global.css";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

async function bootstrap() {
  if (import.meta.env.DEV && import.meta.env.VITE_DEMO_MODE === "true") {
    const { startDemoWorker } = await import("@/mocks/browser");
    await startDemoWorker();
  }
  const { RouterProvider } = await import("react-router-dom");
  const { router } = await import("@/app/router");

  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </StrictMode>,
  );
}

void bootstrap();
