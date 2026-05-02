"use client";

import { useState } from "react";
import Link from "next/link";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import AuthLayout from "@/components/AuthLayout";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form";

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

const forgotSchema = z.object({
  email: z.string().email("유효한 이메일을 입력하세요"),
});

type ForgotFormValues = z.infer<typeof forgotSchema>;

export default function ForgotPasswordPage() {
  const [serverError, setServerError] = useState<string | null>(null);
  const [isPending, setIsPending] = useState(false);
  const [sent, setSent] = useState(false);

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
      setServerError(err instanceof Error ? err.message : "요청 중 오류가 발생했습니다");
    } finally {
      setIsPending(false);
    }
  };

  return (
    <AuthLayout>
      <div className="w-full max-w-sm rounded-xl border border-border bg-card p-8 shadow-sm">
        <div className="mb-8 text-center">
          <h2 className="text-2xl font-bold">비밀번호 찾기</h2>
          <p className="mt-2 text-sm text-muted-foreground">
            가입한 이메일을 입력하시면<br />재설정 토큰을 발급해드립니다
          </p>
        </div>

        {sent ? (
          <div className="space-y-4">
            <div className="rounded-md border border-emerald-300 bg-emerald-50 p-4 text-center text-sm text-emerald-800 shadow-sm dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-200">
              재설정 토큰이 발급되었습니다.<br />
              아래 버튼으로 비밀번호를 변경하세요.
            </div>
            <Button className="w-full" asChild>
              <Link href="/reset-password">비밀번호 재설정하기</Link>
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

              {serverError && (
                <div className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-800 shadow-sm dark:border-red-800 dark:bg-red-950 dark:text-red-200">
                  {serverError}
                </div>
              )}

              <Button type="submit" disabled={isPending} className="w-full">
                {isPending ? "전송 중..." : "재설정 토큰 받기"}
              </Button>
            </form>
          </Form>
        )}

        <div className="mt-6 text-center">
          <p className="text-sm text-muted-foreground">
            <Link href="/login" className="text-primary underline underline-offset-4">
              로그인으로 돌아가기
            </Link>
          </p>
        </div>
      </div>
    </AuthLayout>
  );
}
