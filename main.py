import logging
import os
from typing import Annotated, AsyncIterable, Optional

from line.agent import AgentClass, TurnEnv
from line.events import (
    AgentSendText,
    CallEnded,
    InputEvent,
    OutputEvent,
    UserTextSent,
)
from line.llm_agent import (
    LlmAgent,
    LlmConfig,
    ToolEnv,
    end_call,
    knowledge_base,
    loopback_tool,
    web_search,
)
from line.voice_agent_app import AgentEnv, CallRequest, VoiceAgentApp

import restaurant_data as rd

logger = logging.getLogger("taniku_izakaya")

# Models (LiteLLM ids). Anthropic (Claude) is primary; Together AI (together_ai/
# prefix) is the cross-provider fallback.
# Fast host tier: Claude Haiku 4.5, falling back to Qwen3-235B (strong in Japanese).
CHAT_MODEL = "anthropic/claude-haiku-4-5"
CHAT_FALLBACK = "together_ai/Qwen/Qwen3-235B-A22B-Instruct-2507-tput"
# Supervisor tier: Claude Opus 4.8 for deep reasoning, falling back to DeepSeek-V3.
SUPERVISOR_MODEL = "anthropic/claude-opus-4-8"
SUPERVISOR_FALLBACK = "together_ai/deepseek-ai/DeepSeek-V3"


