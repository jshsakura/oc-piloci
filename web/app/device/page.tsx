"use client";

import { Suspense } from "react";

import RoutePending from "@/components/RoutePending";
import { useTranslation } from "@/lib/i18n";

import DeviceClient from "./device-client";

function DevicePending() {
  const { t } = useTranslation();
  return (
    <RoutePending
      fullScreen
      title={t.device.pendingTitle}
      description={t.device.pendingDesc}
    />
  );
}

export default function DevicePage() {
  return (
    <Suspense fallback={<DevicePending />}>
      <DeviceClient />
    </Suspense>
  );
}
