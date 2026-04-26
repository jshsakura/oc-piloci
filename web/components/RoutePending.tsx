type RoutePendingProps = {
  title: string;
  description: string;
  fullScreen?: boolean;
};

export default function RoutePending({ title, description, fullScreen = false }: RoutePendingProps) {
  return (
    <div className={fullScreen ? "flex min-h-screen items-center justify-center bg-background px-6" : "flex min-h-[40vh] items-center justify-center rounded-2xl border bg-card/60 px-6 py-12"}>
      <div className="mx-auto max-w-md text-center">
        <div className="mx-auto mb-4 size-10 animate-spin rounded-full border-2 border-primary/20 border-t-primary" />
        <h2 className="text-lg font-semibold text-foreground">{title}</h2>
        <p className="mt-2 text-sm text-muted-foreground">{description}</p>
      </div>
    </div>
  );
}
