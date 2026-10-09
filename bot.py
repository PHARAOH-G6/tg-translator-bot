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
POLLINATIONS_KEY = os.environ["POLLINATIONS_KEY"]
WEBHOOK_HOST = os.environ.get("RENDER_EXTERNAL_URL", "")
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"
PORT = int(os.environ.get("PORT", 10000))

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


# ---------------- ПЕРЕВОД ЧЕРЕЗ POLLINATIONS ----------------

def translate_pollinations(text: str, target_lang: str) -> str:
    """Перевод через Pollinations AI с API-ключом."""
    prompt = (
        f"Translate the following text to {target_lang}. "
        f"Output only the translation, without any explanations.\n\n{text}"
    )

    payload = {
        "model": "openai",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        POLLINATIONS_API_URL,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {POLLINATIONS_KEY}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        return result["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        logging.warning(f"Pollinations HTTP {e.code}: {body[:200]}")
        return ""
    except Exception as e:
        logging.warning(f"Pollinations error: {e}")
        return ""


async def get_variants(text: str, target: str):
    variants = []
    result = await asyncio.to_thread(translate_pollinations, text, target)
    if result:
        variants.append(("Pollinations", result))
    return variants


# ---------------- ОБРАБОТЧИКИ ----------------

@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_lang[message.from_user.id] = "en"
    await message.answer(
        "👋 Привет! Я перевожу через <b>Pollinations AI</b>.\n\n"
        "Отправь текст — получишь перевод.\n"
        "/lang — сменить язык"
    )


@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "📖 <b>Как пользоваться:</b>\n\n"
        "1. Выбери язык командой /lang\n"
        "2. Отправь текст (в группе — упомяни меня)\n"
        "3. Получи перевод"
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
    target_name = LANGUAGES.get(target, "English").split(" ", 1)[-1]

    await bot.send_chat_action(message.chat.id, "typing")
    variants = await get_variants(text, target_name)

    if not variants:
        await message.reply("⚠️ Не удалось перевести. Попробуй позже или смени язык (/lang).")
        return

    lines = [f"🌍 <b>{LANGUAGES.get(target, target)}</b>\n"]
    for name, translated in variants:
        lines.append(f"<b>{name}:</b>\n{translated}\n")

    await message.reply("\n".join(lines))


# ---------------- HEALTH CHECK ДЛЯ CRON-JOB.ORG ----------------

async def health_check(request):
    """Эндпоинт для cron-job.org. Возвращает 200 OK."""
    return web.Response(text="OK")


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

    # Эндпоинт /health для cron-job.org
    app.router.add_get("/health", health_check)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=PORT)
    await site.start()

    logging.info(f"Вебхук-сервер запущен на порту {PORT}")
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
