"use client";

import Link from "next/link";
import { useTranslation } from "@/lib/i18n";
import { Locale } from "@/lib/copy";
import BrandMark from "@/components/BrandMark";
import ThemeToggle from "@/components/ThemeToggle";

export default function PrivacyPage() {
  const { locale, setLocale, t } = useTranslation();
  const p = t.privacy;

  return (
    <div className="min-h-screen bg-background landing-pattern">
      <header className="sticky top-0 z-50 border-b bg-background/95 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-4xl items-center justify-between px-4">
          <BrandMark />
          <div className="flex items-center gap-3">
            <select
              value={locale}
              onChange={(e) => setLocale(e.target.value as Locale)}
              className="h-8 rounded-md border bg-background px-2 text-xs text-muted-foreground"
            >
              <option value="ko">KO</option>
              <option value="en">EN</option>
            </select>
            <ThemeToggle />
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-4xl px-4 py-16">
        <h1 className="text-3xl font-bold">{p.title}</h1>
        <h2 className="mt-2 text-lg text-muted-foreground">{p.subtitle}</h2>

        <p className="mt-8 leading-relaxed text-muted-foreground">{p.preamble}</p>

        <div className="mt-12 space-y-12">
          {p.sections.map((section) => (
            <section key={section.title}>
              <h3 className="text-lg font-semibold">{section.title}</h3>
              {section.content && (
                <p className="mt-2 text-sm text-muted-foreground">{section.content}</p>
              )}
              <ul className="mt-3 space-y-2">
                {section.items.map((item, i) => (
                  <li key={i} className="text-sm leading-relaxed text-muted-foreground">
                    {item}
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>

        <p className="mt-16 text-sm text-muted-foreground">{p.dates}</p>

        <div className="mt-8 border-t pt-8">
          <Link href="/" className="text-sm text-muted-foreground hover:text-foreground transition-colors">
            ← {t.common.backToHome}
          </Link>
        </div>
      </main>
    </div>
  );
}
