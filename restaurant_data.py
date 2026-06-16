"""Knowledge base for Taniku Izakaya (local source of truth).

This module holds the restaurant's menu and facts as plain Python data, plus a
couple of small formatting helpers. It is the local "knowledge base" that the
``look_up_menu`` tool in ``main.py`` queries, and it is also used to generate the
markdown docs in ``knowledge/`` that can be uploaded to Cartesia's native
knowledge base for production deployments.

Design note: large / frequently-changing / long-tail content (the full menu)
lives here and is fetched on demand, rather than being baked into the system
prompt. Small, stable, every-call facts (happy hour, popular items, policies)
are summarized in the system prompt. ``FACTS`` below is the bridge between the
two — the host prompt cites it, and it is also surfaced via the menu tool.
"""

from typing import Dict, List, TypedDict

# Placeholders the owner should fill in (kept here so they are easy to find).
TODO = "TODO"


class MenuItem(TypedDict, total=False):
    name: str
    name_ja: str
    price: int  # USD
    desc: str
    tags: List[str]


# ---------------------------------------------------------------------------
# Menu (transcribed from the restaurant's printed menu).
# tags vocabulary:
#   vegetarian, raw, spicy, contains_nuts, gluten_free_option, new, popular
# ---------------------------------------------------------------------------
MENU: Dict[str, List[MenuItem]] = {
    # Zensai = appetizers
    "zensai": [
        {"name": "Okonomiyaki Potato Tots", "price": 11,
         "desc": "Potato, bonito, with okonomiyaki sauce."},
        {"name": "Mekyabetsu", "price": 9,
         "desc": "Brussels sprouts with karashi mustard.", "tags": ["vegetarian"]},
        {"name": "Gyoza", "price": 9,
         "desc": "Chicken & pork gyoza with house honey mustard."},
        {"name": "Karaage", "price": 12,
         "desc": "Fried house-marinated chicken bites with curry aioli."},
        {"name": "Hotate Carpaccio", "price": 16,
         "desc": "Hokkaido scallops, greens, yuzu ponzu, onion, creamy sauce.",
         "tags": ["raw"]},
        {"name": "Kabocha Koro", "price": 11,
         "desc": "Pumpkin potato croquette with house sauce and greens.",
         "tags": ["vegetarian"]},
        {"name": "Takoyaki", "price": 11,
         "desc": "Octopus balls, avocado, bonito flakes, house sauce."},
        {"name": "Agedashi Tofu", "name_ja": "揚げ出し豆腐", "price": 10,
         "desc": "Egg tofu, bonito flakes, onion, yuzu sauce.", "tags": ["vegetarian"]},
        {"name": "Miso Cauliflower", "price": 10,
         "desc": "Cauliflower, miso, butter, garlic, kimchi.", "tags": ["vegetarian"]},
        {"name": "Black Pepper Chicken", "price": 13,
         "desc": "Fried chicken, onion, butter, black pepper."},
        {"name": "Geso Karaage", "price": 13,
         "desc": "Fried squid, Japanese tartar mayo sauce, and lemon."},
        {"name": "Hamachi Carpaccio", "price": 16,
         "desc": "Hamachi, avocado, greens, with truffle sauce.", "tags": ["raw"]},
        {"name": "Mochi Maki", "price": 9,
         "desc": "Seaweed, mochi, cheese.", "tags": ["vegetarian"]},
        {"name": "Kinoko Nimono", "price": 11,
         "desc": "Mushrooms, cream sauce, with truffle oil.", "tags": ["vegetarian"]},
        {"name": "Kimuchi Potato Salad", "price": 10,
         "desc": "Mama's kimchi, potato, with melted cheese.",
         "tags": ["vegetarian", "new"]},
    ],
    # Kushiyaki = charcoal-grilled skewers, two per order
    "kushiyaki": [
        {"name": "Tori Mo-Mo", "price": 10, "desc": "Chicken leg with teriyaki."},
        {"name": "Yuzu Tori", "price": 10, "desc": "Chicken leg, yuzu sauce."},
        {"name": "Tori Tsukune", "price": 13,
         "desc": "Soy minced chicken, yuzu, and egg yolk."},
        {"name": "Hotate", "price": 13, "desc": "Scallops with aka miso sauce."},
        {"name": "Ba-Ra", "price": 11, "desc": "Tender pork belly."},
        {"name": "Kobe", "price": 11, "desc": "Ribeye teriyaki."},
        {"name": "Imo", "price": 9, "desc": "Japanese yam with butter.",
         "tags": ["vegetarian"]},
    ],
    "ramen": [
        {"name": "Hokkaido Miso", "price": 21,
         "desc": "Japanese miso made extraordinary: garlic, chili, corn, roasted pork "
                 "chashu, cabbage, cauliflower, butter, soft egg.", "tags": ["spicy"]},
        {"name": "Saishoku", "price": 19,
         "desc": "Coconut sauce, curry, corn, bamboo shoot, baby bok choy, and greens.",
         "tags": ["vegetarian", "spicy"]},
        {"name": "Spicy Miso Crab", "price": 22,
         "desc": "Soft shell crab, roasted pork chashu, greens, and soft egg.",
         "tags": ["spicy"]},
        {"name": "Niku", "price": 21,
         "desc": "House favorite spicy sauce, sauteed tender beef, sweet onion, "
                 "spicy soy broth, and soft egg.", "tags": ["spicy", "popular"]},
        {"name": "Garlic Pork", "price": 20,
         "desc": "Roasted pork chashu, fried garlic, corn, baby bok choy, "
                 "black garlic oil, and soft egg."},
        {"name": "Midori Udon", "price": 22,
         "desc": "Aomori scallops, basil pesto, butter, corn, greens, bonito. "
                 "Soupless.", "tags": ["contains_nuts"]},
        {"name": "Tsukemen", "name_ja": "つけ麺", "price": 20,
         "desc": "Cold noodles, pork broth, roasted pork chashu, bamboo shoot, "
                 "green onion, soft egg, yuzu, and nori seaweed."},
        {"name": "Yuzu Shiitake", "name_ja": "柚子香る椎茸ラーメン", "price": 19,
         "desc": "Mushroom, chicken yuzu broth, bamboo shoot, greens, and soft egg.",
         "tags": ["new"]},
    ],
    # Ramen add-ons (and noodle substitutions)
    "toppings": [
        {"name": "Soft egg", "price": 2},
        {"name": "Kimchi", "price": 3},
        {"name": "Pork chashu", "price": 6},
        {"name": "Extra noodles", "price": 4},
        {"name": "Soft shell crab", "price": 5},
        {"name": "Bamboo shoot", "price": 3},
        {"name": "SUB yam noodle", "price": 2, "desc": "Gluten free.",
         "tags": ["gluten_free_option"]},
        {"name": "SUB udon", "price": 2},
    ],
    # Donburi = rice bowls
    "donburi": [
        {"name": "Karaage Curry Don", "price": 19,
         "desc": "Fried tender juicy marinated chicken bites, curry, potato, and carrot."},
        {"name": "Katsu Curry Don", "price": 19,
         "desc": "Fried pork, curry, potato, and carrot."},
        {"name": "Kabocha Curry Don", "price": 18,
         "desc": "Pumpkin potato croquette, curry, potato, and carrot.",
         "tags": ["vegetarian"]},
        {"name": "Unagi Don", "price": 20, "desc": "Eel, tofu, bonito, ginger."},
        {"name": "Chazuke", "price": 20,
         "desc": "Salmon, Shizuoka matcha, chicken broth, seaweed, and yuzu."},
    ],
    # Dessert menu was not provided; only the popular item is known so far.
    "desserts": [
        {"name": "Hojicha Panna Cotta", "price": 0,
         "desc": "Roasted-green-tea panna cotta — a guest favorite. "
                 "(Price TODO; full dessert menu TODO.)", "tags": ["popular"]},
    ],
}

