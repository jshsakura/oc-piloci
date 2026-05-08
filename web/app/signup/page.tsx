"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import AuthLayout from "@/components/AuthLayout";
import { AuthProviderButtons } from "@/components/auth-provider-buttons";
import { useAuthStore } from "@/lib/auth";
import { api, type AuthProviderStatus } from "@/lib/api";
import { useTranslation } from "@/lib/i18n";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import type { User } from "@/lib/types";

type SignupCopy = ReturnType<typeof useTranslation>["t"]["signup"];

function makeSignupSchema(copy: SignupCopy) {
  return z
    .object({
      name: z.string().min(2, copy.validation.nameMin),
      email: z.string().email(copy.validation.emailInvalid),
      password: z
        .string()
        .min(12, copy.validation.passwordMin)
        .regex(/[A-Z]/, copy.validation.passwordUpper)
        .regex(/[a-z]/, copy.validation.passwordLower)
        .regex(/[0-9]/, copy.validation.passwordDigit),
      confirmPassword: z.string().min(1, copy.validation.confirmRequired),
    })
    .refine((d) => d.password === d.confirmPassword, {
      message: copy.validation.confirmMismatch,
      path: ["confirmPassword"],
    });
}

type SignupFormValues = z.infer<ReturnType<typeof makeSignupSchema>>;

function getErrorMessage(error: unknown, copy: SignupCopy): string {
  if (error instanceof Error) {
    const msg = error.message.toLowerCase();
    if (msg.includes("duplicate") || msg.includes("already") || msg.includes("409")) {
      return copy.error.emailDuplicate;
    }
  }
  return error instanceof Error ? error.message : copy.error.generic;
}

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
function UserIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" />
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

export default function SignupPage() {
  const router = useRouter();
  const { setUser } = useAuthStore();
  const { t } = useTranslation();
  const [serverError, setServerError] = useState<string | null>(null);
  const [isPending, setIsPending] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [authProviders, setAuthProviders] = useState<AuthProviderStatus[]>([]);
  const [signupComplete, setSignupComplete] = useState(false);

  const signupSchema = useMemo(() => makeSignupSchema(t.signup), [t.signup]);

  const form = useForm<SignupFormValues>({
    resolver: zodResolver(signupSchema),
    mode: "onBlur",
    defaultValues: { name: "", email: "", password: "", confirmPassword: "" },
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

  const onSubmit = async (data: SignupFormValues) => {
    setServerError(null);
    setIsPending(true);
    try {
      const user = (await api.signup(data.email, data.password, data.name)) as User;
      if (((user as unknown) as Record<string, unknown>).approval_status === "approved") {
        setUser(user);
        router.push("/dashboard");
      } else {
        setSignupComplete(true);
      }
    } catch (err) {
      setServerError(getErrorMessage(err, t.signup));
    } finally {
      setIsPending(false);
    }
  };

  const hasAuthProviders = authProviders.some((provider) => provider.configured);

  return (
    <AuthLayout>
      <div className="w-full max-w-sm rounded-xl border border-border bg-card p-8 shadow-sm">
        {signupComplete ? (
          <div className="text-center">
            <div className="mx-auto mb-4 flex size-12 items-center justify-center rounded-full bg-amber-100 dark:bg-amber-900/30">
              <svg className="size-6 text-amber-600 dark:text-amber-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="10" /><path d="M12 16v-2" /><path d="M12 8h.01" />
              </svg>
            </div>
            <h2 className="text-xl font-bold">{t.signup.approvalTitle}</h2>
            <p className="mt-3 text-sm text-muted-foreground">
              {t.signup.approvalMessage}
              <br />
              {t.signup.approvalSubmessage}
            </p>
            <Link href="/login">
              <Button variant="outline" className="mt-6 w-full">{t.signup.goToLogin}</Button>
            </Link>
          </div>
        ) : (
        <>
        <div className="mb-8 text-center">
          <h2 className="text-2xl font-bold">{t.signup.title}</h2>
          <p className="mt-2 text-sm text-muted-foreground">
            {t.signup.subtitle.split("AI").map((part, i, arr) => (
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

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} noValidate className="space-y-4">
            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel className="flex items-center gap-1.5">
                    <UserIcon className="size-3.5" />
                    {t.signup.nameLabel}
                  </FormLabel>
                  <FormControl>
                    <div className="relative">
                      <Input type="text" autoComplete="name" placeholder={t.signup.namePlaceholder} {...field} />
                      {field.value && (
                        <button
                          type="button"
                          onClick={() => form.setValue("name", "", { shouldValidate: false })}
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
              name="email"
              render={({ field }) => (
                <FormItem>
                  <FormLabel className="flex items-center gap-1.5">
                    <MailIcon className="size-3.5" />
                    {t.signup.emailLabel}
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
                    {t.signup.passwordLabel}
                  </FormLabel>
                  <FormControl>
                    <div className="relative">
                      <Input
                        type={showPassword ? "text" : "password"}
                        autoComplete="new-password"
                        placeholder="••••••••••••"
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
                  <FormDescription>{t.signup.passwordHint}</FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="confirmPassword"
              render={({ field }) => (
                <FormItem>
                  <FormLabel className="flex items-center gap-1.5">
                    <LockIcon className="size-3.5" />
                    {t.signup.confirmPasswordLabel}
                  </FormLabel>
                  <FormControl>
                    <div className="relative">
                      <Input
                        type={showConfirm ? "text" : "password"}
                        autoComplete="new-password"
                        placeholder="••••••••••••"
                        {...field}
                      />
                      <div className="absolute right-1.5 top-1/2 flex -translate-y-1/2 items-center gap-0.5">
                        {field.value && (
                          <button
                            type="button"
                            onClick={() => form.setValue("confirmPassword", "", { shouldValidate: false })}
                            className="rounded p-0.5 text-muted-foreground transition-colors hover:text-foreground"
                          >
                            <XIcon className="size-3.5" />
                          </button>
                        )}
                        <button
                          type="button"
                          onClick={() => setShowConfirm(!showConfirm)}
                          className="rounded p-0.5 text-muted-foreground transition-colors hover:text-foreground"
                        >
                          {showConfirm ? <EyeOffIcon className="size-3.5" /> : <EyeIcon className="size-3.5" />}
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
              {isPending ? t.signup.submitting : t.signup.submit}
            </Button>
          </form>
        </Form>

        {hasAuthProviders && (
          <>
            <div className="relative my-6">
              <div className="absolute inset-0 flex items-center"><div className="w-full border-t" /></div>
              <div className="relative flex justify-center text-xs uppercase text-muted-foreground">
                <span className="bg-card px-2">{t.signup.or}</span>
              </div>
            </div>

            <AuthProviderButtons providers={authProviders} />
          </>
        )}

        <div className="mt-6 text-center">
          <p className="text-sm text-muted-foreground">
            {t.signup.hasAccount}{" "}
            <Link href="/login" className="text-primary underline underline-offset-4">
              {t.signup.loginLink}
            </Link>
          </p>
        </div>
        </>
        )}
      </div>
    </AuthLayout>
  );
}
