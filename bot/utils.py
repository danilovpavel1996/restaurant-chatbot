"""Utility helpers: config loading, language detection, message formatting."""

import json
import os
import re

_config_cache = None

def load_config() -> dict:
    """Load restaurant_config.json once and cache it."""
    global _config_cache
    if _config_cache is None:
        config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "restaurant_config.json")
        with open(config_path, "r", encoding="utf-8") as f:
            _config_cache = json.load(f)
    return _config_cache


def detect_language(text: str) -> str:
    """Detect user language from text. Returns 'ro', 'en', or 'ru'. Defaults to 'ro'."""
    # Cyrillic → Russian
    cyrillic = len(re.findall(r"[Ѐ-ӿ]", text))
    if cyrillic > max(2, len(text) * 0.25):
        return "ru"

    # Romanian diacritics
    if any(c in "ăâîșțĂÂÎȘȚ" for c in text):
        return "ro"

    text_lower = text.lower()

    # Romanian keyword check
    ro_words = ["salut", "buna", "bună", "vreau", "masa", "masă", "rezervare", "meniu",
                "multumesc", "mulțumesc", "da", "pentru", "doresc"]
    if any(w in text_lower for w in ro_words):
        return "ro"

    # English keyword check
    en_words = ["hello", "hi", "want", "table", "reservation", "book", "menu",
                "please", "thank", "what", "how", "can", "help"]
    if any(w in text_lower for w in en_words):
        return "en"

    return "ro"


def get_hookah_options(lang: str, config: dict) -> list[dict]:
    """Return hookah options with name and description in the given language."""
    result = []
    for opt in config["hookah"]["options"]:
        if lang == "en":
            name = opt.get("name_en", opt["name"])
            desc = opt.get("description_en", opt["description"])
        elif lang == "ru":
            name = opt.get("name_ru", opt["name"])
            desc = opt.get("description_ru", opt["description"])
        else:
            name = opt["name"]
            desc = opt["description"]
        result.append({
            "id": opt["id"],
            "name": name,
            "desc": desc,
            "price": opt["price_mdl"],
        })
    return result


