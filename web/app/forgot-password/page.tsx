"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import AuthLayout from "@/components/AuthLayout";
import { api } from "@/lib/api";
import { useTranslation } from "@/lib/i18n";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form";

type ForgotCopy = ReturnType<typeof useTranslation>["t"]["forgotPassword"];

function makeForgotSchema(copy: ForgotCopy) {
  return z.object({
    email: z.string().email(copy.validation.emailInvalid),
  });
}

type ForgotFormValues = z.infer<ReturnType<typeof makeForgotSchema>>;

function MailIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect width="20" height="16" x="2" y="4" rx="2" /><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7" />
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

export default function ForgotPasswordPage() {
  const { t } = useTranslation();
  const [serverError, setServerError] = useState<string | null>(null);
  const [isPending, setIsPending] = useState(false);
  const [sent, setSent] = useState(false);

  const forgotSchema = useMemo(() => makeForgotSchema(t.forgotPassword), [t.forgotPassword]);

  const form = useForm<ForgotFormValues>({
    resolver: zodResolver(forgotSchema),
    defaultValues: { email: "" },
  });

  const onSubmit = async (data: ForgotFormValues) => {
    setServerError(null);
    setIsPending(true);
    try {
      await api.forgotPassword(data.email);
      setSent(true);
    } catch (err) {
      setServerError(err instanceof Error ? err.message : t.forgotPassword.error.generic);
    } finally {
      setIsPending(false);
    }
  };

  return (
    <AuthLayout>
      <div className="w-full max-w-sm rounded-xl border border-border bg-card p-8 shadow-sm">
        <div className="mb-8 text-center">
          <h2 className="text-2xl font-bold">{t.forgotPassword.title}</h2>
          <p className="mt-2 text-sm text-muted-foreground">
            {t.forgotPassword.subtitle}<br />{t.forgotPassword.subtitle2}
          </p>
        </div>

        {sent ? (
          <div className="space-y-4">
            <div className="rounded-md border border-emerald-300 bg-emerald-50 p-4 text-center text-sm text-emerald-800 dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-200">
              {t.forgotPassword.sentMessage}<br />
              {t.forgotPassword.sentMessage2}
            </div>
            <Button className="w-full" asChild>
              <Link href="/reset-password">{t.forgotPassword.resetLink}</Link>
            </Button>
          </div>
        ) : (
          <Form {...form}>
            <form onSubmit={form.handleSubmit(onSubmit)} noValidate className="space-y-4">
              <FormField
                control={form.control}
                name="email"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel className="flex items-center gap-1.5">
                      <MailIcon className="size-3.5" />
                      {t.forgotPassword.emailLabel}
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

              {serverError && (
                <div className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-800 dark:border-red-800 dark:bg-red-950 dark:text-red-200">
                  {serverError}
                </div>
              )}

              <Button type="submit" disabled={isPending} className="w-full">
                {isPending ? t.forgotPassword.submitting : t.forgotPassword.submit}
              </Button>
            </form>
          </Form>
        )}

        <div className="mt-6 text-center">
          <p className="text-sm text-muted-foreground">
            <Link href="/login" className="text-primary underline underline-offset-4">
              {t.forgotPassword.backToLogin}
            </Link>
          </p>
        </div>
      </div>
    </AuthLayout>
  );
}
