import html
import logging
import os

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from database import obtener_bot
from registro_bots import (
    borrar_bot,
    cambiar_estado,
    crear_bot_desde_datos,
    teclado_confirmar_eliminacion,
    teclado_detalle_bot,
    teclado_lista_bots,
    texto_detalle_bot,
    texto_lista_bots,
)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

VERSION = "1.1 — REGISTRO DE BOTS"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

(
    REGISTRO_NOMBRE,
    REGISTRO_USERNAME,
    REGISTRO_DESCRIPCION,
    REGISTRO_REPOSITORIO,
    REGISTRO_SERVIDOR,
    REGISTRO_RUTA_PROYECTO,
    REGISTRO_RUTA_DATABASE,
    REGISTRO_CONFIRMACION,
) = range(8)


def autorizado(user_id: int) -> bool:
    return ADMIN_ID == 0 or int(user_id) == ADMIN_ID


def limpiar_registro(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("registro_bot", None)


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


def teclado_cancelar_registro() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "❌ Cancelar registro",
                    callback_data="bot_registro_cancelar",
                )
            ],
            [
                InlineKeyboardButton(
                    "🏠 Menú Principal",
                    callback_data="home",
                )
            ],
        ]
    )


def teclado_omitir_registro() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "⏭ Omitir",
                    callback_data="bot_registro_omitir",
                )
            ],
            [
                InlineKeyboardButton(
                    "❌ Cancelar",
                    callback_data="bot_registro_cancelar",
                ),
                InlineKeyboardButton(
                    "🏠 Menú Principal",
                    callback_data="home",
                ),
            ],
        ]
    )


def teclado_confirmar_registro() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Guardar Bot",
                    callback_data="bot_registro_guardar",
                )
            ],
            [
                InlineKeyboardButton(
                    "❌ Cancelar",
                    callback_data="bot_registro_cancelar",
                ),
                InlineKeyboardButton(
                    "🏠 Menú Principal",
                    callback_data="home",
                ),
            ],
        ]
    )


def valor_visual(valor) -> str:
    contenido = str(valor or "").strip()
    return html.escape(contenido) if contenido else "No configurado"


def resumen_registro(datos: dict) -> str:
    return (
        "🤖 <b>CONFIRMAR REGISTRO</b>\n\n"
        f"📛 Nombre:\n<b>{valor_visual(datos.get('nombre'))}</b>\n\n"
        f"👤 Usuario:\n{valor_visual(datos.get('username'))}\n\n"
        f"📝 Descripción:\n"
        f"{valor_visual(datos.get('descripcion'))}\n\n"
        f"🌐 Repositorio:\n"
        f"{valor_visual(datos.get('repositorio'))}\n\n"
        f"🖥 Servidor:\n"
        f"{valor_visual(datos.get('servidor'))}\n\n"
        f"📂 Ruta del proyecto:\n"
        f"{valor_visual(datos.get('ruta_proyecto'))}\n\n"
        f"🗃 Ruta de base de datos:\n"
        f"{valor_visual(datos.get('ruta_base_datos'))}\n\n"
        "Confirma para guardar este bot."
    )