def config_to_text_summary(config: dict) -> str:
    """Produce a concise, readable summary of the restaurant config for the AI system prompt."""
    c = config["contact"]
    return f"""
RESTAURANT: {config['restaurant']['name']}
{config['restaurant']['description']}

CONTACT & LOCATION:
- Address: {c['address']}
- Phone: {c['phone']}
- Website: {c['website']}

HOURS:
- Lounge: Daily 10:00–02:00
- Kitchen: Daily 12:00–23:00 (food orders only until 23:00)
- Breakfast: 10:00–14:00 daily
- Sushi: 12:00–22:30 daily (IMPORTANT: sushi orders must be placed before 22:30)
- Happy Hour: Mon–Fri 12:00–18:00 — second hookah 50% off (293 MDL)

POLICIES:
- Payment: cash, Visa, Mastercard
- Walk-ins welcome; reservations recommended for groups and weekend evenings
- Dress code: smart casual
- Hookah (narghilea): 18+ only

SEATING:
- Indoor: elegant lounge dining
- Terrace: outdoor, hookah available
- Hookah can be ordered at any table (indoors or outdoors)

HOOKAH / NARGHILEA (all 18+ only):
- Clasică / Classic: 585 MDL — consult Shisha Master for mixes
- Cocktail Vase: 975 MDL — hookah bowl filled with non-alcoholic cocktail mix
- Premium (fruit bowl): 1365 MDL — fresh fruit aromas with selected mixes
- Happy Hour Mon–Fri 12:00–18:00: second hookah 50% off = 293 MDL

MENU HIGHLIGHTS (all prices in MDL):
Breakfast (10:00–14:00): Greek Salad with Feta 215, Fried Eggs & Bacon 215, Bacon Omelette 215, Piperchi 195, Smoked Salmon Toast 332

New Summer Menu (12:00–23:00): Mussels in Wine Sauce 293, Grilled Sardines 273, Saganaki Shrimp 351, Komodo Chicken 351, Asian Duck Breast 624, Wagyu Burger 371, Red Sea Bream with Mediterranean Vegetables 429

Salads: Summer Salad 195, Ponzu Salad 156, Wakame 117, Green Salad with Wasabi 156
Soups: Miso 129, Tom Yum 304

Premium Starters: Oyster (per piece) 98, Tuna Tataki 371, Pork Bao-Bun 254, Salmon Tartare 312, Tuna Tartare 351

Premium Mains: Sirloin Steak 800, Rib-Eye 839, Butterfly Sea Bass 371, Salmon Steak 410, Shrimp in Butter Lime 371, Octopus with Olives 429, Chicken Satay with Nasi Goreng 293

Mains (until 02:00): Chicken Teriyaki 332, Salmon Teriyaki 371, Noodles from 254, Beef Burger 293, Karaage Chicken Burger 273, Octopus a la Gallega 468

Sides: Kimchi Rice 176, French Fries 94, Asparagus 183, Steamed Rice 90, Broccoli 152

Desserts: Tiramisu 215, Mango Sticky Rice 246, Seasonal Fruit Platter 468, Matcha Cheesecake 176, Komodo Garden 195

SUSHI (12:00–22:30 ONLY):
Rolls: Mango Shrimp 312, Trio Yuzu 371, Bell Pepper 312, Octopus 429, Soft Shell Crab 312
Special Rolls: Salmon Fried 293, Dragon 332, Philly Salmon Flambat 351, Komodo Roll 371, Spicy Tuna 371
Hoso Maki: from 109 MDL (6 pcs)
Nigiri: from 105 MDL (2 pcs)
Sashimi: from 156 MDL (4 pcs)
Sushi Sets: Salmon Set (2p) 819, Mixed Set (2p) 878

DRINKS:
Classic Cocktails: from 172 MDL | Signature Cocktails: from 168 MDL | Non-alcoholic: from 148 MDL
Beers: Carlsberg 98, Guinness Draught 156, Weihenstephaner 137
Lemonades (430ml): from 125 MDL
Coffee: Espresso 66, Cappuccino 101, Americano 70, Espresso Tonic 109
Wines by glass: Red/White 137 MDL, Rosé 117 MDL
Champagne: Moët & Chandon Brut 1989, Dom Pérignon 7410
Whisky: Glenfiddich 12 (207), Hibiki Harmony (491), Royal Salute 21 (585)
Cognac: Hennessy VSOP (254), Hennessy XO (605)
Tequila: Don Julio 1942 (351), Clase Azul (975)

KEY RULES (ALWAYS FOLLOW):
1. Sushi available ONLY until 22:30 — inform guests if asking about late-night sushi
2. Breakfast only 10:00–14:00
3. Kitchen closes at 23:00 — lounge stays open until 02:00 (drinks only after 23:00)
4. Hookah for 18+ ONLY — always mention this when hookah is discussed
5. Max reservation party size: 20 people
""".strip()


# ── Menu category definitions ──────────────────────────────────────────────────

