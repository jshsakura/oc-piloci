'use client';

import React, { createContext, useContext, useState, useEffect } from 'react';
import { Locale, defaultLocale, getCopy } from './copy';

type I18nContextType = {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: ReturnType<typeof getCopy>;
};

const I18nContext = createContext<I18nContextType | undefined>(undefined);

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(defaultLocale);

  // Load locale from localStorage on mount
  useEffect(() => {
    try {
      const saved = window.localStorage.getItem('locale') as Locale | null;
      if (saved && (saved === 'ko' || saved === 'en')) {
        setLocaleState(saved);
      }
    } catch {
      // Ignore storage failures and keep default locale.
    }
  }, []);

  const setLocale = (newLocale: Locale) => {
    setLocaleState(newLocale);
    try {
      window.localStorage.setItem('locale', newLocale);
    } catch {
      // Ignore storage failures and keep in-memory locale.
    }

    document.cookie = `locale=${newLocale};path=/;max-age=31536000`;
  };

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
