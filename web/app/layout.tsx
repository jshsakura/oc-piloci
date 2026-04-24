import type { Metadata } from "next";
import Script from "next/script";
import "./globals.css";
import { Providers } from "./providers";
import { getCopy } from "@/lib/copy";

const themeInitScript = `
  const storageKey = 'piloci-theme';
  const storedTheme = localStorage.getItem(storageKey);
  const systemPrefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  const theme = storedTheme === 'dark' || storedTheme === 'light'
    ? storedTheme
    : systemPrefersDark
      ? 'dark'
      : 'light';
  const root = document.documentElement;
  root.classList.toggle('dark', theme === 'dark');
  root.style.colorScheme = theme;
`;

const copy = getCopy();

export const metadata: Metadata = {
  title: {
    template: '%s | piLoci',
    default: 'piLoci - Knowledge Memory for Your AI Core',
  },
  description: copy.metadata.description,
  metadataBase: new URL('https://piloci.io'),
  openGraph: {
    title: 'piLoci - Knowledge Memory for Your AI Core',
    description: copy.metadata.description,
    url: 'https://piloci.io',
    siteName: 'piLoci',
    images: [{ url: '/og-image.webp', width: 1200, height: 630 }],
    locale: 'ko_KR',
    type: 'website',
  },
  twitter: {
    card: 'summary_large_image',
    title: 'piLoci - Knowledge Memory for Your AI Core',
    description: copy.metadata.description,
    images: ['/og-image.webp'],
  },
  icons: {
    icon: "/icon.svg",
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko" suppressHydrationWarning>
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link href="https://fonts.googleapis.com/css2?family=Gugi&display=swap" rel="stylesheet" />
      </head>
      <body className="antialiased">
        <Script id="piloci-theme-init" strategy="beforeInteractive">
          {themeInitScript}
        </Script>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
