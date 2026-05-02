"""OpenCode plugin TypeScript source — served at ``/api/hook/opencode-plugin``.

Auto-installed by ``piloci install`` (or the bash installer) at
``~/.config/opencode/plugins/piloci.ts``. OpenCode's plugin loader
auto-discovers TS/JS files under that directory.

The plugin runs inside OpenCode's own runtime (bun), so the SSE
subscription lives in-process — there is no separate daemon or system
service. When OpenCode exits, the plugin exits with it.

Behaviour mirrors Claude Code's auto-capture:

  * **Catch-up on init** — walks ``$XDG_DATA_HOME/opencode/storage/session``
    and pushes any session not already acknowledged in
    ``~/.config/piloci/opencode-state.json``.
  * **Live via SSE** — subscribes to ``serverUrl/event`` and pushes the
    affected session whenever a turn finishes (``session.idle`` or
    ``session.status`` → idle, plus ``session.compacted`` for forced
    re-curation).

The token comes from ``~/.config/piloci/config.json`` at runtime, so a
revoked-and-reissued token only needs that file refreshed (via
``piloci login``) — the plugin file itself is identical for everyone.
"""

OPENCODE_PLUGIN = """\
// piLoci OpenCode plugin — drops conversations into piLoci memory.
//
// Token + URLs come from ~/.config/piloci/config.json (managed by the
// `piloci` CLI). This file is identical for every user; rotate the token
// in config.json without touching the plugin.

import type { Plugin } from "@opencode-ai/plugin"
import { readFileSync, readdirSync, statSync, mkdirSync, writeFileSync } from "fs"
import { join } from "path"
import { homedir } from "os"

const HOME = homedir()
const CONFIG_PATH = join(HOME, ".config", "piloci", "config.json")
const STATE_PATH = join(HOME, ".config", "piloci", "opencode-state.json")
const STORAGE = join(
  process.env.XDG_DATA_HOME || join(HOME, ".local", "share"),
  "opencode",
  "storage",
)

type Config = {
  token: string
  ingest_url: string
  analyze_url: string
}

type State = Record<string, { sent_at: number; fingerprint: [number, number] }>

function readConfig(): Config | null {
  try {
    const cfg = JSON.parse(readFileSync(CONFIG_PATH, "utf-8")) as Partial<Config>
    if (!cfg.token || !cfg.ingest_url) return null
    return {
      token: cfg.token,
      ingest_url: cfg.ingest_url,
      analyze_url: cfg.analyze_url ?? cfg.ingest_url,
    }
  } catch {
    return null
  }
}

function readState(): State {
  try {
    return JSON.parse(readFileSync(STATE_PATH, "utf-8")) as State
  } catch {
    return {}
  }
}

function writeState(s: State): void {
  try {
    mkdirSync(join(HOME, ".config", "piloci"), { recursive: true })
    writeFileSync(STATE_PATH, JSON.stringify(s))
  } catch {
    // Non-fatal — we'll just re-send next time.
  }
}

function safeReadJson<T = unknown>(path: string): T | null {
  try {
    return JSON.parse(readFileSync(path, "utf-8")) as T
  } catch {
    return null
  }
}

function listSessionMessages(sessionID: string): unknown[] {
  const dir = join(STORAGE, "session", "message", sessionID)
  let files: string[]
  try {
    files = readdirSync(dir).filter((f) => f.endsWith(".json")).sort()
  } catch {
    return []
  }
  const out: unknown[] = []
  for (const f of files) {
    const m = safeReadJson(join(dir, f))
    if (m) out.push(m)
  }
  return out
}

function renderTranscript(messages: unknown[]): string {
  const lines: string[] = []
  for (const raw of messages) {
    const m = raw as { role?: string; parts?: Array<{ type?: string; text?: string }> }
    const role = m.role ?? "user"
    const parts = Array.isArray(m.parts) ? m.parts : []
    const text = parts
      .filter((p) => p && p.type === "text" && typeof p.text === "string" && p.text.length > 0)
      .map((p) => p.text)
      .join("\\n")
      .trim()
    if (text) {
      lines.push(JSON.stringify({ role, content: text }))
    }
  }
  return lines.join("\\n")
}

async function pushSession(sessionID: string, force = false): Promise<boolean> {
  const cfg = readConfig()
  if (!cfg) return false
  const info = safeReadJson<{ directory?: string; cwd?: string }>(
    join(STORAGE, "session", "info", sessionID + ".json"),
  )
  if (!info) return false
  const messages = listSessionMessages(sessionID)
  if (messages.length === 0) return false

  // Fingerprint = (count, latest mtime) so we don't re-send the same turn.
  let latest = 0
  try {
    const dir = join(STORAGE, "session", "message", sessionID)
    for (const f of readdirSync(dir)) {
      if (!f.endsWith(".json")) continue
      const st = statSync(join(dir, f))
      if (st.mtimeMs > latest) latest = st.mtimeMs
    }
  } catch {
    /* ignore — we just lose dedup precision for this push */
  }
  const fingerprint: [number, number] = [messages.length, Math.floor(latest)]

  const state = readState()
  if (!force) {
    const prior = state[sessionID]
    if (
      prior &&
      Array.isArray(prior.fingerprint) &&
      prior.fingerprint[0] === fingerprint[0] &&
      prior.fingerprint[1] === fingerprint[1]
    ) {
      return false
    }
  }

  const transcript = renderTranscript(messages)
  if (!transcript) return false

  try {
    const resp = await fetch(cfg.ingest_url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: "Bearer " + cfg.token,
      },
      body: JSON.stringify({
        cwd: info.directory ?? info.cwd ?? HOME,
        sessions: [{ session_id: sessionID, transcript, source: "opencode" }],
      }),
    })
    if (!resp.ok) {
      // 401 means token revoked — surface it on the next CLI ``piloci login``.
      return false
    }
  } catch {
    return false
  }

  state[sessionID] = { sent_at: Date.now(), fingerprint }
  writeState(state)
  return true
}

async function catchUp(): Promise<void> {
  const dir = join(STORAGE, "session", "info")
  let files: string[]
  try {
    files = readdirSync(dir).filter((f) => f.endsWith(".json"))
  } catch {
    return
  }
  for (const f of files) {
    const sid = f.slice(0, -".json".length)
    await pushSession(sid)
  }
}

async function* sseEvents(url: string): AsyncGenerator<{ type: string; properties?: any }> {
  while (true) {
    try {
      const resp = await fetch(url, {
        headers: { Accept: "text/event-stream", "Cache-Control": "no-cache" },
      })
      if (!resp.ok || !resp.body) {
        await new Promise((r) => setTimeout(r, 5000))
        continue
      }
      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buf = ""
      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const blocks = buf.split("\\n\\n")
        buf = blocks.pop() ?? ""
        for (const block of blocks) {
          const dataLine = block.split("\\n").find((l) => l.startsWith("data: "))
          if (!dataLine) continue
          try {
            yield JSON.parse(dataLine.slice("data: ".length))
          } catch {
            // ignore malformed event
          }
        }
      }
    } catch {
      await new Promise((r) => setTimeout(r, 5000))
    }
  }
}

const PilociPlugin: Plugin = async (ctx) => {
  // Live SSE subscription runs in the background for the lifetime of OpenCode.
  // We don't return any typed Hooks because piLoci captures via OpenCode's bus
  // events, not its message-transform pipeline.
  ;(async () => {
    await catchUp()
    const eventUrl = new URL("/event", ctx.serverUrl).toString()
    for await (const ev of sseEvents(eventUrl)) {
      const t = ev.type
      const props = ev.properties ?? {}
      if (t === "session.idle") {
        if (props.sessionID) await pushSession(String(props.sessionID))
      } else if (t === "session.status") {
        const status = props.status
        if (status && typeof status === "object" && status.type === "idle" && props.sessionID) {
          await pushSession(String(props.sessionID))
        }
      } else if (t === "session.compacted") {
        if (props.sessionID) await pushSession(String(props.sessionID), true)
      }
    }
  })().catch(() => {
    // Plugin background loop should never crash the host. Swallow + done.
  })

  return {}
}

export default PilociPlugin
"""
