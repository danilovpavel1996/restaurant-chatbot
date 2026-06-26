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
