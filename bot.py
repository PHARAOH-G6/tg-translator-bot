import asyncio
import logging
import os
import json
import urllib.request
import urllib.error

from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

# ================== НАСТРОЙКИ ==================
BOT_TOKEN = os.environ["BOT_TOKEN"]
WEBHOOK_HOST = os.environ.get("RENDER_EXTERNAL_URL", "")
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"
PORT = int(os.environ.get("PORT", 10000))

# Провайдеры (KeylessAI -> Pollinations)
KEYLESS_API_URL = "https://keylessai.thryx.workers.dev/v1/chat/completions"
POLLINATIONS_API_URL = "https://gen.pollinations.ai/v1/chat/completions"

LANGUAGES = {
    "ru": "🇷🇺 Русский", "en": "🇬🇧 English", "de": "🇩🇪 Deutsch",
    "fr": "🇫🇷 Français", "es": "🇪🇸 Español", "it": "🇮🇹 Italiano",
    "uk": "🇺🇦 Українська", "tr": "🇹🇷 Türkçe", "zh-CN": "🇨🇳 中文", "ja": "🇯🇵 日本語",
}

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
user_lang = {}


def lang_keyboard():
    buttons, row = [], []
    for code, name in LANGUAGES.items():
        row.append(InlineKeyboardButton(text=name, callback_data=f"lang:{code}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ---------------- ПЕРЕВОД (С ФОЛБЭКОМ) ----------------

def translate_via_keyless(text: str, target_lang: str) -> str:
    """Основной провайдер — KeylessAI"""
    prompt = f"Translate the following text to {target_lang}. Output only the translation, without explanations.\n\n{text}"
    payload = {
        "model": "openai-fast",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        KEYLESS_API_URL, data=data,
        headers={"Content-Type": "application/json", "Authorization": "Bearer not-needed"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        return result["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logging.warning(f"KeylessAI failed: {e}")
        return ""


def translate_via_pollinations(text: str, target_lang: str) -> str:
    """Резервный провайдер — Pollinations (требует API-ключ, но работает стабильно)"""
    prompt = f"Translate the following text to {target_lang}. Output only the translation, without explanations.\n\n{text}"
    payload = {
        "model": "openai",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        POLLINATIONS_API_URL, data=data,
        headers={"Content-Type": "application/json", "Authorization": "Bearer not-needed"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        return result["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logging.warning(f"Pollinations failed: {e}")
        return ""


def translate_with_fallback(text: str, target_lang: str) -> tuple[str, str]:
    """Пробует KeylessAI, потом Pollinations. Возвращает (провайдер, перевод)."""
    result = translate_via_keyless(text, target_lang)
    if result:
        return ("KeylessAI", result)
    
    result = translate_via_pollinations(text, target_lang)
    if result:
        return ("Pollinations", result)
    
    return ("", "")


async def get_variants(text: str, target: str):
    variants = []
    provider, result = await asyncio.to_thread(translate_with_fallback, text, target)
    if result:
        variants.append((provider, result))
    return variants
