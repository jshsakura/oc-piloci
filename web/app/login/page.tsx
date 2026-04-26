"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import AuthLayout from "@/components/AuthLayout";
import { AuthProviderButtons } from "@/components/auth-provider-buttons";
import { useAuthStore } from "@/lib/auth";
import { api, type AuthProviderStatus } from "@/lib/api";
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

const loginSchema = z.object({
  email: z.string().email("유효한 이메일을 입력하세요"),
  password: z.string().min(1, "비밀번호를 입력하세요"),
});

type LoginFormValues = z.infer<typeof loginSchema>;

function getErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    const msg = error.message.toLowerCase();
    if (msg.includes("locked") || msg.includes("잠김")) return "계정이 잠겼습니다";
    if (msg.includes("invalid") || msg.includes("unauthorized") || msg.includes("401")) {
      return "이메일 또는 비밀번호가 올바르지 않습니다";
    }
  }
  return "이메일 또는 비밀번호가 올바르지 않습니다";
}

function getOauthErrorMessage(error: string | null): string | null {
  switch (error) {
    case "oauth_cancelled":
      return "소셜 로그인이 취소되었습니다. 다시 시도해 주세요.";
    case "oauth_invalid_state":
      return "로그인 요청이 만료되었거나 유효하지 않습니다. 다시 시도해 주세요.";
    case "oauth_failed":
      return "소셜 로그인 처리 중 오류가 발생했습니다. 다시 시도해 주세요.";
    default:
      return null;
  }
}

export default function LoginPage() {
  const router = useRouter();
  const { setUser } = useAuthStore();
  const [serverError, setServerError] = useState<string | null>(null);
  const [isPending, setIsPending] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [authProviders, setAuthProviders] = useState<AuthProviderStatus[]>([]);
  const [oauthError, setOauthError] = useState<string | null>(null);
  const [resetNotice, setResetNotice] = useState<string | null>(null);

  const form = useForm<LoginFormValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: "", password: "" },
  });

  useEffect(() => {
    let active = true;

    void api.listAuthProviders()
      .then((result) => {
        if (active) {
          setAuthProviders(result.providers);
        }
      })
      .catch(() => {
        if (active) {
          setAuthProviders([]);
        }
      });

    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    setOauthError(getOauthErrorMessage(params.get("error")));
    setResetNotice(
      params.get("reset") === "1"
        ? "비밀번호가 변경되었습니다. 새 비밀번호로 로그인해 주세요."
        : null
    );
  }, []);

  const onSubmit = async (data: LoginFormValues) => {
    setServerError(null);
    setIsPending(true);
    try {
      const user = (await api.login(data.email, data.password)) as User;
      setUser(user);
      router.push("/dashboard");
    } catch (err) {
      setServerError(getErrorMessage(err));
    } finally {
      setIsPending(false);
    }
  };

  const hasAuthProviders = authProviders.some((provider) => provider.configured);

  return (
    <AuthLayout>
      <div className="w-full max-w-sm rounded-xl border border-border bg-card p-8 shadow-sm">
        <div className="mb-8 text-center">
          <h2 className="text-2xl font-bold">로그인</h2>
          <p className="mt-2 text-sm text-muted-foreground">
            {"프로젝트 워크스페이스에 접속하세요".split("AI").map((part, i, arr) => (
              <span key={i}>
                {part}
                {i < arr.length - 1 && (
                  <span className="bg-clip-text text-transparent animate-[rainbow_4s_linear_infinite] bg-[linear-gradient(90deg,#f87171,#fb923c,#fbbf24,#a3e635,#34d399,#22d3ee,#818cf8,#c084fc,#f87171)] bg-[length:200%_100%]">
                    AI
                  </span>
                )}
              </span>
            ))}
          </p>
        </div>

        {resetNotice && (
          <div className="mb-4 rounded-md border border-emerald-500/20 bg-emerald-500/10 p-3 text-sm text-emerald-700 dark:text-emerald-300">
            {resetNotice}
          </div>
        )}

        {oauthError && (
          <div className="mb-4 rounded-md border border-destructive/20 bg-destructive/10 p-3 text-sm text-destructive">
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
                    이메일
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
                    비밀번호
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
              <div className="rounded-md border border-destructive/20 bg-destructive/10 p-3 text-sm text-destructive">
                {serverError}
              </div>
            )}

            <Button type="submit" disabled={isPending} className="w-full">
              {isPending ? "인증 중..." : "로그인"}
            </Button>
          </form>
        </Form>

        {hasAuthProviders && (
          <>
            <div className="relative my-6">
              <div className="absolute inset-0 flex items-center"><div className="w-full border-t" /></div>
              <div className="relative flex justify-center text-xs uppercase text-muted-foreground">
                <span className="bg-card px-2">또는</span>
              </div>
            </div>

            <AuthProviderButtons providers={authProviders} />
          </>
        )}

        <div className="mt-4 text-center">
          <Link href="/forgot-password" className="text-sm text-muted-foreground underline underline-offset-4 transition-colors hover:text-foreground">
            비밀번호를 잊으셨나요?
          </Link>
        </div>

        <div className="mt-4 text-center">
          <p className="text-sm text-muted-foreground">
            계정이 없으신가요?{" "}
            <Link href="/signup" className="text-primary underline underline-offset-4">
              가입하기
            </Link>
          </p>
        </div>
      </div>
    </AuthLayout>
  );
}
