# piLoci Design Harness

piLoci UI should feel like a calm memory infrastructure product: clear, spatial, low-noise, and trustworthy. Use the shared `pi-*` classes in `app/globals.css` before inventing new page-level styling.

## Visual Rules

1. Use `pi-app-bg` once at the app shell root. Do not add competing page background gradients.
2. Every authenticated page starts with `pi-page-hero`: eyebrow, title, one short description.
3. Use `pi-panel` for large content surfaces and `pi-metric-card` for KPI cards.
4. Use `pi-table-shell` for admin tables. Tables should have uppercase muted headers and quiet row hover states.
5. Use `pi-chip` for compact stats and metadata. Avoid loud badges unless the state needs action.
6. Keep one accent: `primary`. Status colors are only for state labels, warnings, and destructive actions.
7. Prefer soft rounded forms: `rounded-full` for filters and search, `rounded-[1.35rem]` for panels.
8. Use subtle motion only: small hover lift on cards, no bouncing or decorative animation in admin flows.
9. Use logical spacing classes (`ms-*`, `me-*`) in new code instead of `ml-*`, `mr-*`.
10. Do not create one-off hardcoded shadows. Use `--pi-shadow` or `--pi-shadow-sm` through the harness classes.

## Page Pattern

```tsx
<AppShell>
  <div className="pi-page">
    <section className="pi-page-hero">
      <p className="pi-eyebrow">Area label</p>
      <h1 className="pi-title mt-2">Page title</h1>
      <p className="pi-subtitle">One sentence explaining the page.</p>
    </section>

    <section className="grid gap-3 sm:grid-cols-3">
      <div className="pi-metric-card">...</div>
    </section>

    <section className="pi-panel p-3">...</section>
  </div>
</AppShell>
```

## Current Baselines

- `components/AppShell.tsx` owns the authenticated shell background and glass navigation.
- `app/dashboard/page.tsx` and `components/DashboardSummaryPanels.tsx` are the user dashboard baseline.
- `app/admin/users/page.tsx` is the admin console baseline.
- `components/ProjectListView.tsx` and `app/projects/page.tsx` are the project workspace baseline.
