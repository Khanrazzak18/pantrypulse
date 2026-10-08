import { type NextRequest, NextResponse } from "next/server";

// Runs before a protected page renders. It only checks that a session cookie exists, so a visitor
// who is not logged in gets a real redirect instead of a flash of the loading screen. It cannot
// tell whether the cookie is still valid: the pages ask the API (see lib/auth.ts), and the API
// enforces every rule. Expired cookies and wrong roles are handled there.
export function proxy(request: NextRequest) {
  if (request.cookies.has("pp_session")) return NextResponse.next();
  const login = new URL("/login", request.url);
  login.searchParams.set("next", request.nextUrl.pathname + request.nextUrl.search);
  return NextResponse.redirect(login);
}

export const config = {
  matcher: ["/coordinator/:path*", "/pantry/:path*"],
};
