"use client";

import { Suspense, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import AuthLayout from "@/components/AuthLayout";
import { api } from "@/lib/api";
import { useTranslation } from "@/lib/i18n";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Form, FormControl, FormDescription, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form";

type ResetCopy = ReturnType<typeof useTranslation>["t"]["resetPassword"];

function makeResetSchema(copy: ResetCopy) {
  return z
    .object({
      token: z.string().min(1, copy.validation.tokenRequired),
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

type ResetFormValues = z.infer<ReturnType<typeof makeResetSchema>>;

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

function ResetPasswordForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { t } = useTranslation();
  const [serverError, setServerError] = useState<string | null>(null);
  const [isPending, setIsPending] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);

  const resetSchema = useMemo(() => makeResetSchema(t.resetPassword), [t.resetPassword]);

  const form = useForm<ResetFormValues>({
    resolver: zodResolver(resetSchema),
    mode: "onBlur",
    defaultValues: {
      token: searchParams.get("token") ?? "",
      password: "",
      confirmPassword: "",
    },
  });

  const onSubmit = async (data: ResetFormValues) => {
    setServerError(null);
    setIsPending(true);
    try {
      await api.resetPassword(data.token, data.password);
      router.push("/login?reset=1");
    } catch (err) {
      setServerError(err instanceof Error ? err.message : t.resetPassword.error.generic);
    } finally {
      setIsPending(false);
    }
  };

  return (
    <AuthLayout>
      <div className="w-full max-w-sm rounded-xl border border-border bg-card p-8 shadow-sm">
        <div className="mb-8 text-center">
          <h2 className="text-2xl font-bold">{t.resetPassword.title}</h2>
          <p className="mt-2 text-sm text-muted-foreground">
            {t.resetPassword.subtitle}
          </p>
        </div>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} noValidate className="space-y-4">
            <FormField
              control={form.control}
              name="token"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{t.resetPassword.tokenLabel}</FormLabel>
                  <FormControl>
                    <Input type="text" placeholder={t.resetPassword.tokenPlaceholder} {...field} />
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
                    {t.resetPassword.newPasswordLabel}
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
                  <FormDescription>{t.resetPassword.passwordHint}</FormDescription>
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
                    {t.resetPassword.confirmPasswordLabel}
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
              {isPending ? t.resetPassword.submitting : t.resetPassword.submit}
            </Button>
          </form>
        </Form>

        <div className="mt-6 text-center">
          <p className="text-sm text-muted-foreground">
            <Link href="/login" className="text-primary underline underline-offset-4">
              {t.resetPassword.backToLogin}
            </Link>
          </p>
        </div>
      </div>
    </AuthLayout>
  );
}

function ResetPasswordFallback() {
  const { t } = useTranslation();
  return (
    <div className="flex min-h-screen items-center justify-center">
      <p className="text-muted-foreground">{t.resetPassword.loading}</p>
    </div>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={<ResetPasswordFallback />}>
      <ResetPasswordForm />
    </Suspense>
  );
}
