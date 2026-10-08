/**
 * Validates the `?next=` value used after login. Only same-site paths are allowed, so a crafted
 * link cannot send someone to another site once they have logged in (an "open redirect").
 */
export function safeNext(value: string | string[] | undefined): string | null {
  if (typeof value !== "string") return null;
  if (value.length === 0 || value.length > 200) return null;
  if (!value.startsWith("/") || value.startsWith("//")) return null;
  if (value.includes("\\") || /[\u0000-\u001f\u007f]/.test(value)) return null;
  if (value === "/login" || value.startsWith("/login?")) return null;
  return value;
}
