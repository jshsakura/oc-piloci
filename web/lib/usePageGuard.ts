"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/lib/auth";

/**
 * Drains the auth + hydration boilerplate that every authenticated page
 * was repeating: read the auth store, redirect to /login when known
 * unauth'd, and surface a flag for the still-loading vs ready states.
 *
 *   const guard = usePageGuard();
 *   if (guard === "pending") return <Pending/>;
 *   if (guard === "redirecting") return null;
 *   // guard === "ready" — render the page
 *
 * Pages can also wrap themselves in <AuthedPage> for the common case
 * where they don't need to inspect the state machine themselves.
 */
export type PageGuardState = "pending" | "redirecting" | "ready";

export function usePageGuard() {
  const router = useRouter();
  const { user, hasHydrated, isBootstrapping } = useAuthStore();

  useEffect(() => {
    if (hasHydrated && !isBootstrapping && !user) {
      router.replace("/login");
    }
  }, [hasHydrated, isBootstrapping, router, user]);

  let state: PageGuardState;
  if (!hasHydrated || isBootstrapping) state = "pending";
  else if (!user) state = "redirecting";
  else state = "ready";

  return { state, user };
}