# Human-readable section titles (for voice + docs).
SECTION_TITLES: Dict[str, str] = {
    "zensai": "Zensai (Appetizers)",
    "kushiyaki": "Kushiyaki (Charcoal-Grilled Skewers, two per order)",
    "ramen": "Ramen",
    "toppings": "Ramen Toppings & Noodle Subs",
    "donburi": "Donburi (Rice Bowls)",
    "desserts": "Desserts",
}

# Footnotes printed on the menu.
MENU_NOTES: List[str] = [
    "No topping substitutions accepted.",
    "Consuming raw or undercooked meats or eggs may increase your risk of "
    "food-borne illness.",
]

# ---------------------------------------------------------------------------
# Facts: small, stable, every-call info. Summarized into the system prompt and
# also returned by the menu tool for "hours / policy" style questions.
# ---------------------------------------------------------------------------
FACTS: Dict[str, str] = {
    "name": "Taniku Izakaya",
    "cuisine": "Authentic Japanese izakaya",
    "location": "1035 Geary St, San Francisco, CA 94109",
    "hours": "TODO (operating hours not yet provided)",
    "happy_hour": "Happy hour starts daily at 4:30 PM. (End time/days: TODO.)",
    "ownership": "Family-owned and Asian-owned.",
    "atmosphere": "Small, cozy, intimate space.",
    "seating": "No outdoor seating. The space is tiny, so smaller groups "
               "generally have shorter waits.",
    "pets": "No dogs allowed.",
    "popular": "Most popular: the Niku ramen (sweet and spicy house favorite) "
               "and the Hojicha Panna Cotta.",
    "reservations": "Reservations are taken by phone. For large parties or "
                    "private events, callers may be connected to the owner.",
}