MENU_CATEGORIES: list[tuple[str, str, dict]] = [
    ("breakfast",        "🌅", {"en": "Breakfast",        "ro": "Mic dejun",        "ru": "Завтрак"}),
    ("summer_menu",      "☀️", {"en": "Summer Menu",       "ro": "Meniu Vară",       "ru": "Летнее меню"}),
    ("salads",           "🥗", {"en": "Salads",            "ro": "Salate",           "ru": "Салаты"}),
    ("soups",            "🍵", {"en": "Soups",             "ro": "Supe",             "ru": "Супы"}),
    ("premium_starters", "⭐", {"en": "Premium Starters",  "ro": "Startere Premium", "ru": "Премиум закуски"}),
    ("premium_mains",    "🥩", {"en": "Premium Mains",     "ro": "Feluri Premium",   "ru": "Премиум блюда"}),
    ("mains",            "🍜", {"en": "Main Dishes",       "ro": "Feluri Principale","ru": "Основные блюда"}),
    ("sides",            "🫘", {"en": "Sides",             "ro": "Garnituri",        "ru": "Гарниры"}),
    ("desserts",         "🍰", {"en": "Desserts",          "ro": "Deserturi",        "ru": "Десерты"}),
    ("sushi",            "🍣", {"en": "Sushi",             "ro": "Sushi",            "ru": "Суши"}),
    ("cocktails",        "🍹", {"en": "Cocktails",         "ro": "Cocktailuri",      "ru": "Коктейли"}),
    ("drinks",           "🥤", {"en": "Other Drinks",      "ro": "Alte Băuturi",     "ru": "Напитки"}),
    ("wines",            "🍷", {"en": "Wines",             "ro": "Vinuri",           "ru": "Вина"}),
    ("spirits",          "🥃", {"en": "Spirits",           "ro": "Spirtoase",        "ru": "Крепкие напитки"}),
    ("hookah",           "🔥", {"en": "Hookah",            "ro": "Narghilea",        "ru": "Кальян"}),
]

_SIMPLE_CAT_MAP = {
    "breakfast":        "breakfast",
    "summer_menu":      "new_summer_menu",
    "salads":           "salads",
    "soups":            "soups",
    "premium_starters": "premium_starters",
    "premium_mains":    "premium_mains",
    "mains":            "mains",
    "sides":            "sides",
    "desserts":         "desserts",
}


def _cat_label_emoji(category_key: str, lang: str) -> tuple[str, str]:
    for key, emoji, labels in MENU_CATEGORIES:
        if key == category_key:
            return emoji, labels.get(lang, labels["en"])
    return "🍽", category_key


def _item_name(item: dict, lang: str) -> str:
    if lang == "en":
        return item.get("name_en") or item.get("name", "")
    if lang == "ru":
        return item.get("name_ru") or item.get("name", "")
    return item.get("name", "")


def _fmt_items(items: list[dict], lang: str) -> str:
    lines = []
    for item in items:
        name = _item_name(item, lang)
        price = item.get("price_mdl", "")
        vol = item.get("volume_ml") or item.get("volume", "")
        vol_str = (f" ({vol}ml)" if isinstance(vol, int) and vol
                   else f" ({vol})" if isinstance(vol, str) and vol else "")
        note_str = f"  ({item['note']})" if item.get("note") else ""
        line = f"• {name}{vol_str} — {price} MDL{note_str}"
        ingr = item.get("ingredients", "")
        if ingr:
            line += f"\n  {ingr}"
        lines.append(line)
    return "\n".join(lines)


def _fmt_simple_items(items: list[dict]) -> str:
    """For drinks/spirits that only have name + price (no lang variants)."""
    return "\n".join(f"• {item.get('name', '')} — {item.get('price_mdl', '')} MDL" for item in items)


def _pack_pages(blocks: list[str], max_len: int = 3800) -> list[str]:
    """Group text blocks into pages, never exceeding max_len per page."""
    pages: list[str] = []
    current = ""
    for block in blocks:
        segment = ("\n\n" + block) if current else block
        if current and len(current) + len(segment) > max_len:
            pages.append(current.strip())
            current = block
        else:
            current += segment
    if current.strip():
        pages.append(current.strip())
    return pages or [""]


