# @piloci/sdk

TypeScript SDK for the [piLoci](https://github.com/Sisyphus-Junior/piloci) self-hosted memory server.

Wraps the piLoci REST API with a typed, zero-dependency client that runs on Node 18+, Bun, Deno, and modern browsers.

## Install

Not on npm yet — install directly from the repo:

```sh
npm i ./clients/js
# or
pnpm add ./clients/js
```

Once published:

```sh
npm i @piloci/sdk
```

## Get a token

Open your piLoci instance → **Settings → Tokens**. Create a project-scoped token for memory/recall/recommend/contradict, or a user-scoped token for whoami and projects.

## Usage

```ts
import { Piloci } from "@piloci/sdk";

const client = new Piloci({ baseUrl: "https://my.piloci", token: "JWT.xxx" });

// Save a memory
await client.memory.save({ content: "we decided to use argon2id", tags: ["security"] });

// Search memories
const result = await client.recall({ query: "what auth did we pick?", limit: 5 });
for (const m of result.memories) console.log(m.excerpt);

// List projects
const { projects } = await client.projects.list();

// Who am I?
const me = await client.whoami();
console.log(me.userId, me.email);
```

## TypeScript-first

All methods are strictly typed. The API accepts camelCase; the SDK converts to snake_case on the wire automatically.

```ts
import { Piloci, PilociPermissionError } from "@piloci/sdk";

try {
  await client.recall({ query: "test" });
} catch (e) {
  if (e instanceof PilociPermissionError) {
    // JWT is missing project_id — generate a project-scoped token in /settings
  }
}
```

## Project-scoped tokens

`memory`, `recall`, `recommend`, and `contradict` require a JWT that carries `project_id`. The server returns 403 otherwise, which the SDK surfaces as `PilociPermissionError`. Generate the right token in **Settings → Tokens**.

## Error classes

| Class | HTTP status |
|---|---|
| `PilociAuthError` | 401 — token missing, expired, or invalid |
| `PilociPermissionError` | 403 — project-scoped token required |
| `PilociValidationError` | 422 — request body failed validation |
| `PilociServerError` | 5xx — server-side failure |
| `PilociError` | anything else |

## Optional project header

Pass a `project` string as the second argument to `recall`, `recommend`, and `contradict` to send `X-Piloci-Project` for forward compatibility:

```ts
await client.recall({ query: "auth" }, "my-project-slug");
```

## Configuration

```ts
const client = new Piloci({
  baseUrl: "https://my.piloci", // required
  token: "JWT.xxx",            // required — from /settings → Tokens
  timeoutMs: 30_000,           // optional, default 30 s; set 0 to disable
});
```

## Node version

Node 18+ required (uses native `fetch` and `AbortSignal.timeout`). No polyfills included.
