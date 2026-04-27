'use client';

import React, { createContext, useContext, useState, useCallback } from 'react';
import { Locale, defaultLocale, getCopy } from './copy';

type I18nContextType = {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: ReturnType<typeof getCopy>;
};

const I18nContext = createContext<I18nContextType | undefined>(undefined);

function readLocaleFromCookie(): Locale | null {
  if (typeof document === 'undefined') return null;
  const match = document.cookie.match(/(?:^|;\s*)locale=([^;]*)/);
  const value = match?.[1];
  if (value === 'ko' || value === 'en') return value;
  return null;
}

function readLocaleFromStorage(): Locale | null {
  if (typeof window === 'undefined') return null;
  try {
    const saved = window.localStorage.getItem('locale');
    if (saved === 'ko' || saved === 'en') return saved;
  } catch {
    // Ignore storage failures.
  }
  return null;
}

function resolveInitialLocale(): Locale {
  return readLocaleFromCookie() ?? readLocaleFromStorage() ?? defaultLocale;
}

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(resolveInitialLocale);

  const setLocale = useCallback((newLocale: Locale) => {
    setLocaleState(newLocale);
    try {
      window.localStorage.setItem('locale', newLocale);
    } catch {
      // Ignore storage failures and keep in-memory locale.
    }
    document.cookie = `locale=${newLocale};path=/;max-age=31536000;SameSite=Lax`;
  }, []);

  const t = getCopy(locale);

  return (
    <I18nContext.Provider value={{ locale, setLocale, t }}>
      {children}
    </I18nContext.Provider>
  );
}

export function useTranslation() {
  const context = useContext(I18nContext);
  if (context === undefined) {
    throw new Error('useTranslation must be used within an I18nProvider');
  }
  return context;
}
