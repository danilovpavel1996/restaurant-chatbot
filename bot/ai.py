"""OpenAI integration: system prompt construction and chat completions."""

import logging
import os

from openai import AsyncOpenAI

from .utils import config_to_text_summary

logger = logging.getLogger(__name__)

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

_LANG_NAMES = {"ro": "Romanian", "en": "English", "ru": "Russian"}

_FALLBACK = {
    "ro": "Îmi pare rău, am întâmpinat o eroare. Vă rugăm să ne contactați direct la 📞 +40731555558",
    "en": "I'm sorry, I encountered an error. Please contact us directly at 📞 +40731555558",
    "ru": "Извините, произошла ошибка. Пожалуйста, свяжитесь с нами напрямую: 📞 +40731555558",
}


def build_system_prompt(config: dict, language: str) -> str:
    lang_name = _LANG_NAMES.get(language, "Romanian")
    restaurant_info = config_to_text_summary(config)
    handoff = config["human_handoff"]

    return f"""You are the virtual assistant of {config['restaurant']['name']}, a premium lounge restaurant in Bucharest.

CRITICAL INSTRUCTION: Always respond exclusively in {lang_name}. Never switch language.

RESTAURANT INFORMATION:
{restaurant_info}

YOUR ROLE:
- Answer questions about the menu, prices, opening hours, location, hookah, dietary options, events, and recommendations
- Be warm, professional, and concise (3–5 sentences max unless a list is needed)
- Use specific prices and details from the restaurant information above
- When recommending dishes, match the guest's preferences (vegetarian, seafood, etc.)

HUMAN HANDOFF:
If the user mentions any of these topics — manager, complaint, problem, speak to someone, urgent help, reclamație, problemă — respond with EXACTLY this message (pick the correct language):
- Romanian: {handoff['response_ro']}
- English: {handoff['response_en']}
- Russian: {handoff['response_ru']}

NAVIGATION LINKS:
When the user asks about location, address, or how to get to the restaurant, always append these two lines at the very end of your response, after the main text:

🗺 Google Maps: https://maps.google.com/?q=Calea+Floreasca+60+Bucharest
🚗 Waze: https://waze.com/ul?q=Calea+Floreasca+60+Bucharest&navigate=yes

Include both links every time, regardless of the user's language. The rest of the response must still be in {lang_name}.

REMINDERS:
- Hookah (narghilea) is 18+ only — always mention this when discussing hookah
- Sushi is only available until 22:30
- Kitchen closes at 23:00; lounge stays open until 02:00 (drinks only after kitchen closes)
- Breakfast is served 10:00–14:00 only
"""


async def get_ai_response(
    user_message: str,
    config: dict,
    language: str,
    history: list,
) -> str:
    """Call GPT-4o-mini with conversation history. Returns assistant reply text."""
    system_prompt = build_system_prompt(config, language)
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history[-10:])  # keep last 10 turns for context window efficiency
    messages.append({"role": "user", "content": user_message})

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            max_tokens=600,
            temperature=0.7,
        )
        return response.choices[0].message.content
    except Exception as exc:
        logger.error("OpenAI API error: %s", exc)
        return _FALLBACK.get(language, _FALLBACK["ro"])
