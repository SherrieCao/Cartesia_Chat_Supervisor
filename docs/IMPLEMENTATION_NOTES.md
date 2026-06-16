# Taniku Izakaya Voice Host — Implementation Notes

A reference for what this project is, which Cartesia **line** SDK features it uses, and —
most importantly — which capabilities the SDK does **not** provide that we had to build or
work around ourselves.

---

## 1. Project overview

A **bilingual (English + Japanese) phone host** named **Ken** for *Taniku Izakaya*, a
family-owned, Asian-owned Japanese izakaya in San Francisco. It answers inbound calls and:

- **Answers questions** about the menu, hours, location, policies, and atmosphere.
- **Looks up the menu** (dishes, prices, dietary tags) from a structured data source.
- **Takes reservations** (captures the details and logs them).
- **Gives wait-time guidance** (the space is tiny, so smaller groups wait less).
- **Escalates hard questions** — large-party/private events, catering, detailed
  allergen/dietary reasoning — to a more powerful "supervisor" model **in the background**.
- **Mirrors the caller's language**, switching between English and Japanese.

### Architecture — two tiers in one `AgentClass`

```text
Caller ──► Host (Claude Haiku 4.5, Qwen3-235B fallback)
              ├─ look_up_menu / knowledge_base   menu, prices, dietary info
              ├─ check_wait_time                 tiny space → small groups wait less
              ├─ book_reservation                captures + logs a reservation
              ├─ transfer_call                   hand off to the owner's line (rare)
              ├─ web_search                       parking, transit, "near me"
              ├─ end_call                         graceful hangup
              └─ ask_supervisor (background) ──►  Supervisor (Claude Opus 4.8,
                                                  DeepSeek-V3 fallback):
                                                  events / catering / allergens
```

Escalation is two-pronged: hard *questions* go to `ask_supervisor` (a background consult,
the default for anything complex), while `transfer_call` hands the caller to the owner's
line — used sparingly, only for an explicit request for a person, a complaint, or a firm
owner-only decision.

### Files

| File | Purpose |
|---|---|
| `main.py` | The agent: `ChatSupervisorAgent`, tools, prompts, `get_agent`, `VoiceAgentApp`. |
| `restaurant_data.py` | Local knowledge base — menu + facts as structured Python + search helpers. |
| `knowledge/menu.md`, `knowledge/faq.md` | Markdown generated from `restaurant_data.py`, for the hosted KB. |
| `upload_knowledge.py` | Standalone script to upload the docs to Cartesia's hosted knowledge base via REST. |
| `pyproject.toml` | Dependencies (`cartesia-line`) + packaging (`py-modules`). |
| `.env` / `.env.example` | API keys (auto-loaded by the SDK). |

### Models

| Tier | Primary | Fallback |
|---|---|---|
| Host (fast, bilingual) | `anthropic/claude-haiku-4-5` | `together_ai/Qwen/Qwen3-235B-A22B-Instruct-2507-tput` |
| Supervisor (deep reasoning) | `anthropic/claude-opus-4-8` | `together_ai/deepseek-ai/DeepSeek-V3` |

---

## 2. Cartesia line SDK functions used

Everything here is imported directly from the SDK and used as documented.

| SDK symbol | Imported from | How we use it |
|---|---|---|
| `AgentClass` | `line.agent` | Base class for `ChatSupervisorAgent` (wraps two `LlmAgent`s). |
| `TurnEnv` | `line.agent` | Type for the per-turn env in `process()`. |
| `LlmAgent` | `line.llm_agent` | The host and the supervisor agents. |
| `LlmConfig` | `line.llm_agent` | System prompt, introduction, fallbacks per agent. |
| `LlmConfig.from_call_request` | `line.llm_agent` | Per-call runtime override of prompt/introduction in `get_agent`. |
| `loopback_tool` | `line.llm_agent` | Decorator for our custom tools; `is_background=True` for `ask_supervisor`. |
| `end_call` | `line.llm_agent` | Built-in hangup tool (custom description). |
| `web_search` | `line.llm_agent` | Built-in web search (DuckDuckGo / native). |
| `transfer_call` | `line.llm_agent` | Built-in; pinned to `OWNER_PHONE_NUMBER` to hand a caller to the owner (used sparingly). |
| `knowledge_base` | `line.llm_agent` | Built-in tool that queries the agent's hosted documents. |
| `ToolEnv` | `line.llm_agent` | First param type on every custom tool. |
| `AgentSendText` | `line.events` | Read supervisor output text in `ask_supervisor`. |
| `UserTextSent` | `line.events` | Build the event (with history) passed to the supervisor. |
| `CallEnded` | `line.events` | Trigger cleanup of both agents. |
| `InputEvent` / `OutputEvent` | `line.events` | Type the `process()` signature. |
| `VoiceAgentApp` | `line.voice_agent_app` | The app object; `app.run()`. |
| `AgentEnv` / `CallRequest` | `line.voice_agent_app` | Types for the `get_agent` factory. |

**Built-in tools available but not used:** `send_dtmf`, `voicemail` (outbound-oriented),
`agent_as_handoff`, `http_server_tool` (kept only as a commented reservation-backend
template), `mcp_tool`.

---

## 3. Ours vs. theirs

### 3a. Theirs — provided by the SDK, used as-is

- The agent runtime (`LlmAgent`, `AgentClass`, event loop, `VoiceAgentApp`).
- Multi-provider model routing via LiteLLM (any `provider/model` string).
- Built-in tools: `end_call`, `web_search`, `transfer_call`, `knowledge_base` (query side).
- Custom-tool decorators (`loopback_tool`, incl. the background variant).
- Runtime per-call config (`from_call_request` / `CallRequest`).
- Deployment infra (`cartesia deploy`), env-var management, the Calls API, and TTS/STT.

