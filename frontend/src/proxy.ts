import { type NextRequest, NextResponse } from "next/server";

// Runs before every page (not the API, which is proxied to FastAPI and sets its own headers):
//  1. a visitor without a session cookie who asks for a protected page gets a real redirect to the
//     login page instead of a flash of the loading screen. It only checks that a cookie exists; the
//     pages and the API decide whether it is valid and what the role may see.
//  2. every page gets a Content-Security-Policy with a fresh nonce, plus the other security headers.
const PROTECTED = ["/coordinator", "/pantry", "/admin"];
const HTTPS_SITE = process.env.COOKIE_SECURE === "true"; // the same switch the API uses for HSTS

export function contentSecurityPolicy(nonce: string, development: boolean): string {
  // Scripts: only ours (same origin) and those that carry this request's nonce. 'strict-dynamic'
  // lets those trusted scripts load their own chunks. There is no 'unsafe-inline' for scripts.
  const scripts = ["'self'", `'nonce-${nonce}'`, "'strict-dynamic'"];
  if (development) scripts.push("'unsafe-eval'"); // React's development tools need eval
  return [
    "default-src 'self'",
    `script-src ${scripts.join(" ")}`,
    // Styles keep 'unsafe-inline': Next.js and Recharts write style attributes and <style> tags that
    // cannot carry a nonce. Script injection is the serious risk and scripts are locked down above.
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self'",
    `connect-src 'self'${development ? " ws: wss:" : ""}`,
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    ...(HTTPS_SITE ? ["upgrade-insecure-requests"] : []),
  ].join("; ");
}

export const SECURITY_HEADERS: Record<string, string> = {
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
  "Referrer-Policy": "no-referrer",
  "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
  "Cross-Origin-Opener-Policy": "same-origin",
  "Cross-Origin-Resource-Policy": "same-origin",
  ...(HTTPS_SITE ? { "Strict-Transport-Security": "max-age=31536000; includeSubDomains" } : {}),
};

export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const protectedPage = PROTECTED.some((p) => pathname === p || pathname.startsWith(`${p}/`));
  if (protectedPage && !request.cookies.has("pp_session")) {
    const login = new URL("/login", request.url);
    login.searchParams.set("next", pathname + search);
    return withSecurityHeaders(NextResponse.redirect(login), contentSecurityPolicy("redirect", false));
  }

  const nonce = btoa(crypto.randomUUID());
  const policy = contentSecurityPolicy(nonce, process.env.NODE_ENV !== "production");
  // Pages read these request headers: the nonce goes onto Next.js's own scripts, and the page
  // address lets the "temporarily unavailable" screen bring the visitor back.
  const headers = new Headers(request.headers);
  headers.set("x-nonce", nonce);
  headers.set("content-security-policy", policy);
  headers.set("x-pathname", pathname + search);
  return withSecurityHeaders(NextResponse.next({ request: { headers } }), policy);
}

function withSecurityHeaders(response: NextResponse, policy: string): NextResponse {
  response.headers.set("Content-Security-Policy", policy);
  for (const [name, value] of Object.entries(SECURITY_HEADERS)) response.headers.set(name, value);
  return response;
}

export const config = {
  // Everything except the API (proxied), Next's static files and the favicon.
  matcher: [{ source: "/((?!api/|_next/static|_next/image|favicon.ico).*)" }],
};
