'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { api } from '@/lib/api';
import { useAuthStore } from '@/lib/auth';
import { BrandMark } from '@/components/BrandMark';

import { Button } from '@/engine/components/ui/button';
import { Input } from '@/engine/components/ui/input';
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  CardFooter,
} from '@/engine/components/ui/card';
import {
  Form,
  FormField,
  FormItem,
  FormLabel,
  FormControl,
  FormMessage,
  FormDescription,
} from '@/engine/components/ui/form';

const signupSchema = z
  .object({
    name: z.string().min(1, '이름을 입력하세요').max(50, '이름이 너무 깁니다'),
    email: z.string().email('유효한 이메일을 입력하세요'),
    password: z
      .string()
      .min(12, '비밀번호는 최소 12자 이상이어야 합니다')
      .regex(/[a-z]/, '소문자를 포함해야 합니다')
      .regex(/[A-Z]/, '대문자를 포함해야 합니다')
      .regex(/[0-9]/, '숫자를 포함해야 합니다'),
    confirmPassword: z.string().min(1, '비밀번호 확인을 입력하세요'),
  })
  .refine((data) => data.password === data.confirmPassword, {
    message: '비밀번호가 일치하지 않습니다',
    path: ['confirmPassword'],
  });

type SignupFormValues = z.infer<typeof signupSchema>;

function getErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    const msg = error.message.toLowerCase();
    if (
      msg.includes('duplicate') ||
      msg.includes('already') ||
      msg.includes('exists') ||
      msg.includes('conflict') ||
      msg.includes('409')
    ) {
      return '이미 사용 중인 이메일입니다';
    }
    if (msg.includes('password') || msg.includes('weak')) {
      return error.message;
    }
  }
  return error instanceof Error ? error.message : '회원가입 중 오류가 발생했습니다';
}

export default function SignupPage() {
  const router = useRouter();
  const { setUser } = useAuthStore();
  const [serverError, setServerError] = useState<string | null>(null);
  const [isPending, setIsPending] = useState(false);

  const form = useForm<SignupFormValues>({
    resolver: zodResolver(signupSchema),
    mode: 'onBlur',
    defaultValues: { name: '', email: '', password: '', confirmPassword: '' },
  });

  const onSubmit = async (data: SignupFormValues) => {
    setServerError(null);
    setIsPending(true);
    try {
      const user = await api.signup(data.email, data.password, data.name) as import('@/lib/types').User;
      setUser(user);
      router.push('/dashboard');
    } catch (err) {
      setServerError(getErrorMessage(err));
    } finally {
      setIsPending(false);
    }
  };

  return (
    <div
      data-skin="linear"
      className="min-h-screen flex flex-col items-center justify-center bg-surface-page px-6"
    >
      {/* Logo */}
      <BrandMark className="mb-8" />

      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="text-xl font-bold tracking-tight">회원가입</CardTitle>
          <CardDescription>piLoci 계정을 만들어 시작하세요</CardDescription>
        </CardHeader>

        <CardContent>
          <Form {...form}>
            <form onSubmit={form.handleSubmit(onSubmit)} noValidate className="flex flex-col gap-4">
              <FormField
                control={form.control}
                name="name"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>이름</FormLabel>
                    <FormControl>
                      <Input
                        type="text"
                        autoComplete="name"
                        placeholder="홍길동"
                        {...field}
                      />
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
                    <FormLabel>이메일</FormLabel>
                    <FormControl>
                      <Input
                        type="email"
                        autoComplete="email"
                        placeholder="you@example.com"
                        {...field}
                      />
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
                    <FormLabel>비밀번호</FormLabel>
                    <FormControl>
                      <Input
                        type="password"
                        autoComplete="new-password"
                        placeholder="••••••••••••"
                        {...field}
                      />
                    </FormControl>
                    <FormDescription>최소 12자, 대문자·소문자·숫자 포함</FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="confirmPassword"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>비밀번호 확인</FormLabel>
                    <FormControl>
                      <Input
                        type="password"
                        autoComplete="new-password"
                        placeholder="••••••••••••"
                        {...field}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {serverError && (
                <p className="text-sm text-destructive bg-destructive/10 border border-destructive/30 rounded-lg px-3 py-2">
                  {serverError}
                </p>
              )}

              <Button type="submit" disabled={isPending} className="w-full mt-1">
                {isPending ? '가입 중...' : '계정 만들기'}
              </Button>
            </form>
          </Form>
        </CardContent>

        <CardFooter className="justify-center">
          <p className="text-sm text-muted-foreground">
            이미 계정이 있으신가요?{' '}
            <Link href="/login" className="text-brand font-medium hover:underline">
              로그인
            </Link>
          </p>
        </CardFooter>
      </Card>
    </div>
  );
}