# ---------------------------------------------------------------------------
# Helpers (reused by the look_up_menu tool and the knowledge-doc generator).
# ---------------------------------------------------------------------------
def _format_item(item: MenuItem) -> str:
    name = item.get("name", "")
    name_ja = item.get("name_ja")
    if name_ja:
        name = f"{name} ({name_ja})"
    price = item.get("price")
    price_str = f" — ${price}" if price else ""
    line = f"{name}{price_str}"
    desc = item.get("desc")
    if desc:
        line += f": {desc}"
    tags = item.get("tags") or []
    flags = [t.replace("_", " ") for t in tags if t not in ("popular", "new")]
    badges = []
    if "popular" in tags:
        badges.append("popular")
    if "new" in tags:
        badges.append("new")
    badges += flags
    if badges:
        line += f" [{', '.join(badges)}]"
    return line


def format_menu_section(section: str) -> str:
    """Return a voice-friendly listing of one menu section."""
    section = section.lower().strip()
    if section not in MENU:
        return (f"Sorry, I don't have a '{section}' section. Sections are: "
                f"{', '.join(SECTION_TITLES.values())}.")
    title = SECTION_TITLES.get(section, section.title())
    lines = [f"{title}:"] + [f"- {_format_item(i)}" for i in MENU[section]]
    return "\n".join(lines)


def search_menu(query: str) -> str:
    """Search every section by name/description/tag; return matching items."""
    q = query.lower().strip()
    matches: List[str] = []
    for section, items in MENU.items():
        for item in items:
            haystack = " ".join([
                item.get("name", ""),
                item.get("name_ja", ""),
                item.get("desc", ""),
                " ".join(item.get("tags") or []),
            ]).lower()
            if q in haystack:
                matches.append(f"- {_format_item(item)} ({SECTION_TITLES[section]})")
    if not matches:
        return (f"I couldn't find anything matching '{query}'. "
                "Want me to read a section, like ramen or appetizers?")
    return "\n".join(matches)


def items_by_tag(tag: str) -> str:
    """Return items carrying a given tag (e.g. 'vegetarian', 'spicy')."""
    return search_menu(tag)


def popular_items() -> str:
    """Return the popular/house-favorite items."""
    return FACTS["popular"] + "\n" + search_menu("popular")


def facts_summary() -> str:
    """A compact facts block for prompts/docs."""
    return "\n".join(f"- {k}: {v}" for k, v in FACTS.items())


def full_menu_text() -> str:
    """The whole menu, section by section (used for the markdown doc)."""
    parts = [format_menu_section(s) for s in MENU]
    parts.append("Notes:\n" + "\n".join(f"- {n}" for n in MENU_NOTES))
    return "\n\n".join(parts)
