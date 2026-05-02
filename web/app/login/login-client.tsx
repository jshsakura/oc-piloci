"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { UserRound } from "lucide-react";
import AuthLayout from "@/components/AuthLayout";
import { AuthProviderButtons } from "@/components/auth-provider-buttons";
import { useAuthStore } from "@/lib/auth";
import { api, type AuthProviderStatus } from "@/lib/api";
import { useTranslation } from "@/lib/i18n";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form";
import type { User } from "@/lib/types";


function MailIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect width="20" height="16" x="2" y="4" rx="2" /><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7" />
    </svg>
  );
}
function LockIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect width="18" height="11" x="3" y="11" rx="2" ry="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" />
    </svg>
  );
}
function XIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M18 6 6 18" /><path d="m6 6 12 12" />
    </svg>
  );
}
function EyeIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0" /><circle cx="12" cy="12" r="3" />
    </svg>
  );
}
function EyeOffIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M10.733 5.076a10.744 10.744 0 0 1 11.205 6.575 1 1 0 0 1 0 .696 10.747 10.747 0 0 1-1.444 2.49" /><path d="M14.084 14.158a3 3 0 0 1-4.242-4.242" /><path d="M17.479 17.499a10.75 10.75 0 0 1-15.417-5.151 1 1 0 0 1 0-.696 10.75 10.75 0 0 1 4.446-5.143" /><path d="m2 2 20 20" />
    </svg>
  );
}

type LoginTranslations = {
  login: {
    approvalPendingShort: string;
    approvalRejectedShort: string;
    approvalPending: string;
    approvalRejected: string;
    error: { locked: string; invalidCredentials: string; oauthCancelled: string; oauthExpired: string; oauthFailed: string };
    resetNotice: string;
    validation: { emailInvalid: string; passwordRequired: string };
    title: string;
    subtitle: string;
    emailLabel: string;
    passwordLabel: string;
    submitting: string;
    submit: string;
    or: string;
    forgotPassword: string;
    noAccount: string;
    signupLink: string;
  };
};

function makeLoginSchema(t: LoginTranslations) {
  return z.object({
    email: z.string().email(t.login.validation.emailInvalid),
    password: z.string().min(1, t.login.validation.passwordRequired),
  });
}

type LoginFormValues = z.infer<ReturnType<typeof makeLoginSchema>>;

function getErrorMessage(error: unknown, tc: LoginTranslations): string {
  if (error instanceof Error) {
    const msg = error.message.toLowerCase();
    if (msg.includes("pending") || msg.includes("승인")) return tc.login.approvalPendingShort;
    if (msg.includes("rejected") || msg.includes("거부") || msg.includes("거절")) return tc.login.approvalRejectedShort;
    if (msg.includes("locked") || msg.includes("잠김")) return tc.login.error.locked;
  }
  return tc.login.error.invalidCredentials;
}

function getOauthErrorMessage(error: string | null, tc: LoginTranslations): string | null {
  switch (error) {
    case "oauth_cancelled":
      return tc.login.error.oauthCancelled;
    case "oauth_invalid_state":
      return tc.login.error.oauthExpired;
    case "oauth_failed":
      return tc.login.error.oauthFailed;
    case "approval_pending":
      return tc.login.approvalPending;
    case "approval_rejected":
      return tc.login.approvalRejected;
    default:
      return null;
  }
}

function RainbowAI({ text }: { text: string }) {
  const parts = text.split("AI");
  return (
    <>
      {parts.map((part, i, arr) => (
        <span key={i}>
          {part}
          {i < arr.length - 1 && (
            <span className="bg-clip-text text-transparent animate-[rainbow_4s_linear_infinite] bg-[linear-gradient(90deg,#f87171,#fb923c,#fbbf24,#a3e635,#34d399,#22d3ee,#818cf8,#c084fc,#f87171)] bg-[length:200%_100%]">
              AI
            </span>
          )}
        </span>
      ))}
    </>
  );
}

