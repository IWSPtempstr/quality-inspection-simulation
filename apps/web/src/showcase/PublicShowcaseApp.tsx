import { RouterProvider } from "react-router-dom";
import { router } from "@/app/router";

export const SHOWCASE_WORKBENCH_ROUTES = ["/", "/orders", "/resources", "/scheduling", "/execution", "/events", "/knowledge", "/notifications", "/admin/audit", "/admin/system"] as const;

export function PublicShowcaseApp() {
  return <RouterProvider router={router} />;
}
