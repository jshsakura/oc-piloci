import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";
import { getCopy } from "@/lib/copy";

const copy = getCopy();
const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "https://piloci.opencourse.kr";

export const metadata: Metadata = {
  title: {
    template: "%s | piLoci",
    default: copy.metadata.title,
  },
  description: copy.metadata.description,
  metadataBase: new URL(SITE_URL),
  alternates: { canonical: SITE_URL },
  robots: { index: true, follow: true },
  keywords: ["piLoci", "MCP", "LLM memory", "Raspberry Pi", "self-hosted", "LanceDB", "AI context"],
  openGraph: {
    title: copy.metadata.title,
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
      <body className="antialiased">
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: jsonLd }}
        />
        <script dangerouslySetInnerHTML={{ __html: `(function(){try{var t=localStorage.getItem("piloci-theme");var d=t==="dark"||t==="light"?t:matchMedia("(prefers-color-scheme:dark)").matches?"dark":"light";document.documentElement.classList.toggle("dark",d==="dark");document.documentElement.style.colorScheme=d}catch(e){}})()` }} />
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
