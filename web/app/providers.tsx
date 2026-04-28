"use client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, useEffect } from "react";
import { I18nProvider } from "@/lib/i18n";
import { useAuthStore } from "@/lib/auth";
import { api } from "@/lib/api";

function SessionBootstrap() {
  const { user, hasHydrated, setUser, setIsBootstrapping } = useAuthStore();

  useEffect(() => {
    if (!hasHydrated || user) return;
    setIsBootstrapping(true);
    api.me()
      .then((u) => { setUser(u); })
      .catch(() => {})
      .finally(() => { setIsBootstrapping(false); });
  }, [hasHydrated, user, setUser, setIsBootstrapping]);

  return null;
}

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(() => new QueryClient({
    defaultOptions: { queries: { staleTime: 30_000, retry: 1 } },
  }));
  return (
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <SessionBootstrap />
        {children}
      </I18nProvider>
    </QueryClientProvider>
  );
}