### 3b. Ours — application code we had to write (expected; the SDK ships none of this)

- **Domain tools**: `look_up_menu`, `book_reservation`, `check_wait_time` — the SDK provides
  **no** reservation/booking or any domain tool, so these are necessarily ours.
- **Two-tier orchestration**: `ChatSupervisorAgent` + the background `ask_supervisor`
  consult. The SDK gives the primitives (`AgentClass`, background `loopback_tool`); the
  wiring and "host consults supervisor, relays the answer" logic is ours.
- **All prompts**: Ken's persona, bilingual behavior, routing rules, supervisor prompt.
- **All content/data**: the menu and facts in `restaurant_data.py` and `knowledge/`.

### 3c. ⭐ What's MISSING from theirs — gaps we had to fill or work around

This is the important part: capabilities our use case needs that the SDK does **not**
provide out of the box.

1. **Cross-provider fallback with a per-model API key** *(the core workaround)*
   - **Need:** Claude (Anthropic) primary, Together AI fallback — two providers, two keys.
   - **Gap:** `LlmConfig.fallbacks` is typed `List[str]` with a **single** `api_key` on the
     agent. There is **no per-fallback key field**, and `LlmAgent` *requires* an explicit
     `api_key` that LiteLLM then reuses for string fallbacks — so a `together_ai/...` string
     fallback gets called with the Anthropic key and fails to authenticate. This caveat is
     **undocumented**.
   - **Our workaround:** pass fallbacks as **dicts** — `{"model": ..., "api_key": together_key}`
     — exploiting that the SDK forwards `fallbacks` straight to LiteLLM, whose dict form
     overrides the key per model. (`main.py`, supervisor + host `LlmConfig`.)

2. **Knowledge-base document upload** *(no tooling provided)*
   - **Need:** put the menu/FAQ into the hosted `knowledge_base`.
   - **Gap:** the SDK provides the *query* tool and a dashboard, but **no CLI command and no
     SDK helper to upload documents** — only a raw REST API.
   - **Our work:** `upload_knowledge.py`, a standalone `urllib` client hitting
     `POST /agents/folders`, `POST /agents/documents`, `PATCH /agents/folders/{id}`
     (idempotent; reads the key from `CARTESIA_API_KEY`).

3. **A knowledge base that works in local dev** *(native one is platform-only)*
   - **Gap:** the native `knowledge_base` is empty until docs are uploaded **and** the agent
     is deployed — it's a no-op locally.
   - **Our work:** `restaurant_data.py` + the `look_up_menu` tool — a second, local KB so the
     host can answer menu questions in dev and without a platform round-trip.

4. **Bilingual voice is "primitives, not a feature"** *(we use even less than they offer)*
   - **Gap:** the SDK has **no automatic language detection / switching**. It exposes levers
     (per-call `language`/`voice_id` via `PreCallResult`; mid-call via the `AgentUpdateCall`
     event; a language-handoff pattern), but the switching logic is the developer's.
   - **Our state:** our bilingual behavior is **prompt-only** — the model emits Japanese text
     and TTS speaks it with whatever single voice/language the call was set up with. We do
     **not** use `AgentUpdateCall` to switch the TTS language/voice per language. Adequate for
     a host, but not "true" bilingual TTS — an available capability we've left on the table.

5. **No persistence for actions** *(stubs only)*
   - **Gap:** `book_reservation` (and any "take a message" need) have no backend — the SDK
     offers no storage. We log reservations server-side as a stub; a real deployment must
     point these at an external system (the SDK's `http_server_tool` is the documented seam).

6. **Deployment gotchas the docs don't surface** *(friction we engineered around)*
   - **`uv.lock` must match `pyproject.toml`** — a stale lock fails the build's locked
     `uv sync` (undocumented; cost us a `build_error`).
   - **The build imports your source files**, so **every top-level `.py` must be
     import-safe** — a module that reads required env or calls `sys.exit()` at import aborts
     the build (this bit `upload_knowledge.py`).
   - **`py-modules`** in `pyproject.toml` — we list `["main", "restaurant_data"]` so the
     extra module ships; the docs only mention `main.py` + `pyproject.toml`.
   - **`cartesia.toml`** exists in the repo but is **undocumented**; real linkage lives in
     `.cartesia/config.toml`.

### Headline

The genuinely **non-provided, necessary** work is three things:
1. **per-key cross-provider fallback** (undocumented workaround around a real limitation),
2. **knowledge-base uploading** (no CLI/SDK path — we wrote a REST client), and
3. **a local KB** to make menu knowledge usable off-platform.

Everything else is either standard SDK usage or expected application code (prompts, data,
and domain tools — of which the SDK ships none). Secondary gaps worth knowing: **bilingual
TTS is prompt-only** (the SDK's language-switching levers are unused), **no persistence** for
reservations/messages, and several **undocumented deployment constraints**.

---

## Sources (SDK behavior / gaps)

- SDK overview & agents: <https://docs.cartesia.ai/line/sdk/overview>, <https://docs.cartesia.ai/line/sdk/agents>
- Tools: <https://docs.cartesia.ai/line/sdk/tools>
- Patterns (chat-supervisor, handoffs): <https://docs.cartesia.ai/line/sdk/patterns>
- Events (`AgentUpdateCall`): <https://docs.cartesia.ai/line/sdk/events>
- Knowledge base: <https://docs.cartesia.ai/line/knowledge-base>; documents API: <https://docs.cartesia.ai/api-reference/agents/documents>
- CLI: <https://docs.cartesia.ai/line/cli>; deployment: <https://docs.cartesia.ai/line/infrastructure/deployments>
- `LlmConfig.fallbacks` typing: `line/llm_agent/config.py` in <https://github.com/cartesia-ai/line>