def _fmt_hookah(lang: str, config: dict) -> str:
    h = config["hookah"]
    hh = h["happy_hour"]
    lines = []
    for opt in h["options"]:
        if lang == "en":
            name = opt.get("name_en", opt["name"])
            desc = opt.get("description_en", opt.get("description", ""))
        elif lang == "ru":
            name = opt.get("name_ru", opt["name"])
            desc = opt.get("description_ru", opt.get("description", ""))
        else:
            name = opt["name"]
            desc = opt.get("description", "")
        lines.append(f"• {name} — {opt['price_mdl']:,} MDL\n  {desc}")

    if lang == "ro":
        hh_line = f"🕐 Happy Hour {hh['days']} {hh['time']}\n  Al doilea narghilă 50% reducere — doar {hh['price_second_hookah_mdl']} MDL"
        age_line = "⚠️ Doar pentru persoane cu vârsta de 18+ ani"
        title = "🔥 Narghilea"
    elif lang == "ru":
        hh_line = f"🕐 Happy Hour {hh['days']} {hh['time']}\n  Второй кальян 50% скидка — всего {hh['price_second_hookah_mdl']} MDL"
        age_line = "⚠️ Только для гостей 18+"
        title = "🔥 Кальян"
    else:
        hh_line = f"🕐 Happy Hour {hh['days']} {hh['time']}\n  Second hookah 50% off — only {hh['price_second_hookah_mdl']} MDL"
        age_line = "⚠️ Age 18+ only"
        title = "🔥 Hookah (Narghilea)"

    body = "\n\n".join(lines)
    return f"{title}\n\n{body}\n\n{hh_line}\n\n{age_line}"


def _fmt_sushi_pages(sushi: dict, lang: str, header: str) -> list[str]:
    _sub = {
        "en": {"rolls": "Rolls", "special_rolls": "Special Rolls", "hoso_maki": "Hoso Maki",
               "nigiri": "Nigiri", "sashimi": "Sashimi", "sushi_sets": "Sets (for 2)"},
        "ro": {"rolls": "Rulouri", "special_rolls": "Rulouri Speciale", "hoso_maki": "Hoso Maki",
               "nigiri": "Nigiri", "sashimi": "Sashimi", "sushi_sets": "Seturi (pentru 2)"},
        "ru": {"rolls": "Роллы", "special_rolls": "Специальные роллы", "hoso_maki": "Хосо Маки",
               "nigiri": "Нигири", "sashimi": "Сашими", "sushi_sets": "Сеты (на 2)"},
    }.get(lang, {})

    note = {"en": "⏰ Sushi available 12:00–22:30 only",
            "ro": "⏰ Sushi disponibil 12:00–22:30",
            "ru": "⏰ Суши доступны 12:00–22:30"}.get(lang, "")

    blocks = [header, note]
    order = ["rolls", "special_rolls", "hoso_maki", "nigiri", "sashimi", "sushi_sets"]
    for sub_key in order:
        items = sushi.get(sub_key, [])
        if not items:
            continue
        sub_label = _sub.get(sub_key, sub_key)
        if sub_key == "sushi_sets":
            body = "\n".join(
                f"• {_item_name(s, lang)} — {s.get('price_mdl', '')} MDL\n  {s.get('contents', '')}"
                for s in items
            )
        else:
            body = _fmt_items(items, lang)
        blocks.append(f"{sub_label}:\n{body}")

    return _pack_pages(blocks)


def _fmt_cocktails_pages(drinks: dict, lang: str, header: str) -> list[str]:
    _sub = {
        "en": {"cocktails_classic": "Classic Cocktails",
               "cocktails_signature": "Signature Cocktails",
               "cocktails_non_alcoholic": "Non-Alcoholic"},
        "ro": {"cocktails_classic": "Cocktailuri Clasice",
               "cocktails_signature": "Cocktailuri Signature",
               "cocktails_non_alcoholic": "Fără Alcool"},
        "ru": {"cocktails_classic": "Классические коктейли",
               "cocktails_signature": "Авторские коктейли",
               "cocktails_non_alcoholic": "Безалкогольные"},
    }.get(lang, {})

    blocks = [header]
    for sub_key in ("cocktails_classic", "cocktails_signature", "cocktails_non_alcoholic"):
        section = drinks.get(sub_key, {})
        items = section.get("items", [])
        if not items:
            continue
        label = _sub.get(sub_key, sub_key)
        blocks.append(f"{label}:\n{_fmt_items(items, lang)}")
    return _pack_pages(blocks)