async def mostrar_inicio(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    texto = (
        "🛡️ <b>BOT RESPALDOS PREMIUM</b>\n\n"
        "Centro independiente de respaldo, monitoreo "
        "y recuperación de bots de Telegram.\n\n"
        f"Versión: <b>{html.escape(VERSION)}</b>"
    )

    if update.callback_query:
        await update.callback_query.edit_message_text(
            texto,
            parse_mode="HTML",
            reply_markup=teclado_principal(),
        )
    else:
        await update.effective_message.reply_text(
            texto,
            parse_mode="HTML",
            reply_markup=teclado_principal(),
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

    limpiar_registro(context)
    await mostrar_inicio(update, context)


async def cancelar_comando(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    limpiar_registro(context)

    await update.effective_message.reply_text(
        "❌ Operación cancelada.",
        reply_markup=teclado_principal(),
    )
    return ConversationHandler.END


async def iniciar_registro(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    query = update.callback_query
    await query.answer()

    if not autorizado(query.from_user.id):
        await query.answer("No autorizado.", show_alert=True)
        return ConversationHandler.END

    context.user_data["registro_bot"] = {}

    await query.edit_message_text(
        "➕ <b>REGISTRAR BOT</b>\n\n"
        "Escribe el <b>nombre visible</b> del bot.\n\n"
        "Ejemplo:\n"
        "<code>Publicidad Control Streaming</code>",
        parse_mode="HTML",
        reply_markup=teclado_cancelar_registro(),
    )
    return REGISTRO_NOMBRE


async def recibir_nombre(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    nombre = str(update.effective_message.text or "").strip()

    if not nombre:
        await update.effective_message.reply_text(
            "⚠️ El nombre no puede estar vacío."
        )
        return REGISTRO_NOMBRE

    context.user_data.setdefault("registro_bot", {})["nombre"] = nombre

    await update.effective_message.reply_text(
        "👤 Escribe el <b>usuario de Telegram</b> del bot.\n\n"
        "Ejemplo:\n"
        "<code>@PublicidadControlStreamingBot</code>\n\n"
        "También puedes omitirlo.",
        parse_mode="HTML",
        reply_markup=teclado_omitir_registro(),
    )
    return REGISTRO_USERNAME


async def recibir_username(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    username = str(update.effective_message.text or "").strip()

    if username and not username.startswith("@"):
        username = f"@{username}"

    context.user_data["registro_bot"]["username"] = username

    await update.effective_message.reply_text(
        "📝 Escribe una <b>descripción</b> del bot.\n\n"
        "También puedes omitirla.",
        parse_mode="HTML",
        reply_markup=teclado_omitir_registro(),
    )
    return REGISTRO_DESCRIPCION


async def recibir_descripcion(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    context.user_data["registro_bot"]["descripcion"] = str(
        update.effective_message.text or ""
    ).strip()

    await update.effective_message.reply_text(
        "🌐 Escribe la dirección del <b>repositorio GitHub</b>.\n\n"
        "También puedes omitirla.",
        parse_mode="HTML",
        reply_markup=teclado_omitir_registro(),
    )
    return REGISTRO_REPOSITORIO


async def recibir_repositorio(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    context.user_data["registro_bot"]["repositorio"] = str(
        update.effective_message.text or ""
    ).strip()

    await update.effective_message.reply_text(
        "🖥 Escribe el nombre del <b>servidor o plataforma</b>.\n\n"
        "Ejemplo:\n"
        "<code>JustRunMy</code>\n"
        "<code>Oracle Cloud</code>\n\n"
        "También puedes omitirlo.",
        parse_mode="HTML",
        reply_markup=teclado_omitir_registro(),
    )
    return REGISTRO_SERVIDOR


async def recibir_servidor(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    context.user_data["registro_bot"]["servidor"] = str(
        update.effective_message.text or ""
    ).strip()

    await update.effective_message.reply_text(
        "📂 Escribe la <b>ruta del proyecto</b> en el servidor.\n\n"
        "Ejemplo:\n"
        "<code>/opt/PublicidadBot</code>\n\n"
        "También puedes omitirla.",
        parse_mode="HTML",
        reply_markup=teclado_omitir_registro(),
    )
    return REGISTRO_RUTA_PROYECTO


async def recibir_ruta_proyecto(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    context.user_data["registro_bot"]["ruta_proyecto"] = str(
        update.effective_message.text or ""
    ).strip()

    await update.effective_message.reply_text(
        "🗃 Escribe la <b>ruta de la base de datos</b>.\n\n"
        "Ejemplo:\n"
        "<code>/app/data/publicidad.db</code>\n\n"
        "También puedes omitirla.",
        parse_mode="HTML",
        reply_markup=teclado_omitir_registro(),
    )
    return REGISTRO_RUTA_DATABASE


async def recibir_ruta_database(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    context.user_data["registro_bot"]["ruta_base_datos"] = str(
        update.effective_message.text or ""
    ).strip()

    datos = context.user_data["registro_bot"]

    await update.effective_message.reply_text(
        resumen_registro(datos),
        parse_mode="HTML",
        reply_markup=teclado_confirmar_registro(),
    )
    return REGISTRO_CONFIRMACION


async def omitir_campo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    query = update.callback_query
    await query.answer()

    estado = context.user_data.get("registro_estado")

    if estado is None:
        return ConversationHandler.END

    return ConversationHandler.END


async def cancelar_registro_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    query = update.callback_query
    await query.answer()

    limpiar_registro(context)

    await query.edit_message_text(
        "❌ Registro cancelado.",
        reply_markup=teclado_principal(),
    )
    return ConversationHandler.END


async def guardar_registro(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    query = update.callback_query
    await query.answer()

    datos = context.user_data.get("registro_bot", {})
    correcto, mensaje, bot_id = crear_bot_desde_datos(datos)

    if not correcto:
        await query.edit_message_text(
            f"❌ <b>No se pudo registrar el bot</b>\n\n"
            f"{html.escape(mensaje)}",
            parse_mode="HTML",
            reply_markup=teclado_lista_bots(),
        )
        limpiar_registro(context)
        return ConversationHandler.END

    limpiar_registro(context)

    bot = obtener_bot(bot_id)
    texto = texto_detalle_bot(bot_id)

    await query.edit_message_text(
        "✅ <b>BOT REGISTRADO CORRECTAMENTE</b>\n\n"
        + (texto or ""),
        parse_mode="HTML",
        reply_markup=teclado_detalle_bot(
            bot_id,
            bot["estado"] if bot else "ACTIVO",
        ),
    )
    return ConversationHandler.END


async def botones_generales(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    query = update.callback_query
    await query.answer()

    if not autorizado(query.from_user.id):
        await query.answer("No autorizado.", show_alert=True)
        return

    opcion = query.data

    if opcion == "home":
        limpiar_registro(context)
        await mostrar_inicio(update, context)
        return

    if opcion == "bots":
        await query.edit_message_text(
            texto_lista_bots(),
            parse_mode="HTML",
            reply_markup=teclado_lista_bots(),
        )
        return

    if opcion.startswith("bot_detalle:"):
        bot_id = int(opcion.split(":")[1])
        bot = obtener_bot(bot_id)
        texto = texto_detalle_bot(bot_id)

        if not bot or not texto:
            await query.answer(
                "El bot ya no existe.",
                show_alert=True,
            )
            return

        await query.edit_message_text(
            texto,
            parse_mode="HTML",
            reply_markup=teclado_detalle_bot(
                bot_id,
                bot["estado"],
            ),
        )
        return

    if opcion.startswith("bot_estado:"):
        _, bot_id, estado = opcion.split(":")
        correcto, mensaje = cambiar_estado(
            int(bot_id),
            estado,
        )

        await query.answer(mensaje, show_alert=not correcto)

        bot = obtener_bot(int(bot_id))
        texto = texto_detalle_bot(int(bot_id))

        if bot and texto:
            await query.edit_message_text(
                texto,
                parse_mode="HTML",
                reply_markup=teclado_detalle_bot(
                    int(bot_id),
                    bot["estado"],
                ),
            )
        return

    if opcion.startswith("bot_eliminar_confirmar:"):
        bot_id = int(opcion.split(":")[1])
        correcto, mensaje = borrar_bot(bot_id)

        await query.answer(mensaje, show_alert=not correcto)

        await query.edit_message_text(
            texto_lista_bots(),
            parse_mode="HTML",
            reply_markup=teclado_lista_bots(),
        )
        return

    if opcion.startswith("bot_eliminar:"):
        bot_id = int(opcion.split(":")[1])
        bot = obtener_bot(bot_id)

        if not bot:
            await query.answer("El bot no existe.", show_alert=True)
            return

        await query.edit_message_text(
            "⚠️ <b>CONFIRMAR ELIMINACIÓN</b>\n\n"
            f"¿Deseas eliminar del registro a:\n\n"
            f"<b>{html.escape(str(bot['nombre']))}</b>?\n\n"
            "Esto elimina el registro administrativo, "
            "pero no borra el bot ni sus archivos.",
            parse_mode="HTML",
            reply_markup=teclado_confirmar_eliminacion(bot_id),
        )
        return

    if opcion.startswith("bot_backup:"):
        await query.answer(
            "El respaldo real se integrará en la siguiente mejora.",
            show_alert=True,
        )
        return

    if opcion.startswith("bot_restore:"):
        await query.answer(
            "La restauración se integrará en una mejora posterior.",
            show_alert=True,
        )
        return

    if opcion.startswith("bot_history:"):
        await query.answer(
            "Todavía no existen respaldos para este bot.",
            show_alert=True,
        )
        return

    if opcion.startswith("bot_editar:"):
        await query.answer(
            "La edición se integrará en la siguiente ampliación.",
            show_alert=True,
        )
        return

    if opcion == "backup":
        texto = (
            "💾 <b>CREAR RESPALDO</b>\n\n"
            "Primero registra los bots que deseas proteger."
        )

    elif opcion == "restore":
        texto = (
            "📥 <b>RESTAURAR RESPALDO</b>\n\n"
            "La restauración estará disponible cuando "
            "existan respaldos registrados."
        )

    elif opcion == "history":
        texto = (
            "📂 <b>HISTORIAL DE RESPALDOS</b>\n\n"
            "Todavía no existen respaldos registrados."
        )

    elif opcion == "status":
        texto = (
            "❤️ <b>ESTADO DE BOTS</b>\n\n"
            "El monitoreo automático se integrará "
            "en una próxima mejora."
        )

    elif opcion == "settings":
        texto = (
            "⚙️ <b>CONFIGURACIÓN</b>\n\n"
            "Desde <b>Bots Registrados</b> puedes agregar "
            "los proyectos que administrará este sistema."
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


async def registro_omitir_username(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["registro_bot"]["username"] = None

    await query.edit_message_text(
        "📝 Escribe una <b>descripción</b> del bot.\n\n"
        "También puedes omitirla.",
        parse_mode="HTML",
        reply_markup=teclado_omitir_registro(),
    )
    return REGISTRO_DESCRIPCION


async def registro_omitir_descripcion(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["registro_bot"]["descripcion"] = None

    await query.edit_message_text(
        "🌐 Escribe la dirección del <b>repositorio GitHub</b>.\n\n"
        "También puedes omitirla.",
        parse_mode="HTML",
        reply_markup=teclado_omitir_registro(),
    )
    return REGISTRO_REPOSITORIO


async def registro_omitir_repositorio(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["registro_bot"]["repositorio"] = None

    await query.edit_message_text(
        "🖥 Escribe el nombre del <b>servidor o plataforma</b>.\n\n"
        "También puedes omitirlo.",
        parse_mode="HTML",
        reply_markup=teclado_omitir_registro(),
    )
    return REGISTRO_SERVIDOR


async def registro_omitir_servidor(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["registro_bot"]["servidor"] = None

    await query.edit_message_text(
        "📂 Escribe la <b>ruta del proyecto</b>.\n\n"
        "También puedes omitirla.",
        parse_mode="HTML",
        reply_markup=teclado_omitir_registro(),
    )
    return REGISTRO_RUTA_PROYECTO


async def registro_omitir_ruta_proyecto(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["registro_bot"]["ruta_proyecto"] = None

    await query.edit_message_text(
        "🗃 Escribe la <b>ruta de la base de datos</b>.\n\n"
        "También puedes omitirla.",
        parse_mode="HTML",
        reply_markup=teclado_omitir_registro(),
    )
    return REGISTRO_RUTA_DATABASE


async def registro_omitir_ruta_database(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["registro_bot"]["ruta_base_datos"] = None

    await query.edit_message_text(
        resumen_registro(context.user_data["registro_bot"]),
        parse_mode="HTML",
        reply_markup=teclado_confirmar_registro(),
    )
    return REGISTRO_CONFIRMACION


def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError(
            "Falta configurar BOT_TOKEN en el archivo .env"
        )

    application = Application.builder().token(BOT_TOKEN).build()

    registro_conversation = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                iniciar_registro,
                pattern=r"^bot_registrar$",
            )
        ],
        states={
            REGISTRO_NOMBRE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    recibir_nombre,
                )
            ],
            REGISTRO_USERNAME: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    recibir_username,
                ),
                CallbackQueryHandler(
                    registro_omitir_username,
                    pattern=r"^bot_registro_omitir$",
                ),
            ],
            REGISTRO_DESCRIPCION: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    recibir_descripcion,
                ),
                CallbackQueryHandler(
                    registro_omitir_descripcion,
                    pattern=r"^bot_registro_omitir$",
                ),
            ],
            REGISTRO_REPOSITORIO: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    recibir_repositorio,
                ),
                CallbackQueryHandler(
                    registro_omitir_repositorio,
                    pattern=r"^bot_registro_omitir$",
                ),
            ],
            REGISTRO_SERVIDOR: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    recibir_servidor,
                ),
                CallbackQueryHandler(
                    registro_omitir_servidor,
                    pattern=r"^bot_registro_omitir$",
                ),
            ],
            REGISTRO_RUTA_PROYECTO: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    recibir_ruta_proyecto,
                ),
                CallbackQueryHandler(
                    registro_omitir_ruta_proyecto,
                    pattern=r"^bot_registro_omitir$",
                ),
            ],
            REGISTRO_RUTA_DATABASE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    recibir_ruta_database,
                ),
                CallbackQueryHandler(
                    registro_omitir_ruta_database,
                    pattern=r"^bot_registro_omitir$",
                ),
            ],
            REGISTRO_CONFIRMACION: [
                CallbackQueryHandler(
                    guardar_registro,
                    pattern=r"^bot_registro_guardar$",
                )
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancelar_comando),
            CallbackQueryHandler(
                cancelar_registro_callback,
                pattern=r"^bot_registro_cancelar$",
            ),
            CallbackQueryHandler(
                cancelar_registro_callback,
                pattern=r"^home$",
            ),
        ],
        allow_reentry=True,
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("cancel", cancelar_comando))
    application.add_handler(registro_conversation)
    application.add_handler(CallbackQueryHandler(botones_generales))

    print(f"BOT RESPALDOS PREMIUM {VERSION} iniciado.")

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
