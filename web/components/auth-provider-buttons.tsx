"use client";

import type { ReactElement } from "react";

import { Button } from "@/components/ui/button";
import type { AuthProviderName, AuthProviderStatus } from "@/lib/api";

const PROVIDER_ORDER: AuthProviderName[] = ["kakao", "naver", "google", "github"];

const providerMeta: Record<
  AuthProviderName,
  {
    label: string;
    className: string;
    icon: ReactElement;
    variant?: "default" | "outline";
  }
> = {
  kakao: {
    label: "카카오로 계속하기",
    className: "w-full gap-2 rounded-lg bg-[#FEE500] text-[#191919] hover:bg-[#F2D900]",
    icon: (
      <svg className="size-4" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <path d="M12 3C6.48 3 2 6.58 2 11c0 2.78 1.77 5.23 4.46 6.66L5.5 21l4.24-2.33c.73.11 1.48.17 2.26.17 5.52 0 10-3.58 10-8s-4.48-8-10-8Z" />
      </svg>
    ),
  },
  naver: {
    label: "네이버로 계속하기",
    className: "w-full gap-2 rounded-lg bg-[#03C75A] text-white hover:bg-[#02b351]",
    icon: (
      <svg className="size-4" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path d="M6 4h4.1l3.8 5.45V4H18v16h-4.1L10.1 14.55V20H6V4Z" fill="currentColor" />
      </svg>
    ),
  },
  google: {
    label: "Google로 계속하기",
    className: "w-full gap-2 rounded-lg",
    variant: "outline",
    icon: (
      <svg className="size-4" viewBox="0 0 24 24" aria-hidden="true">
        <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" fill="#4285F4"/>
        <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
        <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05"/>
        <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
      </svg>
    ),
  },
  github: {
    label: "GitHub로 계속하기",
    className: "w-full gap-2 rounded-lg bg-[#24292F] text-white hover:bg-[#1b1f23]",
    icon: (
      <svg className="size-4" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <path d="M12 2C6.48 2 2 6.58 2 12.26c0 4.54 2.87 8.39 6.84 9.75.5.1.68-.22.68-.49 0-.24-.01-1.04-.01-1.88-2.78.62-3.37-1.21-3.37-1.21-.46-1.2-1.11-1.52-1.11-1.52-.91-.64.07-.63.07-.63 1 .07 1.53 1.06 1.53 1.06.9 1.57 2.36 1.12 2.94.86.09-.67.35-1.12.63-1.38-2.22-.26-4.55-1.14-4.55-5.09 0-1.12.39-2.03 1.03-2.75-.1-.26-.45-1.3.1-2.71 0 0 .84-.28 2.75 1.05A9.35 9.35 0 0 1 12 6.84c.85 0 1.71.12 2.51.36 1.9-1.33 2.74-1.05 2.74-1.05.56 1.41.21 2.45.11 2.71.64.72 1.03 1.63 1.03 2.75 0 3.96-2.33 4.82-4.56 5.08.36.32.68.95.68 1.92 0 1.39-.01 2.5-.01 2.84 0 .27.18.59.69.49A10.28 10.28 0 0 0 22 12.26C22 6.58 17.52 2 12 2Z" />
      </svg>
    ),
  },
};

export function AuthProviderButtons({ providers }: { providers: AuthProviderStatus[] }) {
  const configuredProviders = PROVIDER_ORDER.filter((name) =>
    providers.some((provider) => provider.name === name && provider.configured)
  ).map((name) => {
    const provider = providers.find((item) => item.name === name);
    return provider ?? null;
  }).filter((provider): provider is AuthProviderStatus => provider !== null);

  if (configuredProviders.length === 0) {
    return null;
  }

  return (
    <div className="space-y-2">
      {configuredProviders.map((provider) => {
        const meta = providerMeta[provider.name];
        return (
          <Button key={provider.name} variant={meta.variant} className={meta.className} asChild>
            <a href={provider.login_path}>
              {meta.icon}
              {meta.label}
            </a>
          </Button>
        );
      })}
    </div>
  );
}
