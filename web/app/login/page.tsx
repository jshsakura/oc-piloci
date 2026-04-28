import type { AuthProviderStatus } from "@/lib/api";
import LoginClient from "./login-client";

async function getAuthProviders(): Promise<AuthProviderStatus[]> {
  try {
    const apiBase = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8314";
    const res = await fetch(`${apiBase}/api/auth/providers`, { cache: "no-store" });
    if (!res.ok) return [];
    const data = (await res.json()) as { providers: AuthProviderStatus[] };
    return data.providers ?? [];
  } catch {
    return [];
  }
}

export default async function LoginPage() {
  const authProviders = await getAuthProviders();
  return <LoginClient authProviders={authProviders} />;
}
