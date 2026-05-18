"use client";

import { AuthedPage } from "@/components/AuthedPage";
import { DistillationStatusPanel } from "@/components/DistillationStatusPanel";
import { RecentSessionsCard } from "@/components/RecentSessionsCard";
import { useTranslation } from "@/lib/i18n";

export default function PipelinePage() {
  const { t } = useTranslation();
  const copy = t.pages.pipeline;
  return (
    <AuthedPage title={copy.title}>
      <div className="space-y-6">
        <DistillationStatusPanel />
        <RecentSessionsCard />
      </div>
    </AuthedPage>
  );
}
