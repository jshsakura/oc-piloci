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
    default: 'piLoci - High Performance MCP Memory Engine',
  },
  description: copy.metadata.description,
  metadataBase: new URL('https://piloci.io'), // 예시 URL
  openGraph: {
    title: 'piLoci - Your AI Memory Vault',
    description: copy.metadata.description,
    url: 'https://piloci.io',
    siteName: 'piLoci',
    images: [
      {
        url: '/og-image.png', // 이미지 있다고 가정
        width: 1200,
        height: 630,
      },
    ],
    locale: 'ko_KR',
    type: 'website',
  },
  twitter: {
    card: 'summary_large_image',
    title: 'piLoci - Your AI Memory Vault',
    description: copy.metadata.description,
    images: ['/og-image.png'],
  },
  icons: {
    icon: "/icon.svg",
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko" data-skin="linear" suppressHydrationWarning>
      <body className="antialiased">
        <Script id="piloci-theme-init" strategy="beforeInteractive">
          {themeInitScript}
        </Script>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
