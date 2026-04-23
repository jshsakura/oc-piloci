'use client';

import { useEffect, useState } from 'react';
import { Moon, Sun } from 'lucide-react';

import { Button } from '@/engine/components/ui/button';
import { getCopy } from '@/lib/copy';

const THEME_STORAGE_KEY = 'piloci-theme';

type ThemeMode = 'light' | 'dark';

function resolveTheme(): ThemeMode {
  const storedTheme = window.localStorage.getItem(THEME_STORAGE_KEY);
  if (storedTheme === 'light' || storedTheme === 'dark') {
    return storedTheme;
  }

  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function applyTheme(theme: ThemeMode) {
  const root = document.documentElement;
  root.classList.toggle('dark', theme === 'dark');
  root.style.colorScheme = theme;
  window.localStorage.setItem(THEME_STORAGE_KEY, theme);
}

export function ThemeToggle() {
  const [theme, setTheme] = useState<ThemeMode>('light');
  const isDark = theme === 'dark';
  const copy = getCopy();

  useEffect(() => {
    const initialTheme = resolveTheme();
    applyTheme(initialTheme);
    setTheme(initialTheme);
  }, []);

  const toggleTheme = () => {
    const nextTheme: ThemeMode = isDark ? 'light' : 'dark';
    applyTheme(nextTheme);
    setTheme(nextTheme);
  };

  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={toggleTheme}
      aria-label={isDark ? copy.themeToggle.toLightAriaLabel : copy.themeToggle.toDarkAriaLabel}
      title={isDark ? copy.themeToggle.toLightAriaLabel : copy.themeToggle.toDarkAriaLabel}
      className="text-text-secondary hover:text-text-primary"
    >
      {isDark ? <Sun className="size-4" /> : <Moon className="size-4" />}
    </Button>
  );
}
