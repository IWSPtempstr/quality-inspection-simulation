export function safeReturnTo(value: string | null | undefined): string {
  if (!value || !value.startsWith("/") || value.startsWith("//") || value.includes("\\")) return "/";
  return value;
}

export function loginHref(returnTo: string): string {
  return `${apiBaseUrl}/auth/login?return_to=${encodeURIComponent(safeReturnTo(returnTo))}`;
}
import { apiBaseUrl } from "@/api/client";
