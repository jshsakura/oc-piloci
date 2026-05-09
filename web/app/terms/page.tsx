"use client";

import Link from "next/link";
import { useTranslation } from "@/lib/i18n";
import { Locale } from "@/lib/copy";
import BrandMark from "@/components/BrandMark";
import ThemeToggle from "@/components/ThemeToggle";

export default function TermsPage() {
  const { locale, setLocale, t } = useTranslation();
  const terms = t.terms;

  return (
    <div className="pi-app-bg min-h-screen">
      <header className="pi-glass-nav sticky top-0 z-50 border-b backdrop-blur-xl">
        <div className="mx-auto flex h-14 max-w-4xl items-center justify-between px-4">
          <BrandMark />
          <div className="flex items-center gap-3">
            <select
              value={locale}
              onChange={(e) => setLocale(e.target.value as Locale)}
              className="pi-soft-input h-8 px-2 text-xs text-muted-foreground"
            >
              <option value="ko">KO</option>
              <option value="en">EN</option>
            </select>
            <ThemeToggle />
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-4xl px-4 py-16">
        <section className="pi-page-hero">
          <h1 className="pi-title">{terms.title}</h1>
          <h2 className="pi-subtitle text-base">{terms.subtitle}</h2>
        </section>

        <p className="mt-8 leading-relaxed text-muted-foreground">{terms.preamble}</p>

        <div className="mt-12 space-y-4">
          {terms.sections.map((section) => (
            <section key={section.title} className="pi-panel p-5 sm:p-6">
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

        <p className="mt-16 text-sm text-muted-foreground">{terms.dates}</p>

        <div className="mt-8 border-t pt-8">
          <Link href="/" className="text-sm text-muted-foreground hover:text-foreground transition-colors">
            ← {t.common.backToHome}
          </Link>
        </div>
      </main>
    </div>
  );
}
