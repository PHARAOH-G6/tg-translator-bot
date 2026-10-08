import asyncio
import logging
import os
import time
import random

from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from deep_translator import GoogleTranslator
from langdetect import detect, DetectorFactory

# ================== НАСТРОЙКИ ==================
BOT_TOKEN = os.environ["BOT_TOKEN"]
DEEPL_KEY = os.environ.get("DEEPL_KEY", "")
# Render даёт RENDER_EXTERNAL_URL автоматически
WEBHOOK_HOST = os.environ.get("RENDER_EXTERNAL_URL", "")
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"
PORT = int(os.environ.get("PORT", 10000))
# ===============================================

DetectorFactory.seed = 0

LANGUAGES = {
    "ru": "🇷🇺 Русский",
    "en": "🇬🇧 English",
    "de": "🇩🇪 Deutsch",
    "fr": "🇫🇷 Français",
    "es": "🇪🇸 Español",
    "it": "🇮🇹 Italiano",
    "uk": "🇺🇦 Українська",
    "tr": "🇹🇷 Türkçe",
    "zh-CN": "🇨🇳 中文",
    "ja": "🇯🇵 日本語",
}

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# Глобальное хранилище выбранного языка: {user_id: lang_code}
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


# ---------------- ДВИЖКИ ----------------

_google_last_call = 0.0
GOOGLE_MIN_INTERVAL = 1.1


def translate_google(text: str, target: str) -> str | None:
    global _google_last_call
    try:
        elapsed = time.time() - _google_last_call
        if elapsed < GOOGLE_MIN_INTERVAL:
            time.sleep(GOOGLE_MIN_INTERVAL - elapsed)

        last_error = None
        for attempt in range(3):
            try:
                result = GoogleTranslator(source="auto", target=target).translate(text)
                _google_last_call = time.time()
                return result
            except Exception as e:
                last_error = e
                msg = str(e).lower()
                if "too many requests" in msg or "429" in msg:
                    wait = (2 ** attempt) + random.uniform(0.5, 1.5)
                    logging.info(f"Google rate limit, ждём {wait:.1f} сек...")
                    time.sleep(wait)
                    continue
                raise

        logging.warning(f"Google error after retries: {last_error}")
        return None
    except Exception as e:
        logging.warning(f"Google error: {e}")
        return None


async def get_variants(text: str, target: str):
    variants = []
    seen = set()

    g = await asyncio.to_thread(translate_google, text, target)
    if isinstance(g, str) and g.strip():
        cleaned = g.strip()
        seen.add(cleaned.lower().strip(" .,!?;:—-"))
        variants.append(("Google", cleaned))

    return variants


# ---------------- ХЕНДЛЕРЫ ----------------

@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_lang[message.from_user.id] = "en"
    await message.answer(
        "👋 Привет! Я перевожу через <b>Google</b>.\n\n"
        "В личке: отправь текст — получишь перевод.\n"
        "В группе: упомяни меня (@username) или используй /lang и /help.\n\n"
        "/lang — сменить язык"
    )


@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "📖 <b>Как пользоваться:</b>\n\n"
        "1. Выбери язык командой /lang\n"
        "2. Отправь текст (в группе — упомяни меня)\n"
        "3. Получи перевод\n\n"
        "Исходный язык определяется автоматически."
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
    # В группах бот отвечает только когда его упомянули
    if message.chat.type in ("group", "supergroup"):
        bot_username = (await bot.me()).username
        mentioned = f"@{bot_username}" in (message.text or "")
        if not mentioned:
            return
        # Убираем упоминание из текста
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
    for name, translated in variants:
        lines.append(f"<b>{name}:</b>\n{translated}\n")

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
    webhook_requests_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    webhook_requests_handler.register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=PORT)
    await site.start()

    logging.info(f"Вебхук-сервер запущен на порту {PORT}")
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())