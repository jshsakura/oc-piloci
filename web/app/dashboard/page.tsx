"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

// /dashboard kept as a redirect for back-compat with bookmarks and the
// install script's deep links. Routes were split into /summary,
// /activity, /pipeline, /memory, /projects, /teams in v0.3.47.
export default function DashboardRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/summary");
  }, [router]);
  return null;
}
