import type { Metadata } from "next";
import Script from "next/script";
import "./globals.css";
import { Providers } from "./providers";
import { getCopy } from "@/lib/copy";

const copy = getCopy();
const SITE_URL = "https://piloci.jshsakura.com";

export const metadata: Metadata = {
  title: {
    template: "%s | piLoci",
    default: "piLoci, AI가 스스로 기억하게 돕는 세컨드 브레인",
  },
  description: copy.metadata.description,
  metadataBase: new URL(SITE_URL),
  alternates: { canonical: SITE_URL },
  robots: { index: true, follow: true },
  keywords: ["piLoci", "MCP", "LLM memory", "Raspberry Pi", "self-hosted", "LanceDB", "AI context"],
  openGraph: {
    title: "piLoci, AI가 스스로 기억하게 돕는 세컨드 브레인",
    description: copy.metadata.description,
    url: SITE_URL,
    siteName: "piLoci",
    images: [{ url: "/og-image.png", width: 1200, height: 630, alt: "piLoci Memory Graph" }],
    locale: "ko_KR",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "piLoci, The Second Brain That Helps AI Remember",
    description: copy.metadata.description,
    images: ['/og-image.png'],
  },
  icons: {
    icon: [
      { url: "/favicon.ico", sizes: "48x48" },
      { url: "/icon.svg", type: "image/svg+xml" },
      { url: "/icon-192.png", sizes: "192x192", type: "image/png" },
    ],
    apple: [{ url: "/apple-touch-icon.png", sizes: "180x180", type: "image/png" }],
  },
};

const jsonLd = JSON.stringify({
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  name: "piLoci",
  description: copy.metadata.description,
  url: SITE_URL,
  applicationCategory: "DeveloperApplication",
  operatingSystem: "Linux",
  offers: { "@type": "Offer", price: "0", priceCurrency: "USD" },
  featureList: [
    "Project-scoped memory isolation",
    "MCP-native memory surface",
    "LanceDB semantic search",
    "Obsidian-compatible workspace",
    "Multi-user team support",
  ],
});

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko" suppressHydrationWarning>
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link href="https://fonts.googleapis.com/css2?family=Gugi&display=swap" rel="stylesheet" />
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: jsonLd }}
        />
      </head>
      <body className="antialiased">
        <Script src="/theme-init.js" strategy="beforeInteractive" />
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
