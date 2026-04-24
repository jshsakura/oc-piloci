"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import {
  Fingerprint, Code2, Zap, ShieldCheck, BrainCircuit, Network,
  Lock, Plug, ArrowRight, Activity, TrendingDown, Gauge,
} from "lucide-react";
import { useAuthStore } from "@/lib/auth";
import { useTranslation } from "@/lib/i18n";
import { Locale } from "@/lib/copy";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import BrandMark from "@/components/BrandMark";
import ThemeToggle from "@/components/ThemeToggle";
import TypingQuotes from "@/components/TypingQuotes";

export default function LandingPage() {
  const router = useRouter();
  const { user } = useAuthStore();
  const { locale, setLocale, t } = useTranslation();
  const [copied, setCopied] = useState(false);

  const copyInstall = () => {
    navigator.clipboard.writeText("uvx oc-piloci install");
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  useEffect(() => {
    if (user) router.replace("/dashboard");
  }, [user, router]);

  if (user) return null;

  const features = t.landing.sections.features.list;
  const capabilities = t.landing.sections.capabilities.list;
  const stats = t.landing.stats;

  const featureIcons = [Fingerprint, Code2, Zap, ShieldCheck, BrainCircuit, Network, Lock, Plug];

  return (
    <div
      className="min-h-screen bg-background"
      style={{
        backgroundImage:
          'radial-gradient(circle, hsl(var(--muted-foreground) / 0.06) 1px, transparent 1px)',
        backgroundSize: '24px 24px',
      }}
    >
      {/* Nav */}
      <header className="sticky top-0 z-50 border-b bg-background/95 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4">
          <BrandMark />
          <div className="flex items-center gap-3">
            <select
              value={locale}
              onChange={(e) => setLocale(e.target.value as Locale)}
              className="h-8 rounded-md border bg-background px-2 text-xs text-muted-foreground"
            >
              <option value="ko">KO</option>
              <option value="en">EN</option>
            </select>
            <ThemeToggle />
            <Button variant="ghost" size="sm" asChild>
              <Link href="/login">{t.common.login}</Link>
            </Button>
            <Button size="sm" asChild>
              <Link href="/signup">{t.common.signup}</Link>
            </Button>
          </div>
        </div>
      </header>

      {/* Hero */}
      <section className="relative mx-auto max-w-6xl px-4 py-16 sm:py-24 text-center overflow-hidden">
        <div className="relative z-10">
          <p className="mb-5 sm:mb-6 h-8 text-xs sm:text-sm font-medium tracking-wide text-muted-foreground">
            <TypingQuotes quotes={t.landing.quotes} />
          </p>
          <h1 className="text-2xl font-bold tracking-tight sm:text-4xl md:text-6xl">
            {t.landing.titleLines[0]}
            <br />
            <span className="text-muted-foreground">
              {t.landing.titleLines[1].split("AI").map((part, i, arr) => (
                <span key={i}>
                  {part}
                  {i < arr.length - 1 && (
                    <span className="bg-clip-text text-transparent animate-[rainbow_4s_linear_infinite] bg-[linear-gradient(90deg,#f87171,#fb923c,#fbbf24,#a3e635,#34d399,#22d3ee,#818cf8,#c084fc,#f87171)] bg-[length:200%_100%]">
                      AI
                    </span>
                  )}
                </span>
              ))}
            </span>
          </h1>

          <div className="mx-auto mt-6 sm:mt-8 max-w-2xl space-y-2">
            {t.landing.descriptionLines.map((line, i) => (
              <motion.p
                key={i}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.6, delay: 0.8 + i * 0.5, ease: "easeOut" }}
                className="text-lg text-muted-foreground"
              >
                {line}
              </motion.p>
            ))}
          </div>

          <div className="mx-auto mt-10 sm:mt-16 grid max-w-md grid-cols-3 gap-3 sm:gap-4">
            {[
              { Icon: Gauge, value: stats.latency, label: stats.latencyLabel },
              { Icon: TrendingDown, value: stats.reduction, label: stats.reductionLabel },
              { Icon: Activity, value: stats.uptime, label: stats.uptimeLabel },
            ].map(({ Icon, value, label }) => (
              <div
                key={label}
                className="group flex flex-col items-center gap-2 rounded-xl border bg-muted/30 px-3 py-4 sm:px-5 sm:py-6 backdrop-blur-sm transition-colors hover:bg-muted/50"
              >
                <div className="flex size-8 sm:size-10 items-center justify-center rounded-full bg-primary/10 text-primary transition-colors group-hover:bg-primary/20">
                  <Icon className="size-4 sm:size-5" />
                </div>
                <p className="text-xl sm:text-3xl font-bold tracking-tight">{value}</p>
                <p className="text-[10px] sm:text-xs font-medium text-muted-foreground uppercase tracking-wider">{label}</p>
              </div>
            ))}
          </div>

          {/* Install command */}
          <div className="mx-auto mt-10 sm:mt-12 max-w-lg">
            <button
              onClick={copyInstall}
              className="group flex w-full items-center justify-between gap-3 rounded-lg border bg-muted/50 px-5 py-3 font-mono text-sm transition-colors hover:bg-muted"
            >
              <span className="flex items-center gap-3">
                <span className="text-muted-foreground">$</span>
                <span>uvx oc-piloci install</span>
              </span>
              <span className="text-xs text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100">
                {copied ? "✓ 복사됨" : "복사"}
              </span>
            </button>
          </div>

          <div className="mt-8 sm:mt-10">
            <Button size="lg" asChild>
              <Link href="/signup">
                {t.common.signup}
                <ArrowRight className="ml-2 size-4" />
              </Link>
            </Button>
          </div>
        </div>
      </section>

      {/* Features */}
      <section className="border-t bg-muted/30 py-20">
        <div className="mx-auto max-w-6xl px-4">
          <h2 className="mb-12 text-center text-2xl font-bold">{t.landing.sections.features.title}</h2>
          <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
            {features.map((f, i) => {
              const Icon = featureIcons[i] ?? Fingerprint;
              return (
                <Card key={f.title}>
                  <CardContent className="p-6">
                    <Icon className="mb-3 size-5 text-primary" />
                    <h3 className="mb-2 font-semibold">{f.title}</h3>
                    <p className="text-sm text-muted-foreground">{f.desc}</p>
                  </CardContent>
                </Card>
              );
            })}
          </div>
        </div>
      </section>

      {/* Capabilities */}
      <section className="py-20">
        <div className="mx-auto max-w-6xl px-4">
          <h2 className="mb-4 text-center text-2xl font-bold">{t.landing.sections.capabilities.title}</h2>
          <p className="mb-12 text-center text-muted-foreground">{t.landing.sections.capabilities.desc}</p>
          <div className="grid gap-6 sm:grid-cols-3">
            {capabilities.map((c) => (
              <Card key={c.name}>
                <CardContent className="p-6">
                  <h3 className="mb-2 font-mono text-sm font-semibold">{c.name}</h3>
                  <p className="text-sm text-muted-foreground">{c.desc}</p>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      </section>

      {/* Pricing + Engineering */}
      <section className="border-t bg-muted/30 py-20">
        <div className="mx-auto max-w-6xl px-4">
          <div className="grid gap-8 lg:grid-cols-2">
            {/* Free tier card */}
            <Card className="border-primary/20">
              <CardContent className="p-8">
                <h2 className="mb-2 text-2xl font-bold">{t.landing.sections.pricing.title}</h2>
                <p className="mb-8 text-sm text-muted-foreground">{t.landing.sections.pricing.desc}</p>
                <ul className="space-y-3">
                  {t.landing.sections.pricing.features.map((f) => (
                    <li key={f} className="flex items-center gap-3 text-sm">
                      <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs text-primary">✓</span>
                      {f}
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>

            {/* Engineering card */}
            <Card>
              <CardContent className="p-8">
                <h2 className="mb-2 text-2xl font-bold">{t.landing.sections.pricing.engineering.title}</h2>
                <p className="mb-8 text-sm text-muted-foreground">{t.landing.sections.pricing.engineering.desc}</p>
                <dl className="space-y-4">
                  {t.landing.sections.pricing.engineering.items.map((item) => (
                    <div key={item.label} className="flex gap-3">
                      <dt className="shrink-0 rounded-md bg-muted px-2 py-0.5 font-mono text-xs font-medium">{item.label}</dt>
                      <dd className="text-sm text-muted-foreground">{item.desc}</dd>
                    </div>
                  ))}
                </dl>
              </CardContent>
            </Card>
          </div>
        </div>
      </section>

      <footer className="border-t py-6">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4">
          <p className="text-sm text-muted-foreground">{t.landing.footer}</p>
          <Link href="/privacy" className="text-sm text-muted-foreground/60 hover:text-foreground transition-colors">
            {t.privacy.title}
          </Link>
        </div>
      </footer>
    </div>
  );
}
