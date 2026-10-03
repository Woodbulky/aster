import { NextResponse, type NextRequest } from "next/server";

import { safeNext } from "@/lib/safe-next";
import { createClient } from "@/lib/supabase/server";

/** OAuth + magic-link (PKCE) landing: exchange the code for a session cookie. Also takes a
 * `token_hash` (an admin-generated sign-in link, e.g. the demo account from the seed script). */
export async function GET(request: NextRequest) {
  const { searchParams, origin } = request.nextUrl;
  const code = searchParams.get("code");
  const next = safeNext(searchParams.get("next"));

  const tokenHash = searchParams.get("token_hash");
  if (tokenHash && searchParams.get("type") === "magiclink") {
    const supabase = await createClient();
    const { error } = await supabase.auth.verifyOtp({ token_hash: tokenHash, type: "magiclink" });
    if (!error) return NextResponse.redirect(new URL(next, origin));
  }
  if (code) {
    const supabase = await createClient();
    const { error } = await supabase.auth.exchangeCodeForSession(code);
    if (!error) return NextResponse.redirect(new URL(next, origin));
  }
  return NextResponse.redirect(new URL("/login?error=auth", origin));
}
