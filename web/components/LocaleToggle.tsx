"use client";

import { useTranslation } from "@/lib/i18n";
import { locales, localeLabels } from "@/lib/copy";

// Two-language compact toggle, N-language scalable. With 2 locales it shows
// "KO / EN" highlighting the active one. Adding a 3rd or 4th language to
// ``locales`` automatically extends this list — no separate UI work needed.
export default function LocaleToggle() {
  const { locale, setLocale } = useTranslation();

  return (
    <div className="inline-flex h-8 items-center gap-1 rounded-md border border-input bg-background px-2.5 text-xs font-medium text-muted-foreground">
      {locales.map((code, idx) => {
        const active = code === locale;
        return (
          <span key={code} className="contents">
            {idx > 0 && <span className="opacity-40">/</span>}
            <button
              type="button"
              onClick={() => setLocale(code)}
              className={`cursor-pointer rounded-sm px-0.5 transition-colors hover:text-foreground ${
                active ? "font-bold text-foreground" : ""
              }`}
              aria-label={localeLabels[code].native}
              aria-pressed={active}
            >
              {localeLabels[code].short}
            </button>
          </span>
        );
      })}
    </div>
  );
}