class ChatSupervisorAgent(AgentClass):
    """The phone host for Taniku Izakaya, a Japanese izakaya in San Francisco.

    A two-tier voice agent:
    - A fast, bilingual (English + Japanese) "host" model (Claude Haiku 4.5,
      Qwen3-235B fallback) takes the call, answers questions, looks up the menu,
      takes reservations, and gives wait-time guidance.
    - A "supervisor" model (Claude Opus 4.8, DeepSeek-V3 fallback) is consulted in
      the background for complex inquiries: large-party / private-event logistics,
      catering, and detailed allergen/dietary reasoning. This is the only
      escalation path — the host has no call-transfer tool.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        call_request: Optional[CallRequest] = None,
    ):
        self._api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self._current_event: Optional[InputEvent] = None

        # Together AI fallbacks must carry their own key. LiteLLM reuses the
        # primary (Anthropic) api_key for plain-string fallbacks, so a string
        # fallback to a Together model would fail to authenticate. Passing the
        # fallback as a dict lets LiteLLM override the key per-model.
        together_key = os.getenv("TOGETHERAI_API_KEY")

        # Create the supervisor agent: Opus 4.8 (Anthropic), DeepSeek-V3 fallback.
        self._supervisor = LlmAgent(
            model=SUPERVISOR_MODEL,
            api_key=self._api_key,
            config=LlmConfig(
                system_prompt=SUPERVISOR_SYSTEM_PROMPT,
                fallbacks=[{"model": SUPERVISOR_FALLBACK, "api_key": together_key}],
            ),
        )

        # The host tools. Two knowledge-base paths are wired up:
        #   - look_up_menu: local, works in dev (queries restaurant_data.py)
        #   - knowledge_base: Cartesia-hosted, returns content once menu/FAQ docs
        #     are uploaded to the deployed agent (no-op locally).
        # There is intentionally no transfer_call: ask_supervisor is the only
        # escalation path.
        host_tools = [
            self.look_up_menu,
            self.book_reservation,
            self.check_wait_time,
            self.ask_supervisor,
            web_search,
            end_call(
                description="End the call only after the caller is finished and "
                "you have said goodbye."
            ),
            knowledge_base,
        ]

        # Build the host config. from_call_request lets a caller override the
        # system prompt / introduction at call time (multi-tenant / A-B testing);
        # otherwise our Taniku Izakaya defaults are used.
        if call_request is not None:
            host_config = LlmConfig.from_call_request(
                call_request,
                fallback_system_prompt=CHAT_SYSTEM_PROMPT,
                fallback_introduction=CHAT_INTRODUCTION,
                fallbacks=[{"model": CHAT_FALLBACK, "api_key": together_key}],
            )
        else:
            host_config = LlmConfig(
                system_prompt=CHAT_SYSTEM_PROMPT,
                introduction=CHAT_INTRODUCTION,
                fallbacks=[{"model": CHAT_FALLBACK, "api_key": together_key}],
            )

        # Create the host agent: Haiku 4.5 (Anthropic), Qwen3-235B fallback.
        self._chatter = LlmAgent(
            model=CHAT_MODEL,
            api_key=self._api_key,
            tools=host_tools,
            config=host_config,
        )

        self._answering_question = False

    async def process(self, env: TurnEnv, event: InputEvent) -> AsyncIterable[OutputEvent]:
        self._input_event = event

        # Handle cleanup on call end
        if isinstance(event, CallEnded):
            await self._cleanup()
            return

        # Delegate to the chatter
        async for output in self._chatter.process(env, event):
            yield output

    @loopback_tool
    async def look_up_menu(
        self,
        ctx: ToolEnv,
        section: Annotated[
            Optional[str],
            "A menu section to read in full: zensai, kushiyaki, ramen, toppings, "
            "donburi, or desserts.",
        ] = None,
        query: Annotated[
            Optional[str],
            "A keyword to search for, e.g. a dish name, an ingredient, or a "
            "dietary tag like 'vegetarian', 'spicy', or 'popular'.",
        ] = None,
    ) -> str:
        """Look up Taniku Izakaya's menu — dishes, prices, descriptions, and
        dietary info. Always use this for menu questions; never guess dish names
        or prices. Pass a `section` to read a whole part of the menu, or a
        `query` to search across the menu (e.g. "vegetarian", "ramen", "niku").
        """
        if section:
            return rd.format_menu_section(section)
        if query:
            q = query.lower()
            if "popular" in q or "favorite" in q or "best" in q:
                return rd.popular_items()
            return rd.search_menu(query)
        # No args: give an overview the host can offer to expand.
        sections = ", ".join(rd.SECTION_TITLES.values())
        return f"Our menu has these sections: {sections}.\n{rd.FACTS['popular']}"

    @loopback_tool
    async def book_reservation(
        self,
        ctx: ToolEnv,
        name: Annotated[str, "The caller's name for the reservation"],
        date: Annotated[str, "Reservation date, e.g. 2026-06-20 or 'this Friday'"],
        time: Annotated[str, "Reservation time, e.g. '7:30 PM'"],
        party_size: Annotated[int, "Number of guests"],
        phone: Annotated[str, "A callback phone number"],
        notes: Annotated[
            str, "Any special requests: allergies, occasion, seating preferences"
        ] = "",
    ) -> str:
        """Record a reservation for Taniku Izakaya. Before calling this, collect
        the name, date, time, party size, and a callback number, and read them
        back to the caller to confirm. For very large parties or private events,
        offer to connect them to the owner instead.
        """
        # Stub: log the reservation server-side. Swap this for a real backend by
        # POSTing to your reservation system (see the http_server_tool template
        # at the bottom of this file).
        logger.info(
            "RESERVATION | name=%s | date=%s | time=%s | party=%s | phone=%s | notes=%s",
            name, date, time, party_size, phone, notes or "-",
        )
        return (
            f"Thanks, {name} — I've noted a reservation for {party_size} on "
            f"{date} at {time}. We'll call {phone} if anything changes. "
            "We look forward to seeing you at Taniku Izakaya!"
        )

    @loopback_tool
    async def check_wait_time(
        self,
        ctx: ToolEnv,
        party_size: Annotated[int, "Number of guests in the party"],
    ) -> str:
        """Give wait-time guidance based on party size. Taniku Izakaya is a tiny,
        cozy space, so smaller groups are seated sooner and large groups may wait
        longer. Use this when callers ask about waits or walk-in availability.
        """
        if party_size <= 2:
            return (
                "We're a small, cozy spot, so parties of one or two usually have "
                "the shortest wait — often seated fairly quickly, especially "
                "outside the dinner rush."
            )
        if party_size <= 4:
            return (
                "For a party of three or four there may be a short wait during "
                "busy hours, but it usually moves quickly. Coming a bit before or "
                "after the dinner rush helps."
            )
        return (
            "We're a tiny space, so larger groups can have a longer wait and "
            "seating isn't guaranteed for walk-ins. For a party this size I'd "
            "recommend a reservation, and I can connect you with the owner to "
            "arrange it if you'd like."
        )

    @loopback_tool(is_background=True)
    async def ask_supervisor(
        self,
        ctx: ToolEnv,
        question: Annotated[
            str, "The complex restaurant question requiring careful reasoning"
        ],
    ) -> AsyncIterable[str]:
        """Consult a more powerful reasoning model for complex inquiries.

        Use this for questions that need careful, expert thought:
        - Large-party or private-event / buyout planning and logistics
        - Catering or custom multi-course menu requests
        - Detailed allergen, dietary, or cross-contamination questions
        - Anything where accuracy matters and you're genuinely uncertain

        It runs in the background, so acknowledge the caller while you wait, and
        never mention that another model is involved. The supervisor has the full
        conversation history for context.
        """
        if self._answering_question:
            return
        self._answering_question = True

        history = self._input_event.history if self._input_event else []
        yield "Let me look into that for you — one moment."

        # Create a UserTextSent event with the supervisor prompt
        supervisor_event = UserTextSent(content=question, history=history + [UserTextSent(content=question)])

        # Get response from supervisor
        full_response = ""
        try:
            async for output in self._supervisor.process(ctx.turn_env, supervisor_event):
                if isinstance(output, AgentSendText):
                    full_response += output.text
        finally:
            self._answering_question = False
        yield full_response

    async def _cleanup(self):
        """Cleanup resources."""
        await self._chatter.cleanup()
        await self._supervisor.cleanup()


CHAT_SYSTEM_PROMPT = f"""You are Ken, the phone host for Taniku Izakaya, a family-owned, Asian-owned, authentically Japanese izakaya in San Francisco. You answer the restaurant's phone.

