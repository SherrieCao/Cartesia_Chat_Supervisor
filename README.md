# Taniku Izakaya — Voice Phone Host

A voice agent that acts as the **phone host for Taniku Izakaya**, a family-owned,
Asian-owned, authentic Japanese izakaya in San Francisco. It takes inbound calls, answers
questions, looks up the menu, takes reservations, gives wait-time guidance, and transfers
callers to the owner's line — **bilingually in English and Japanese**.

Built on Cartesia's [`line`](https://docs.cartesia.ai/line/sdk/overview) SDK, this example
is intentionally broad: it exercises a wide range of SDK functionality in one coherent app.

## Architecture

A two-tier design wrapped in an `AgentClass`:

- **Host** (fast, bilingual): `Qwen3-235B` on Together AI (Japanese-strong), with
  `Claude Haiku 4.5` as a fallback. Handles the conversation and all the tools.
- **Supervisor** (deep reasoning, consulted in the background): `DeepSeek-V3` on Together
  AI, with `Claude Opus 4.8` as a fallback. Repurposed as a restaurant operations/events
  expert for complex inquiries (private events, catering, detailed allergen/dietary
  questions).

```text
Caller ──► Host (Qwen3-235B)
              ├─ look_up_menu / knowledge_base   (menu, prices, dietary info)
              ├─ check_wait_time                 (tiny space → small groups wait less)
              ├─ book_reservation                (captures + logs a reservation)
              ├─ transfer_call                   (→ owner's line)
              ├─ web_search                       (parking, transit, "near me")
              ├─ end_call                         (graceful hangup)
              └─ ask_supervisor (background) ──►  Supervisor (DeepSeek-V3)
                                                  events / catering / allergens
```

## SDK features exercised

| Feature | Where |
|---|---|
| `AgentClass` wrapping multiple `LlmAgent`s | `ChatSupervisorAgent` |
| Multi-provider models + **cross-provider fallbacks** | Together (Qwen/DeepSeek) → Anthropic (Haiku/Opus) |
| Background nested-agent tool | `ask_supervisor` (`@loopback_tool(is_background=True)`) |
| Custom `@loopback_tool`s | `look_up_menu`, `book_reservation`, `check_wait_time` |
| Built-in `transfer_call` (pinned mode) | transfer to `OWNER_PHONE_NUMBER` |
| Built-in `end_call` (custom description) | graceful hangup |
| Built-in `web_search` | local logistics questions |
| Native `knowledge_base` tool | menu/FAQ lookup when deployed (see below) |
| `LlmConfig.from_call_request` | runtime per-call prompt override in `get_agent` |
| `http_server_tool` | commented reservation-backend template in `main.py` |
| Bilingual `introduction` + `system_prompt` | English + Japanese host |

`send_dtmf` and `voicemail` are intentionally omitted — they don't fit an inbound host.

## Menu / restaurant data — two knowledge-base paths

The restaurant's menu (~35 items) and facts live in **`restaurant_data.py`** as structured
Python data, not in the system prompt. Small, stable facts (happy hour, popular items,
policies) are summarized into the prompt; the large, changing menu is fetched on demand.
Two KB paths are wired up:

1. **Local (`look_up_menu` tool)** — queries `restaurant_data.py` directly. Works in local
   dev with no extra setup. This is the default runnable path.
2. **Native Cartesia `knowledge_base` tool** — queries documents hosted on the Cartesia
   platform. To use it in a deployed agent, upload the generated docs in **`knowledge/`**
   (`menu.md`, `faq.md`) to your agent's knowledge base. Locally it's a harmless no-op.

The `knowledge/` markdown is generated from `restaurant_data.py` — edit the data there
(the single source of truth), then regenerate the docs and re-upload them.

## Configuration

Set keys and the transfer number in `.env` (auto-loaded by the SDK):

```bash
TOGETHERAI_API_KEY=...      # primary provider (Together AI) for both tiers
ANTHROPIC_API_KEY=...       # required for the Haiku/Opus fallbacks
OWNER_PHONE_NUMBER=+14155550123   # E.164; the owner's line for transfers
```

`[TODO]` placeholders in `restaurant_data.py` (operating hours, street address, full
dessert menu) and `OWNER_PHONE_NUMBER` should be filled with the real values.

## Running

```bash
uv run python main.py
```

Then place a call via the [Calls API](https://docs.cartesia.ai/line/integrations/calls-api)
or your local runner. Try:

- "What ramen do you have?" / "Do you have anything vegetarian?" / "What's popular?"
- "I'd like a table for two this Friday at 7:30." (reservation flow)
- "How long is the wait for a group of six?"
- "Can you connect me to the owner?"  → transfer
- Switch to Japanese mid-call — the host follows.

## Example conversations

> Caller: "何が人気ですか？" (What's popular?)
> Host: "一番人気は肉ラーメンです。甘辛いビーフのラーメンで…" (looks up the menu, answers in Japanese)

> Caller: "We'd like to book the whole place for a birthday, about 20 people."
> Host: *acknowledges, calls `ask_supervisor` in the background, then* "For a group that
> size in our cozy space, here's what I'd suggest… and let me connect you with the owner to
> lock in the date."
