from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
from dotenv import load_dotenv
from os import getenv

from telegramIOAdapter import TelegramIOAdapter

load_dotenv()
AUTHORIZED_USER_ID = int(getenv("TELEGRAM_USER_ID", "0"))
print(f"Usuario autorizado: {AUTHORIZED_USER_ID}")


async def is_authorized(update: Update) -> bool:
    if update.effective_user is None:
        return False
    return update.effective_user.id == AUTHORIZED_USER_ID


async def deny_access(update: Update):
    if update.effective_message is not None:
        await update.effective_message.reply_text("⛔ Acceso denegado. Este bot es privado.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_authorized(update):
        await deny_access(update)
        return

    user_id = update.effective_user.id if update.effective_user is not None else "desconocido"
    print(f"Usuario {user_id} ha iniciado el bot.")
    await update.effective_message.reply_text("Bienvenido. Envíame un mensaje y lo proceso con tu MCP client.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_authorized(update):
        await deny_access(update)
        return

    if update.effective_message is None:
        return

    user_text = (update.effective_message.text or "").strip()
    if not user_text:
        return

    adapter: TelegramIOAdapter = context.application.bot_data["io_adapter"]
    await update.effective_message.chat.send_action(action=ChatAction.TYPING)
    reply_text = await adapter.handle_user_message(user_text)
    await update.effective_message.reply_text(reply_text)


async def on_startup(app):
    adapter = TelegramIOAdapter()
    await adapter.start()
    app.bot_data["io_adapter"] = adapter


async def on_shutdown(app):
    adapter: TelegramIOAdapter | None = app.bot_data.get("io_adapter")
    if adapter is not None:
        await adapter.stop()

if __name__ == '__main__':
    bot_token = getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        raise RuntimeError("Falta TELEGRAM_BOT_TOKEN en el entorno.")
    if AUTHORIZED_USER_ID == 0:
        raise RuntimeError("Falta TELEGRAM_USER_ID válido en el entorno.")

    app = (
        ApplicationBuilder()
        .token(bot_token)
        .post_init(on_startup)
        .post_shutdown(on_shutdown)
        .build()
    )

    app.add_handler(CommandHandler('start', start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()