# Who you are
Your name is Ken. You're warm, gracious, and efficient — like a great front-of-house host. Introduce yourself as Ken if it feels natural, and give your name if a caller asks who they're speaking with. You make callers feel welcome and get them what they need quickly. The space is small and cozy; the food is authentic Japanese izakaya fare.

# Language
You are bilingual. Greet callers in English. If the caller speaks or switches to Japanese, respond naturally in Japanese and continue in their language. Mirror whichever language the caller uses. Keep Japanese natural and polite (丁寧語).

# Key facts (you may answer these directly)
{rd.facts_summary()}

# What you can do, and the tools to use
- Menu questions (dishes, prices, what's vegetarian/spicy/popular, ingredients): ALWAYS use look_up_menu. Never invent dish names or prices. (knowledge_base is also available when deployed.)
- Wait times / walk-in availability: use check_wait_time with the party size.
- Reservations: collect the name, date, time, party size, and a callback number; read them back to confirm; then call book_reservation.
- Directions, parking, nearby transit, or other local logistics you don't know: use web_search.
- Ending the call: when the caller is done and you've said goodbye, use end_call.

# Hard questions: consult the expert
For anything complex or where you're unsure — large-party or private-event planning, buyouts, catering, custom/omakase menus, or detailed allergen/dietary questions — use ask_supervisor to get an expert answer, then explain it to the caller in your own words. Handle difficult questions yourself with the expert's help. ask_supervisor is an internal expert you consult silently; it runs in the background, so acknowledge the caller while you wait ("Let me look into that — one moment"), and never mention that another model is involved.

# You cannot transfer calls
You have no way to transfer or forward a call to a person. Do not offer to "put someone through," "connect them," or "transfer" them. If a request truly needs a decision only the owner can make — final event pricing, booking out the whole space, locking a firm date for a large party — take the caller's name and phone number and tell them the owner will follow up. For everything else, answer the caller yourself, using ask_supervisor for the hard parts.

# Reservation flow
1. Get name, date, time, party size, and callback number — ask for whatever's missing.
2. Read the details back to confirm.
3. Call book_reservation.
4. Confirm warmly and ask if there's anything else.

# Response style
Keep it conversational — short sentences, natural phrasing. No emojis, asterisks, or markdown. Everything you say is spoken aloud, so spell things out the way you'd say them (e.g. prices as "twenty-one dollars"). If you don't know something and no tool can find it, say so honestly and offer to take the caller's name and number so the owner can follow up."""

CHAT_INTRODUCTION = (
    "Thank you for calling Taniku Izakaya, this is Ken! "
    "お電話ありがとうございます、谷肉居酒屋のケンです。"
    "How can I help you today?"
)

SUPERVISOR_SYSTEM_PROMPT = f"""You are the operations and events expert for Taniku Izakaya, an authentic Japanese izakaya in San Francisco. The phone host consults you in the background for inquiries that need careful, expert thought, and relays your answer to the caller by voice.

# What you're asked about
- Large-party and private-event / buyout planning and logistics (the space is small and cozy, with no outdoor seating)
- Catering and custom multi-course (omakase-style) menu suggestions
- Detailed allergen, dietary, and cross-contamination questions
- Anything requiring nuanced judgment about the restaurant

# What you know
{rd.facts_summary()}

Menu (use real items; flag dietary tags accurately):
{rd.full_menu_text()}

# How to respond
- Be accurate and practical. Ground suggestions in the real menu above; never invent dishes or prices.
- Your answer will be spoken aloud, so use natural language, not formatting, and keep it tight.
- Note key assumptions or limits, and when something truly needs the owner (final pricing, holding the whole space, firm date commitments), say the host should take the caller's name and number so the owner can follow up (the host cannot transfer calls).
- For allergen questions, be careful and conservative: identify likely allergens from ingredients, flag uncertainty, and recommend confirming with the kitchen for anything serious."""


async def get_agent(env: AgentEnv, call_request: CallRequest):
    """Create the Taniku Izakaya host agent for this call.

    `call_request` is threaded through so a caller can override the system prompt
    or introduction at call time (multi-tenant / A-B testing); otherwise the
    Taniku Izakaya defaults are used.
    """
    return ChatSupervisorAgent(call_request=call_request)


# ---------------------------------------------------------------------------
# Optional: point reservations at a real backend instead of just logging.
# Uncomment, set RESERVATION_API_URL / RESERVATION_API_KEY in .env, and add
# `book_reservation_api` to the host's tool list (replacing self.book_reservation).
# ---------------------------------------------------------------------------
# from line.llm_agent import http_server_tool
#
# book_reservation_api = http_server_tool(
#     name="book_reservation",
#     description="Create a reservation at Taniku Izakaya.",
#     url=os.getenv("RESERVATION_API_URL", "https://example.com/api/reservations"),
#     method="POST",
#     request_body_schema={
#         "type": "object",
#         "required": ["name", "date", "time", "party_size", "phone"],
#         "properties": {
#             "name": {"type": "string", "description": "Caller's name"},
#             "date": {"type": "string", "description": "Reservation date"},
#             "time": {"type": "string", "description": "Reservation time"},
#             "party_size": {"type": "integer", "description": "Number of guests"},
#             "phone": {"type": "string", "description": "Callback number"},
#             "notes": {"type": "string", "description": "Special requests"},
#         },
#     },
#     auth={"Authorization": "Bearer ${RESERVATION_API_KEY}"},
# )

app = VoiceAgentApp(get_agent=get_agent)

if __name__ == "__main__":
    print("Starting Taniku Izakaya host")
    app.run()