def _fmt_drinks_pages(drinks: dict, lang: str, header: str) -> list[str]:
    _sub = {
        "en": {"beer_cider": "Beer & Cider", "lemonades": "Lemonades", "fresh_juices": "Fresh Juices",
               "tea": "Teas", "ice_tea": "Iced Tea", "coffee": "Coffee",
               "hot_drinks": "Hot Drinks", "soft_drinks": "Soft Drinks",
               "water": "Water", "energy_drinks": "Energy Drinks"},
        "ro": {"beer_cider": "Bere & Cidru", "lemonades": "Limonade", "fresh_juices": "Sucuri Proaspete",
               "tea": "Ceaiuri", "ice_tea": "Ice Tea", "coffee": "Cafea",
               "hot_drinks": "Băuturi Calde", "soft_drinks": "Soft Drinks",
               "water": "Apă", "energy_drinks": "Energizante"},
        "ru": {"beer_cider": "Пиво и сидр", "lemonades": "Лимонады", "fresh_juices": "Свежие соки",
               "tea": "Чаи", "ice_tea": "Холодный чай", "coffee": "Кофе",
               "hot_drinks": "Горячие напитки", "soft_drinks": "Безалкогольные",
               "water": "Вода", "energy_drinks": "Энергетики"},
    }.get(lang, {})

    blocks = [header]
    for sub_key, label in _sub.items():
        section = drinks.get(sub_key)
        if not section:
            continue
        items = section.get("items", [])
        note_str = section.get("note", "")

        if sub_key == "tea":
            # items is a list of strings
            tea_names = ", ".join(items) if isinstance(items, list) else ""
            price = section.get("price_mdl", "")
            body = f"{tea_names}\n  {price} MDL each"
        elif sub_key == "ice_tea":
            tea_names = ", ".join(items) if isinstance(items, list) else ""
            price = section.get("price_mdl", "")
            body = f"{tea_names}\n  {price} MDL each"
        elif sub_key == "soft_drinks":
            body = f"{note_str or ''} — {section.get('price_mdl', '')} MDL"
        elif items:
            body = _fmt_items(items, lang)
        else:
            continue

        header_line = f"{label}:" + (f"  ({note_str})" if note_str and sub_key not in ("tea", "ice_tea", "soft_drinks") else "")
        blocks.append(f"{header_line}\n{body}")

    return _pack_pages(blocks)


def _fmt_wines_pages(wines: dict, lang: str, header: str) -> list[str]:
    _sub = {
        "en": {"by_glass": "By the Glass", "champagne_prosecco": "Champagne & Prosecco",
               "white": "White Wine", "rose": "Rosé", "red": "Red Wine"},
        "ro": {"by_glass": "La Pahar", "champagne_prosecco": "Șampanie & Prosecco",
               "white": "Vin Alb", "rose": "Rosé", "red": "Vin Roșu"},
        "ru": {"by_glass": "По бокалу", "champagne_prosecco": "Шампанское и Просекко",
               "white": "Белое вино", "rose": "Розовое", "red": "Красное вино"},
    }.get(lang, {})

    blocks = [header]
    for sub_key, label in _sub.items():
        items = wines.get(sub_key, [])
        if not items:
            continue
        blocks.append(f"{label}:\n{_fmt_simple_items(items)}")
    return _pack_pages(blocks)


def _fmt_spirits_pages(spirits: dict, lang: str, header: str) -> list[str]:
    _sub = {
        "en": {"aperitifs": "Aperitifs", "whisky": "Whisky", "cognac": "Cognac & Brandy",
               "liqueurs": "Liqueurs", "gin": "Gin", "rum": "Rum",
               "sake": "Sake", "tequila": "Tequila", "vodka": "Vodka"},
        "ro": {"aperitifs": "Aperitive", "whisky": "Whisky", "cognac": "Coniac & Brandy",
               "liqueurs": "Lichioruri", "gin": "Gin", "rum": "Rom",
               "sake": "Sake", "tequila": "Tequila", "vodka": "Vodcă"},
        "ru": {"aperitifs": "Аперитивы", "whisky": "Виски", "cognac": "Коньяк и бренди",
               "liqueurs": "Ликёры", "gin": "Джин", "rum": "Ром",
               "sake": "Саке", "tequila": "Текила", "vodka": "Водка"},
    }.get(lang, {})

    blocks = [header]
    for sub_key, label in _sub.items():
        items = spirits.get(sub_key, [])
        if not items:
            continue
        blocks.append(f"{label}:\n{_fmt_simple_items(items)}")
    return _pack_pages(blocks)


