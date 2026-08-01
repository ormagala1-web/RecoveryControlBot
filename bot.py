import os
import logging

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

VERSION = "1.0"


def autorizado(user_id: int) -> bool:
    return ADMIN_ID == 0 or user_id == ADMIN_ID


def teclado_principal() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🤖 Bots Registrados",
                    callback_data="bots",
                )
            ],
            [
                InlineKeyboardButton(
                    "💾 Crear Respaldo",
                    callback_data="backup",
                ),
                InlineKeyboardButton(
                    "📥 Restaurar Respaldo",
                    callback_data="restore",
                ),
            ],
            [
                InlineKeyboardButton(
                    "📂 Historial",
                    callback_data="history",
                ),
                InlineKeyboardButton(
                    "❤️ Estado de Bots",
                    callback_data="status",
                ),
            ],
            [
                InlineKeyboardButton(
                    "⚙️ Configuración",
                    callback_data="settings",
                )
            ],
            [
                InlineKeyboardButton(
                    "❌ Cerrar",
                    callback_data="close",
                )
            ],
        ]
    )


def teclado_regreso() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "⬅️ Regresar",
                    callback_data="home",
                ),
                InlineKeyboardButton(
                    "❌ Cerrar",
                    callback_data="close",
                ),
            ]
        ]
    )


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    user = update.effective_user

    if not user or not autorizado(user.id):
        await update.effective_message.reply_text(
            "⛔ No tienes autorización para usar este bot."
        )
        return

    await update.effective_message.reply_text(
        "🛡️ <b>BOT RESPALDOS PREMIUM</b>\n\n"
        "Centro independiente de respaldo, monitoreo "
        "y recuperación de bots de Telegram.\n\n"
        f"Versión: <b>{VERSION}</b>",
        parse_mode="HTML",
        reply_markup=teclado_principal(),
    )


async def botones(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    query = update.callback_query
    await query.answer()

    user = query.from_user

    if not autorizado(user.id):
        await query.answer(
            "No autorizado.",
            show_alert=True,
        )
        return

    opcion = query.data

    if opcion == "home":
        await query.edit_message_text(
            "🛡️ <b>BOT RESPALDOS PREMIUM</b>\n\n"
            "Selecciona una opción:",
            parse_mode="HTML",
            reply_markup=teclado_principal(),
        )
        return

    if opcion == "bots":
        texto = (
            "🤖 <b>BOTS REGISTRADOS</b>\n\n"
            "Todavía no hay bots registrados.\n\n"
            "En la siguiente mejora podremos registrar "
            "PublicidadBot y los demás proyectos."
        )

    elif opcion == "backup":
        texto = (
            "💾 <b>CREAR RESPALDO</b>\n\n"
            "Módulo preparado.\n"
            "La creación real de respaldos se incorporará "
            "después de registrar los bots."
        )

    elif opcion == "restore":
        texto = (
            "📥 <b>RESTAURAR RESPALDO</b>\n\n"
            "Módulo preparado.\n"
            "La restauración incluirá validación y copia "
            "preventiva de la información actual."
        )

    elif opcion == "history":
        texto = (
            "📂 <b>HISTORIAL DE RESPALDOS</b>\n\n"
            "Todavía no existen respaldos registrados."
        )

    elif opcion == "status":
        texto = (
            "❤️ <b>ESTADO DE BOTS</b>\n\n"
            "Todavía no existen bots registrados "
            "para monitorear."
        )

    elif opcion == "settings":
        texto = (
            "⚙️ <b>CONFIGURACIÓN</b>\n\n"
            "Próximas opciones:\n"
            "• Registrar bots\n"
            "• Administradores\n"
            "• Respaldo automático\n"
            "• Ubicación de respaldos"
        )

    elif opcion == "close":
        await query.edit_message_text(
            "✅ Panel cerrado.\n\n"
            "Usa /start para abrirlo nuevamente."
        )
        return

    else:
        texto = "Opción no reconocida."

    await query.edit_message_text(
        texto,
        parse_mode="HTML",
        reply_markup=teclado_regreso(),
    )


def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError(
            "Falta configurar BOT_TOKEN en el archivo .env"
        )

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(
        CommandHandler("start", start)
    )
    application.add_handler(
        CallbackQueryHandler(botones)
    )

    print(
        f"BOT RESPALDOS PREMIUM versión {VERSION} iniciado."
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
