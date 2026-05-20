"use client";

import { Suspense, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import AppShell from "@/components/AppShell";
import { useTranslation } from "@/lib/i18n";

// The team wiki now lives as a tab inside /teams. This route is kept as a thin
// redirect so old links and bookmarks (/teams/wiki?id=…) still land on the
// LLM 위키 tab. useSearchParams() needs a Suspense boundary under static export.
export default function TeamWikiRedirectPage() {
  return (
    <Suspense fallback={<RedirectFallback />}>
      <TeamWikiRedirect />
    </Suspense>
  );
}

function RedirectFallback() {
  const { t } = useTranslation();
  return (
    <AppShell title={t.teams.wiki.title}>
      <p className="text-sm text-muted-foreground">{t.teams.wiki.loading}</p>
    </AppShell>
  );
}

function TeamWikiRedirect() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const id = searchParams?.get("id") ?? "";

  useEffect(() => {
    router.replace(`/teams?tab=wiki${id ? `&id=${id}` : ""}`);
  }, [router, id]);

  return <RedirectFallback />;
}