def format_menu_category(category_key: str, lang: str, config: dict) -> list[str]:
    """Return 1+ message strings (each ≤ 3800 chars) for the given category."""
    emoji, cat_label = _cat_label_emoji(category_key, lang)
    header = f"{emoji} {cat_label}"
    menu = config["menu"]

    if category_key == "hookah":
        return [_fmt_hookah(lang, config)]

    if category_key in _SIMPLE_CAT_MAP:
        items = menu[_SIMPLE_CAT_MAP[category_key]]["items"]
        return [f"{header}\n\n{_fmt_items(items, lang)}"]

    if category_key == "sushi":
        return _fmt_sushi_pages(menu["sushi"], lang, header)

    if category_key == "cocktails":
        return _fmt_cocktails_pages(menu["drinks"], lang, header)

    if category_key == "drinks":
        return _fmt_drinks_pages(menu["drinks"], lang, header)

    if category_key == "wines":
        return _fmt_wines_pages(menu["drinks"]["wines"], lang, header)

    if category_key == "spirits":
        return _fmt_spirits_pages(menu["drinks"]["spirits"], lang, header)

    return [f"{header}\n\n(No data available)"]


# ── Reservation formatting ──────────────────────────────────────────────────────

def format_single_reservation(res: dict, lang: str) -> str:
    """Format a single reservation record for display."""
    status = res.get("status", "confirmed")
    status_emoji = "✅" if status == "confirmed" else "❌"
    hookah_line = f"\n• {'Narghilea' if lang == 'ro' else 'Hookah' if lang == 'en' else 'Кальян'}: {res.get('hookah')}" if res.get("hookah") else ""

    seating = res.get("seating_preference", "")
    seating_labels = {
        "indoor":  {"ro": "Interior", "en": "Indoor",  "ru": "Внутри"},
        "terrace": {"ro": "Terasă",   "en": "Terrace", "ru": "Терраса"},
    }
    seating_text = seating_labels.get(seating, {}).get(lang, seating)

    special = res.get("special_requests") or {"ro": "Fără", "en": "None", "ru": "Нет"}[lang]

    if lang == "en":
        return (
            f"{status_emoji} *{res['id']}* (Status: {status})\n"
            f"• Name: {res.get('name', '')}\n"
            f"• Date: {res.get('date', '')}\n"
            f"• Time: {res.get('time', '')}\n"
            f"• Guests: {res.get('party_size', '')}\n"
            f"• Phone: {res.get('phone', '')}\n"
            f"• Seating: {seating_text}{hookah_line}\n"
            f"• Special requests: {special}"
        )
    elif lang == "ru":
        return (
            f"{status_emoji} *{res['id']}* (Статус: {status})\n"
            f"• Имя: {res.get('name', '')}\n"
            f"• Дата: {res.get('date', '')}\n"
            f"• Время: {res.get('time', '')}\n"
            f"• Гостей: {res.get('party_size', '')}\n"
            f"• Телефон: {res.get('phone', '')}\n"
            f"• Место: {seating_text}{hookah_line}\n"
            f"• Особые пожелания: {special}"
        )
    else:  # ro
        return (
            f"{status_emoji} *{res['id']}* (Status: {status})\n"
            f"• Nume: {res.get('name', '')}\n"
            f"• Data: {res.get('date', '')}\n"
            f"• Ora: {res.get('time', '')}\n"
            f"• Persoane: {res.get('party_size', '')}\n"
            f"• Telefon: {res.get('phone', '')}\n"
            f"• Loc: {seating_text}{hookah_line}\n"
            f"• Cereri speciale: {special}"
        )
