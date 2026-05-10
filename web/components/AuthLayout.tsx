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
  const { t } = useTranslation();
  return (
    <div className="flex min-h-screen">
      <div className="hidden lg:flex lg:w-1/2 flex-col justify-between border-r bg-muted/50 p-12 section-pattern">
        <BrandMark />
        <div className="space-y-4">
          <h1 className="text-3xl font-semibold tracking-[-0.04em]">
            <RainbowAI text={t.authLayout.heading1} />
            <br />
            {t.authLayout.heading2}
          </h1>
          <p className="text-muted-foreground max-w-md">
            {t.authLayout.description}
          </p>
        </div>
        <p className="text-sm text-muted-foreground">
          © piLoci 2026. Husband of Rebekah. ·{" "}
          <Link href="/privacy" className="hover:text-foreground transition-colors">
            {t.authLayout.privacyLink}
          </Link>
          {" "}·{" "}
          <Link href="/terms" className="hover:text-foreground transition-colors">
            {t.authLayout.termsLink}
          </Link>
        </p>
      </div>
      <div className="flex w-full items-center justify-center p-6 lg:w-1/2 landing-pattern">
        {children}
      </div>
    </div>
  );
}
