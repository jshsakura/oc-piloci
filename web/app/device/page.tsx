import { Suspense } from "react";

import RoutePending from "@/components/RoutePending";

import DeviceClient from "./device-client";

export default function DevicePage() {
  return (
    <Suspense
      fallback={
        <RoutePending
          title="기기 승인 페이지 준비 중"
          description="인증 코드 처리 화면을 불러오고 있습니다."
        />
      }
    >
      <DeviceClient />
    </Suspense>
  );
}