export default function LoginClient({ authProviders: initialProviders }: { authProviders: AuthProviderStatus[] }) {
  const router = useRouter();
  const { setUser } = useAuthStore();
  const { t } = useTranslation();
  const [serverError, setServerError] = useState<string | null>(null);
  const [isPending, setIsPending] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [authProviders, setAuthProviders] = useState<AuthProviderStatus[]>(initialProviders);
  const [oauthError, setOauthError] = useState<string | null>(null);
  const [resetNotice, setResetNotice] = useState<string | null>(null);

  const loginSchema = makeLoginSchema(t);

  const form = useForm<LoginFormValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: "", password: "" },
  });

  useEffect(() => {
    if (initialProviders.length > 0) return;
    let active = true;
    void api.listAuthProviders()
      .then((result) => { if (active) setAuthProviders(result.providers); })
      .catch(() => { if (active) setAuthProviders([]); });
    return () => { active = false; };
  }, [initialProviders.length]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    setOauthError(getOauthErrorMessage(params.get("error"), t));
    setResetNotice(
      params.get("reset") === "1" ? t.login.resetNotice : null
    );
  }, [t]);

  const onSubmit = async (data: LoginFormValues) => {
    setServerError(null);
    setIsPending(true);
    try {
      const user = (await api.login(data.email, data.password)) as User;
      setUser(user);
      router.push("/dashboard");
    } catch (err) {
      setServerError(getErrorMessage(err, t));
    } finally {
      setIsPending(false);
    }
  };

  const hasAuthProviders = authProviders.some((provider) => provider.configured);

  return (
    <AuthLayout>
      <div className="w-full max-w-sm rounded-xl border border-border bg-card p-8 shadow-sm">
        <div className="mb-8 text-center">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-primary/10">
            <UserRound className="h-7 w-7 text-primary" />
          </div>
          <h2 className="text-2xl font-bold">{t.login.title}</h2>
          <p className="mt-2 text-sm text-muted-foreground">
            <RainbowAI text={t.login.subtitle} />
          </p>
        </div>

        {resetNotice && (
          <div className="mb-4 rounded-md border border-emerald-300 bg-emerald-50 p-3 text-sm text-emerald-800 shadow-sm dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-200">
            {resetNotice}
          </div>
        )}

        {oauthError && (
          <div className="mb-4 rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-800 shadow-sm dark:border-red-800 dark:bg-red-950 dark:text-red-200">
            {oauthError}
          </div>
        )}

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} noValidate className="space-y-4">
            <FormField
              control={form.control}
              name="email"
              render={({ field }) => (
                <FormItem>
                  <FormLabel className="flex items-center gap-1.5">
                    <MailIcon className="size-3.5" />
                    {t.login.emailLabel}
                  </FormLabel>
                  <FormControl>
                    <div className="relative">
                      <Input type="email" autoComplete="email" placeholder="you@example.com" {...field} />
                      {field.value && (
                        <button
                          type="button"
                          onClick={() => form.setValue("email", "", { shouldValidate: false })}
                          className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-0.5 text-muted-foreground transition-colors hover:text-foreground"
                        >
                          <XIcon className="size-3.5" />
                        </button>
                      )}
                    </div>
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="password"
              render={({ field }) => (
                <FormItem>
                  <FormLabel className="flex items-center gap-1.5">
                    <LockIcon className="size-3.5" />
                    {t.login.passwordLabel}
                  </FormLabel>
                  <FormControl>
                    <div className="relative">
                      <Input
                        type={showPassword ? "text" : "password"}
                        autoComplete="current-password"
                        placeholder="••••••••"
                        {...field}
                      />
                      <div className="absolute right-1.5 top-1/2 flex -translate-y-1/2 items-center gap-0.5">
                        {field.value && (
                          <button
                            type="button"
                            onClick={() => form.setValue("password", "", { shouldValidate: false })}
                            className="rounded p-0.5 text-muted-foreground transition-colors hover:text-foreground"
                          >
                            <XIcon className="size-3.5" />
                          </button>
                        )}
                        <button
                          type="button"
                          onClick={() => setShowPassword(!showPassword)}
                          className="rounded p-0.5 text-muted-foreground transition-colors hover:text-foreground"
                        >
                          {showPassword ? <EyeOffIcon className="size-3.5" /> : <EyeIcon className="size-3.5" />}
                        </button>
                      </div>
                    </div>
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            {serverError && (
              <div className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-800 shadow-sm dark:border-red-800 dark:bg-red-950 dark:text-red-200">
                {serverError}
              </div>
            )}

            <Button type="submit" disabled={isPending} className="w-full">
              {isPending ? t.login.submitting : t.login.submit}
            </Button>
          </form>
        </Form>

        {hasAuthProviders && (
          <>
            <div className="relative my-6">
              <div className="absolute inset-0 flex items-center"><div className="w-full border-t" /></div>
              <div className="relative flex justify-center text-xs uppercase text-muted-foreground">
                <span className="bg-card px-2">{t.login.or}</span>
              </div>
            </div>

            <AuthProviderButtons providers={authProviders} />
          </>
        )}

        <div className="mt-4 text-center">
          <Link href="/forgot-password" className="text-sm text-muted-foreground underline underline-offset-4 transition-colors hover:text-foreground">
            {t.login.forgotPassword}
          </Link>
        </div>

        <div className="mt-4 text-center">
          <p className="text-sm text-muted-foreground">
            {t.login.noAccount}{" "}
            <Link href="/signup" className="text-primary underline underline-offset-4">
              {t.login.signupLink}
            </Link>
          </p>
        </div>
      </div>
    </AuthLayout>
  );
}
