"use client";

import Link from "next/link";
import BrandMark from "@/components/BrandMark";
import { useTranslation } from "@/lib/i18n";

function RainbowAI({ text }: { text: string }) {
  const parts = text.split("AI");
  return (
    <>
      {parts.map((part, i, arr) => (
        <span key={i}>
          {part}
          {i < arr.length - 1 && (
            <span className="bg-clip-text text-transparent animate-[rainbow_4s_linear_infinite] bg-[linear-gradient(90deg,#f87171,#fb923c,#fbbf24,#a3e635,#34d399,#22d3ee,#818cf8,#c084fc,#f87171)] bg-[length:200%_100%]">
              AI
            </span>
          )}
        </span>
      ))}
    </>
  );
}

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  const { locale } = useTranslation();
  return (
    <div className="flex min-h-screen">
      <div className="hidden lg:flex lg:w-1/2 flex-col justify-between p-12 bg-muted/50 border-r section-pattern">
        <BrandMark />
        <div className="space-y-4">
          <h1 className="text-3xl font-bold tracking-tight">
            <RainbowAI text="당신의 AI에게" />
            <br />
            새로운 기억들을 추가해보세요
          </h1>
          <p className="text-muted-foreground max-w-md">
            piLoci는 프로젝트별 격리된 메모리 공간으로 AI가 맥락을 잃지 않도록 돕습니다.
          </p>
        </div>
        <p className="text-sm text-muted-foreground">
          © piLoci 2026. Husband of Rebekah. ·{" "}
          <Link href="/privacy" className="hover:text-foreground transition-colors">
            {locale === "ko" ? "개인정보 처리방침" : "Privacy Policy"}
          </Link>
          {" "}·{" "}
          <Link href="/terms" className="hover:text-foreground transition-colors">
            {locale === "ko" ? "서비스 약관" : "Terms of Service"}
          </Link>
        </p>
      </div>
      <div className="flex w-full lg:w-1/2 items-center justify-center p-6 landing-pattern">
        {children}
      </div>
    </div>
  );
}
