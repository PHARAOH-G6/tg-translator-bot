import asyncio
import logging
import os
import time
import random
import requests

from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from langdetect import detect, DetectorFactory

# ================== НАСТРОЙКИ ==================
BOT_TOKEN = os.environ["BOT_TOKEN"]
DEEPLX_API_URL = os.environ.get("DEEPLX_API_URL", "https://api.deeplx.org/translate")
WEBHOOK_HOST = os.environ.get("RENDER_EXTERNAL_URL", "")
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"
PORT = int(os.environ.get("PORT", 10000))
# ===============================================

DetectorFactory.seed = 0

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


# ---------------- ДВИЖОК DEEPLX ----------------

_deeplx_last_call = 0.0
DEEPLX_MIN_INTERVAL = 1.5  # Пауза, чтобы не поймать 429


def translate_deeplx(text: str, target: str) -> list[str]:
    """Перевод через DeepLX с запросом вариантов."""
    global _deeplx_last_call
    try:
        # Пауза между запросами
        elapsed = time.time() - _deeplx_last_call
        if elapsed < DEEPLX_MIN_INTERVAL:
            time.sleep(DEEPLX_MIN_INTERVAL - elapsed)

        # DeepLX использует коды вида EN, RU, DE
        target_code = {"zh-CN": "ZH"}.get(target, target.upper())
        
        payload = {
            "text": text,
            "source_lang": "auto",
            "target_lang": target_code
        }
        
        # Запрашиваем 3 варианта перевода
        response = requests.post(DEEPLX_API_URL, json=payload, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        _deeplx_last_call = time.time()
        
        # DeepLX возвращает основной перевод в 'data' и варианты в 'alternatives'
        results = [data.get("data")]
        if "alternatives" in data:
            results.extend(data["alternatives"])
        
        # Убираем пустые и дубликаты
        seen = set()
        unique_results = []
        for r in results:
            if isinstance(r, str) and r.strip():
                key = r.lower().strip()
                if key not in seen:
                    seen.add(key)
                    unique_results.append(r.strip())
        
        return unique_results

    except Exception as e:
        logging.warning(f"DeepLX error: {e}")
        return []


async def get_variants(text: str, target: str):
    variants = []
    seen = set()

    results = await asyncio.to_thread(translate_deeplx, text, target)
    
    for r in results:
        key = r.lower().strip(" .,!?;:—-")
        if key not in seen:
            seen.add(key)
            variants.append(("DeepLX", r))

    return variants


# ---------------- ХЕНДЛЕРЫ ----------------

@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_lang[message.from_user.id] = "en"
    await message.answer(
        "👋 Привет! Я перевожу через <b>DeepLX</b>.\n\n"
        "Отправь текст — получишь до 3 вариантов перевода.\n"
        "/lang — сменить язык"
    )


@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "📖 <b>Как пользоваться:</b>\n\n"
        "1. Выбери язык командой /lang\n"
        "2. Отправь текст (в группе — упомяни меня)\n"
        "3. Получи до 3 вариантов перевода"
    )


@dp.message(Command("lang"))
async def cmd_lang(message: Message):
    await message.answer("🌍 Выбери язык перевода:", reply_markup=lang_keyboard())


@dp.callback_query(F.data.startswith("lang:"))
async def on_lang_selected(callback: CallbackQuery):
    code = callback.data.split(":")[1]
    user_lang[callback.from_user.id] = code
    await callback.message.edit_text(f"✅ Язык перевода: <b>{LANGUAGES.get(code, code)}</b>")
    await callback.answer()


@dp.message(F.text)
async def translate_message(message: Message):
    if message.chat.type in ("group", "supergroup"):
        bot_username = (await bot.me()).username
        if f"@{bot_username}" not in (message.text or ""):
            return
        text = message.text.replace(f"@{bot_username}", "").strip()
    else:
        text = message.text.strip()

    if not text:
        return

    target = user_lang.get(message.from_user.id, "en")
    await bot.send_chat_action(message.chat.id, "typing")

    variants = await get_variants(text, target)

    if not variants:
        await message.reply("⚠️ Не удалось перевести. Попробуй позже или смени язык (/lang).")
        return

    lines = [f"🌍 <b>{LANGUAGES.get(target, target)}</b>\n"]
    for i, (name, translated) in enumerate(variants, 1):
        lines.append(f"<b>Вариант {i}:</b>\n{translated}\n")

    await message.reply("\n".join(lines))


# ---------------- WEBHOOK ----------------

async def on_startup(bot: Bot):
    logging.info(f"Устанавливаю webhook: {WEBHOOK_URL}")
    await bot.set_webhook(WEBHOOK_URL, drop_pending_updates=True)
    logging.info("Webhook установлен")


async def on_shutdown(bot: Bot):
    await bot.delete_webhook()


async def main():
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    app = web.Application()
    handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    handler.register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=PORT)
    await site.start()

    logging.info(f"Вебхук-сервер запущен на порту {PORT}")
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
