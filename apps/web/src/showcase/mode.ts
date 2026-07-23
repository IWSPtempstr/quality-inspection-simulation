export function isPublicShowcase(): boolean {
  return import.meta.env.VITE_PUBLIC_SHOWCASE === "true";
}
