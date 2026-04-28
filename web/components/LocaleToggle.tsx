"use client";

import { useTranslation } from "@/lib/i18n";

export default function LocaleToggle() {
  const { locale, setLocale } = useTranslation();

  return (
    <button
      onClick={() => setLocale(locale === "ko" ? "en" : "ko")}
      className="inline-flex h-8 cursor-pointer items-center gap-1 rounded-md border border-input bg-background px-2.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
    >
      <span className={locale === "ko" ? "text-foreground font-bold" : ""}>KO</span>
      <span className="opacity-40">/</span>
      <span className={locale === "en" ? "text-foreground font-bold" : ""}>EN</span>
    </button>
  );
}
