import asyncio
import html
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from database import (
    actualizar_bot,
    obtener_bot,
    obtener_respaldo,
    obtener_respaldos_bot,
    obtener_ultimos_respaldos,
)
from respaldos import crear_respaldo_bot, formatear_tamano
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
VERSION = "3.2 — DESCARGA TEMPORAL LIMPIA"

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
    EDICION_VALOR,
) = range(9)

CAMPOS = {
    "nombre": ("📛 Nombre", False),
    "username": ("👤 Usuario", True),
    "descripcion": ("📝 Descripción", True),
    "repositorio": ("🌐 Repositorio", True),
    "servidor": ("🖥 Servidor", True),
    "ruta_proyecto": ("📂 Ruta del proyecto", True),
    "ruta_base_datos": ("🗃 Ruta de la base de datos", True),
}


def autorizado(user_id: int) -> bool:
    return ADMIN_ID == 0 or int(user_id) == ADMIN_ID


def limpiar_flujos(context: ContextTypes.DEFAULT_TYPE) -> None:
    for clave in (
        "registro_bot",
        "registro_campo",
        "edicion_bot_id",
        "edicion_campo",
        "edicion_origen",
    ):
        context.user_data.pop(clave, None)



def registrar_panel(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int,
) -> None:
    context.user_data["panel_chat_id"] = int(chat_id)
    context.user_data["panel_message_id"] = int(message_id)


def registrar_panel_desde_query(
    query,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if query and query.message:
        registrar_panel(
            context,
            query.message.chat_id,
            query.message.message_id,
        )


async def borrar_mensaje_seguro(mensaje) -> None:
    if not mensaje:
        return
    try:
        await mensaje.delete()
    except TelegramError:
        pass


async def actualizar_panel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    texto: str,
    parse_mode: Optional[str] = None,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> None:
    """Mantiene un único panel y elimina el texto escrito por el usuario."""
    mensaje_usuario = update.effective_message
    chat = update.effective_chat

    # Los comandos y respuestas manuales no deben quedar visibles.
    if mensaje_usuario and not update.callback_query:
        await borrar_mensaje_seguro(mensaje_usuario)

    chat_id = context.user_data.get("panel_chat_id")
    message_id = context.user_data.get("panel_message_id")

    if chat_id and message_id:
        try:
            await context.bot.edit_message_text(
                chat_id=int(chat_id),
                message_id=int(message_id),
                text=texto,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
            )
            return
        except TelegramError:
            try:
                await context.bot.delete_message(
                    chat_id=int(chat_id),
                    message_id=int(message_id),
                )
            except TelegramError:
                pass

    if not chat:
        return

    nuevo_panel = await context.bot.send_message(
        chat_id=chat.id,
        text=texto,
        parse_mode=parse_mode,
        reply_markup=reply_markup,
    )
    registrar_panel(context, nuevo_panel.chat_id, nuevo_panel.message_id)



def teclado_principal() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🤖 Bots Registrados", callback_data="bots")],
            [
                InlineKeyboardButton("💾 Crear Respaldo", callback_data="backup"),
                InlineKeyboardButton("📥 Restaurar Respaldo", callback_data="restore"),
            ],
            [
                InlineKeyboardButton("📂 Historial", callback_data="history"),
                InlineKeyboardButton("❤️ Estado de Bots", callback_data="status"),
            ],
            [InlineKeyboardButton("⚙️ Configuración", callback_data="settings")],
            [InlineKeyboardButton("❌ Cerrar", callback_data="close")],
        ]
    )


def teclado_regreso() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("⬅️ Regresar", callback_data="home"),
            InlineKeyboardButton("❌ Cerrar", callback_data="close"),
        ]]
    )


def teclado_cancelar_registro() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("❌ Cancelar registro", callback_data="bot_registro_cancelar")],
            [InlineKeyboardButton("🏠 Menú Principal", callback_data="home")],
        ]
    )


def teclado_omitir_registro() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("⏭ Omitir", callback_data="bot_registro_omitir")],
            [
                InlineKeyboardButton("❌ Cancelar", callback_data="bot_registro_cancelar"),
                InlineKeyboardButton("🏠 Menú Principal", callback_data="home"),
            ],
        ]
    )


def teclado_confirmar_registro() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Guardar Bot", callback_data="bot_registro_guardar")],
            [InlineKeyboardButton("✏️ Editar información", callback_data="bot_registro_editar")],
            [
                InlineKeyboardButton("❌ Cancelar", callback_data="bot_registro_cancelar"),
                InlineKeyboardButton("🏠 Menú Principal", callback_data="home"),
            ],
        ]
    )


def teclado_campos_edicion(origen: str, bot_id: Optional[int] = None) -> InlineKeyboardMarkup:
    filas = []
    for clave, (etiqueta, _) in CAMPOS.items():
        callback = (
            f"bot_registro_editar_campo:{clave}"
            if origen == "registro"
            else f"bot_editar_campo:{bot_id}:{clave}"
        )
        filas.append([InlineKeyboardButton(etiqueta, callback_data=callback)])

    regreso = "bot_registro_confirmacion" if origen == "registro" else f"bot_detalle:{bot_id}"
    filas.append(
        [
            InlineKeyboardButton("⬅️ Regresar", callback_data=regreso),
            InlineKeyboardButton("🏠 Menú Principal", callback_data="home"),
        ]
    )
    filas.append([InlineKeyboardButton("❌ Cerrar", callback_data="close")])
    return InlineKeyboardMarkup(filas)


def teclado_cancelar_edicion(
    origen: str,
    bot_id: Optional[int],
    permite_vacio: bool,
) -> InlineKeyboardMarkup:
    filas = []
    if permite_vacio:
        filas.append([InlineKeyboardButton("🧹 Dejar vacío", callback_data="bot_edicion_vaciar")])

    regreso = "bot_registro_editar" if origen == "registro" else f"bot_editar:{bot_id}"
    filas.append(
        [
            InlineKeyboardButton("⬅️ Regresar", callback_data=regreso),
            InlineKeyboardButton("❌ Cancelar", callback_data="bot_edicion_cancelar"),
        ]
    )
    return InlineKeyboardMarkup(filas)


def valor_visual(valor) -> str:
    contenido = str(valor or "").strip()
    return html.escape(contenido) if contenido else "No configurado"


def resumen_registro(datos: dict) -> str:
    return (
        "🤖 <b>CONFIRMAR REGISTRO</b>\n\n"
        f"📛 Nombre:\n<b>{valor_visual(datos.get('nombre'))}</b>\n\n"
        f"👤 Usuario:\n{valor_visual(datos.get('username'))}\n\n"
        f"📝 Descripción:\n{valor_visual(datos.get('descripcion'))}\n\n"
        f"🌐 Repositorio:\n{valor_visual(datos.get('repositorio'))}\n\n"
        f"🖥 Servidor:\n{valor_visual(datos.get('servidor'))}\n\n"
        f"📂 Ruta del proyecto:\n{valor_visual(datos.get('ruta_proyecto'))}\n\n"
        f"🗃 Ruta de base de datos:\n{valor_visual(datos.get('ruta_base_datos'))}\n\n"
        "Puedes guardar o corregir cualquier campo."
    )


def texto_editor(origen: str, bot_id: Optional[int] = None) -> str:
    if origen == "registro":
        titulo = "✏️ <b>EDITAR ANTES DE GUARDAR</b>"
    else:
        bot = obtener_bot(int(bot_id)) if bot_id is not None else None
        nombre = html.escape(str(bot["nombre"] if bot else "Bot"))
        titulo = f"✏️ <b>EDITAR BOT</b>\n\n{nombre}"
    return f"{titulo}\n\nSelecciona el campo que deseas modificar:"


def normalizar_valor(campo: str, valor: str) -> str:
    valor = str(valor or "").strip()
    if campo == "username" and valor and not valor.startswith("@"):
        valor = f"@{valor}"
    return valor


async def mostrar_inicio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    texto = (
        "🛡️ <b>BOT RESPALDOS PREMIUM</b>\n\n"
        "Centro independiente de respaldo, monitoreo y recuperación "
        "de bots de Telegram.\n\n"
        f"Versión: <b>{html.escape(VERSION)}</b>"
    )
    if update.callback_query:
        registrar_panel_desde_query(update.callback_query, context)
        await update.callback_query.edit_message_text(
            texto,
            parse_mode="HTML",
            reply_markup=teclado_principal(),
        )
    else:
        await actualizar_panel(update, context,
            texto,
            parse_mode="HTML",
            reply_markup=teclado_principal(),
        )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or not autorizado(user.id):
        await actualizar_panel(update, context,"⛔ No tienes autorización para usar este bot.")
        return
    limpiar_flujos(context)
    await mostrar_inicio(update, context)


async def cancelar_comando(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    limpiar_flujos(context)
    await actualizar_panel(update, context,
        "❌ Operación cancelada.",
        reply_markup=teclado_principal(),
    )
    return ConversationHandler.END


async def iniciar_registro(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    registrar_panel_desde_query(query, context)
    if not autorizado(query.from_user.id):
        await query.answer("No autorizado.", show_alert=True)
        return ConversationHandler.END

    limpiar_flujos(context)
    context.user_data["registro_bot"] = {}
    await query.edit_message_text(
        "➕ <b>REGISTRAR BOT</b>\n\n"
        "Escribe el <b>nombre visible</b> del bot.\n\n"
        "Ejemplo:\n<code>Publicidad Control Streaming</code>",
        parse_mode="HTML",
        reply_markup=teclado_cancelar_registro(),
    )
    return REGISTRO_NOMBRE


async def recibir_nombre(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    nombre = str(update.effective_message.text or "").strip()
    if not nombre:
        await actualizar_panel(update, context,"⚠️ El nombre no puede estar vacío.")
        return REGISTRO_NOMBRE

    context.user_data.setdefault("registro_bot", {})["nombre"] = nombre
    await actualizar_panel(update, context,
        "👤 Escribe el <b>usuario de Telegram</b> del bot.\n\n"
        "Ejemplo:\n<code>@PublicidadControlStreamingBot</code>\n\n"
        "También puedes omitirlo.",
        parse_mode="HTML",
        reply_markup=teclado_omitir_registro(),
    )
    return REGISTRO_USERNAME


async def recibir_username(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["registro_bot"]["username"] = normalizar_valor(
        "username",
        update.effective_message.text,
    )
    await actualizar_panel(update, context,
        "📝 Escribe una <b>descripción</b> del bot.\n\nTambién puedes omitirla.",
        parse_mode="HTML",
        reply_markup=teclado_omitir_registro(),
    )
    return REGISTRO_DESCRIPCION


async def recibir_descripcion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["registro_bot"]["descripcion"] = str(
        update.effective_message.text or ""
    ).strip()
    await actualizar_panel(update, context,
        "🌐 Escribe la dirección del <b>repositorio GitHub</b>.\n\nTambién puedes omitirla.",
        parse_mode="HTML",
        reply_markup=teclado_omitir_registro(),
    )
    return REGISTRO_REPOSITORIO


async def recibir_repositorio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["registro_bot"]["repositorio"] = str(
        update.effective_message.text or ""
    ).strip()
    await actualizar_panel(update, context,
        "🖥 Escribe el nombre del <b>servidor o plataforma</b>.\n\n"
        "Ejemplo:\n<code>JustRunMy</code>\n<code>Oracle Cloud</code>\n\n"
        "También puedes omitirlo.",
        parse_mode="HTML",
        reply_markup=teclado_omitir_registro(),
    )
    return REGISTRO_SERVIDOR


async def recibir_servidor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["registro_bot"]["servidor"] = str(
        update.effective_message.text or ""
    ).strip()
    await actualizar_panel(update, context,
        "📂 Escribe la <b>ruta del proyecto</b> en el servidor.\n\n"
        "Ejemplo:\n<code>/opt/PublicidadBot</code>\n\nTambién puedes omitirla.",
        parse_mode="HTML",
        reply_markup=teclado_omitir_registro(),
    )
    return REGISTRO_RUTA_PROYECTO


async def recibir_ruta_proyecto(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["registro_bot"]["ruta_proyecto"] = str(
        update.effective_message.text or ""
    ).strip()
    await actualizar_panel(update, context,
        "🗃 Escribe la <b>ruta de la base de datos</b>.\n\n"
        "Ejemplo:\n<code>/app/data/publicidad.db</code>\n\nTambién puedes omitirla.",
        parse_mode="HTML",
        reply_markup=teclado_omitir_registro(),
    )
    return REGISTRO_RUTA_DATABASE


async def recibir_ruta_database(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["registro_bot"]["ruta_base_datos"] = str(
        update.effective_message.text or ""
    ).strip()
    await actualizar_panel(update, context,
        resumen_registro(context.user_data["registro_bot"]),
        parse_mode="HTML",
        reply_markup=teclado_confirmar_registro(),
    )
    return REGISTRO_CONFIRMACION


async def omitir_y_avanzar(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    campo: str,
    siguiente_estado: int,
    texto: str,
) -> int:
    query = update.callback_query
    await query.answer()

    registrar_panel_desde_query(query, context)
    context.user_data["registro_bot"][campo] = None
    await query.edit_message_text(
        texto,
        parse_mode="HTML",
        reply_markup=teclado_omitir_registro(),
    )
    return siguiente_estado


async def registro_omitir_username(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await omitir_y_avanzar(
        update,
        context,
        "username",
        REGISTRO_DESCRIPCION,
        "📝 Escribe una <b>descripción</b> del bot.\n\nTambién puedes omitirla.",
    )


async def registro_omitir_descripcion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await omitir_y_avanzar(
        update,
        context,
        "descripcion",
        REGISTRO_REPOSITORIO,
        "🌐 Escribe la dirección del <b>repositorio GitHub</b>.\n\nTambién puedes omitirla.",
    )


async def registro_omitir_repositorio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await omitir_y_avanzar(
        update,
        context,
        "repositorio",
        REGISTRO_SERVIDOR,
        "🖥 Escribe el nombre del <b>servidor o plataforma</b>.\n\nTambién puedes omitirlo.",
    )


async def registro_omitir_servidor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await omitir_y_avanzar(
        update,
        context,
        "servidor",
        REGISTRO_RUTA_PROYECTO,
        "📂 Escribe la <b>ruta del proyecto</b>.\n\nTambién puedes omitirla.",
    )


async def registro_omitir_ruta_proyecto(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await omitir_y_avanzar(
        update,
        context,
        "ruta_proyecto",
        REGISTRO_RUTA_DATABASE,
        "🗃 Escribe la <b>ruta de la base de datos</b>.\n\nTambién puedes omitirla.",
    )


async def registro_omitir_ruta_database(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    registrar_panel_desde_query(query, context)
    context.user_data["registro_bot"]["ruta_base_datos"] = None
    await query.edit_message_text(
        resumen_registro(context.user_data["registro_bot"]),
        parse_mode="HTML",
        reply_markup=teclado_confirmar_registro(),
    )
    return REGISTRO_CONFIRMACION


async def mostrar_confirmacion_registro(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    query = update.callback_query
    await query.answer()

    registrar_panel_desde_query(query, context)
    datos = context.user_data.get("registro_bot")
    if not datos:
        await query.edit_message_text(
            "⚠️ El registro ya no está disponible.",
            reply_markup=teclado_principal(),
        )
        return ConversationHandler.END

    await query.edit_message_text(
        resumen_registro(datos),
        parse_mode="HTML",
        reply_markup=teclado_confirmar_registro(),
    )
    return REGISTRO_CONFIRMACION


async def abrir_editor_registro(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    registrar_panel_desde_query(query, context)
    await query.edit_message_text(
        texto_editor("registro"),
        parse_mode="HTML",
        reply_markup=teclado_campos_edicion("registro"),
    )
    return REGISTRO_CONFIRMACION


async def seleccionar_campo_registro(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    query = update.callback_query
    await query.answer()

    registrar_panel_desde_query(query, context)
    campo = query.data.split(":", 1)[1]
    if campo not in CAMPOS:
        await query.answer("Campo no válido.", show_alert=True)
        return REGISTRO_CONFIRMACION

    context.user_data["edicion_origen"] = "registro"
    context.user_data["edicion_campo"] = campo
    etiqueta, permite_vacio = CAMPOS[campo]
    actual = context.user_data.get("registro_bot", {}).get(campo)

    await query.edit_message_text(
        f"✏️ <b>{html.escape(etiqueta)}</b>\n\n"
        f"Valor actual:\n{valor_visual(actual)}\n\n"
        "Escribe el nuevo valor.",
        parse_mode="HTML",
        reply_markup=teclado_cancelar_edicion("registro", None, permite_vacio),
    )
    return EDICION_VALOR


async def abrir_editor_bot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    registrar_panel_desde_query(query, context)
    bot_id = int(query.data.split(":")[1])
    bot = obtener_bot(bot_id)
    if not bot:
        await query.answer("El bot no existe.", show_alert=True)
        return ConversationHandler.END

    context.user_data["edicion_bot_id"] = bot_id
    context.user_data["edicion_origen"] = "guardado"
    await query.edit_message_text(
        texto_editor("guardado", bot_id),
        parse_mode="HTML",
        reply_markup=teclado_campos_edicion("guardado", bot_id),
    )
    return REGISTRO_CONFIRMACION


async def seleccionar_campo_bot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    registrar_panel_desde_query(query, context)
    _, bot_id_texto, campo = query.data.split(":", 2)
    bot_id = int(bot_id_texto)
    bot = obtener_bot(bot_id)
    if not bot or campo not in CAMPOS:
        await query.answer("Dato no disponible.", show_alert=True)
        return ConversationHandler.END

    context.user_data["edicion_bot_id"] = bot_id
    context.user_data["edicion_origen"] = "guardado"
    context.user_data["edicion_campo"] = campo
    etiqueta, permite_vacio = CAMPOS[campo]

    await query.edit_message_text(
        f"✏️ <b>{html.escape(etiqueta)}</b>\n\n"
        f"Valor actual:\n{valor_visual(bot[campo])}\n\n"
        "Escribe el nuevo valor.",
        parse_mode="HTML",
        reply_markup=teclado_cancelar_edicion("guardado", bot_id, permite_vacio),
    )
    return EDICION_VALOR


async def guardar_valor_editado(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    campo = context.user_data.get("edicion_campo")
    origen = context.user_data.get("edicion_origen")
    if campo not in CAMPOS or origen not in {"registro", "guardado"}:
        limpiar_flujos(context)
        await actualizar_panel(update, context,
            "⚠️ La edición expiró.",
            reply_markup=teclado_principal(),
        )
        return ConversationHandler.END

    valor = normalizar_valor(campo, update.effective_message.text)
    _, permite_vacio = CAMPOS[campo]
    if not valor and not permite_vacio:
        await actualizar_panel(update, context,"⚠️ Este campo no puede quedar vacío.")
        return EDICION_VALOR

    if origen == "registro":
        context.user_data.setdefault("registro_bot", {})[campo] = valor or None
        context.user_data.pop("edicion_campo", None)
        context.user_data.pop("edicion_origen", None)
        await actualizar_panel(update, context,
            resumen_registro(context.user_data["registro_bot"]),
            parse_mode="HTML",
            reply_markup=teclado_confirmar_registro(),
        )
        return REGISTRO_CONFIRMACION

    bot_id = int(context.user_data["edicion_bot_id"])
    actualizado = actualizar_bot(bot_id, **{campo: valor or None})
    bot = obtener_bot(bot_id)
    texto = texto_detalle_bot(bot_id)

    if not actualizado or not bot or not texto:
        await actualizar_panel(update, context,
            "❌ No se pudo actualizar el dato.",
            reply_markup=teclado_principal(),
        )
        limpiar_flujos(context)
        return ConversationHandler.END

    await actualizar_panel(update, context,
        "✅ <b>INFORMACIÓN ACTUALIZADA</b>\n\n" + texto,
        parse_mode="HTML",
        reply_markup=teclado_detalle_bot(bot_id, bot["estado"]),
    )
    limpiar_flujos(context)
    return ConversationHandler.END


async def vaciar_valor_editado(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    query = update.callback_query
    await query.answer()

    registrar_panel_desde_query(query, context)
    campo = context.user_data.get("edicion_campo")
    origen = context.user_data.get("edicion_origen")
    if campo not in CAMPOS or not CAMPOS[campo][1]:
        await query.answer("Este campo no puede quedar vacío.", show_alert=True)
        return EDICION_VALOR

    if origen == "registro":
        context.user_data.setdefault("registro_bot", {})[campo] = None
        context.user_data.pop("edicion_campo", None)
        context.user_data.pop("edicion_origen", None)
        await query.edit_message_text(
            resumen_registro(context.user_data["registro_bot"]),
            parse_mode="HTML",
            reply_markup=teclado_confirmar_registro(),
        )
        return REGISTRO_CONFIRMACION

    bot_id = int(context.user_data["edicion_bot_id"])
    actualizar_bot(bot_id, **{campo: None})
    bot = obtener_bot(bot_id)
    texto = texto_detalle_bot(bot_id)
    await query.edit_message_text(
        "✅ <b>INFORMACIÓN ACTUALIZADA</b>\n\n" + (texto or ""),
        parse_mode="HTML",
        reply_markup=teclado_detalle_bot(
            bot_id,
            bot["estado"] if bot else "ACTIVO",
        ),
    )
    limpiar_flujos(context)
    return ConversationHandler.END


async def cancelar_edicion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    registrar_panel_desde_query(query, context)
    origen = context.user_data.get("edicion_origen")
    bot_id = context.user_data.get("edicion_bot_id")
    context.user_data.pop("edicion_campo", None)
    context.user_data.pop("edicion_origen", None)

    if origen == "registro" and context.user_data.get("registro_bot"):
        await query.edit_message_text(
            resumen_registro(context.user_data["registro_bot"]),
            parse_mode="HTML",
            reply_markup=teclado_confirmar_registro(),
        )
        return REGISTRO_CONFIRMACION

    if bot_id:
        bot = obtener_bot(int(bot_id))
        texto = texto_detalle_bot(int(bot_id))
        await query.edit_message_text(
            texto or "Bot no encontrado.",
            parse_mode="HTML",
            reply_markup=teclado_detalle_bot(
                int(bot_id),
                bot["estado"] if bot else "ACTIVO",
            ),
        )
    else:
        await query.edit_message_text(
            texto_lista_bots(),
            parse_mode="HTML",
            reply_markup=teclado_lista_bots(),
        )

    limpiar_flujos(context)
    return ConversationHandler.END


async def cancelar_registro_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    query = update.callback_query
    await query.answer()

    registrar_panel_desde_query(query, context)
    limpiar_flujos(context)
    await query.edit_message_text(
        "❌ Registro cancelado.",
        reply_markup=teclado_principal(),
    )
    return ConversationHandler.END


async def guardar_registro(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    registrar_panel_desde_query(query, context)
    datos = context.user_data.get("registro_bot", {})
    correcto, mensaje, bot_id = crear_bot_desde_datos(datos)

    if not correcto:
        await query.edit_message_text(
            f"❌ <b>No se pudo registrar el bot</b>\n\n{html.escape(mensaje)}",
            parse_mode="HTML",
            reply_markup=teclado_confirmar_registro(),
        )
        return REGISTRO_CONFIRMACION

    limpiar_flujos(context)
    bot = obtener_bot(bot_id)
    texto = texto_detalle_bot(bot_id)
    await query.edit_message_text(
        "✅ <b>BOT REGISTRADO CORRECTAMENTE</b>\n\n" + (texto or ""),
        parse_mode="HTML",
        reply_markup=teclado_detalle_bot(
            bot_id,
            bot["estado"] if bot else "ACTIVO",
        ),
    )
    return ConversationHandler.END


def formatear_fecha_historial(fecha_iso: str) -> str:
    valor = str(fecha_iso or "").strip()
    if not valor:
        return "Sin fecha"

    try:
        fecha = datetime.fromisoformat(valor.replace("Z", "+00:00"))
        return fecha.strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return valor


def texto_historial_bot(bot_id: int) -> str:
    bot = obtener_bot(bot_id)
    respaldos = obtener_respaldos_bot(bot_id, limite=20)

    if not bot:
        return "❌ Bot no encontrado."

    nombre = html.escape(str(bot["nombre"] or "Bot"))

    if not respaldos:
        return (
            "📂 <b>HISTORIAL DE RESPALDOS</b>\n\n"
            f"🤖 <b>{nombre}</b>\n\n"
            "Todavía no existen respaldos registrados."
        )

    return (
        "📂 <b>HISTORIAL DE RESPALDOS</b>\n\n"
        f"🤖 <b>{nombre}</b>\n"
        f"📦 Total mostrado: <b>{len(respaldos)}</b>\n\n"
        "Selecciona un respaldo para ver sus detalles."
    )


def teclado_historial_bot(bot_id: int) -> InlineKeyboardMarkup:
    respaldos = obtener_respaldos_bot(bot_id, limite=20)
    filas = []

    for respaldo in respaldos:
        fecha = formatear_fecha_historial(respaldo["fecha_creacion"])
        tamano = formatear_tamano(respaldo["tamano_bytes"])
        filas.append(
            [
                InlineKeyboardButton(
                    f"📦 #{respaldo['id']} · {fecha} · {tamano}",
                    callback_data=f"respaldo_detalle:{respaldo['id']}",
                )
            ]
        )

    filas.append(
        [
            InlineKeyboardButton(
                "⬅️ Volver al bot",
                callback_data=f"bot_detalle:{bot_id}",
            ),
            InlineKeyboardButton(
                "🏠 Inicio",
                callback_data="home",
            ),
        ]
    )
    return InlineKeyboardMarkup(filas)


def texto_detalle_respaldo(respaldo_id: int) -> str:
    respaldo = obtener_respaldo(respaldo_id)

    if not respaldo:
        return "❌ Respaldo no encontrado."

    archivo = html.escape(str(respaldo["archivo"] or "Sin nombre"))
    bot_nombre = html.escape(str(respaldo["bot_nombre"] or "Bot"))
    fecha = html.escape(formatear_fecha_historial(respaldo["fecha_creacion"]))
    tamano = html.escape(formatear_tamano(respaldo["tamano_bytes"]))
    estado = html.escape(str(respaldo["estado"] or "DESCONOCIDO"))
    tipo = html.escape(str(respaldo["tipo"] or "MANUAL"))
    sha256 = html.escape(str(respaldo["sha256"] or "No disponible"))
    observacion = html.escape(str(respaldo["observacion"] or "Sin observaciones"))

    return (
        "📦 <b>DETALLE DEL RESPALDO</b>\n\n"
        f"🆔 ID: <code>{respaldo['id']}</code>\n"
        f"🤖 Bot: <b>{bot_nombre}</b>\n"
        f"📅 Fecha: <b>{fecha}</b>\n"
        f"📏 Tamaño: <b>{tamano}</b>\n"
        f"⚙️ Tipo: <b>{tipo}</b>\n"
        f"📊 Estado: <b>{estado}</b>\n\n"
        f"📄 Archivo:\n<code>{archivo}</code>\n\n"
        f"🔐 SHA-256:\n<code>{sha256}</code>\n\n"
        f"📝 Observación:\n{observacion}"
    )


def teclado_detalle_respaldo(
    respaldo_id: int,
    bot_id: int,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "⬇️ Descargar respaldo",
                    callback_data=f"respaldo_descargar:{respaldo_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    "♻️ Restaurar",
                    callback_data=f"respaldo_restaurar:{respaldo_id}",
                ),
                InlineKeyboardButton(
                    "🗑 Eliminar",
                    callback_data=f"respaldo_eliminar:{respaldo_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Historial",
                    callback_data=f"bot_history:{bot_id}",
                ),
                InlineKeyboardButton(
                    "🏠 Inicio",
                    callback_data="home",
                ),
            ],
        ]
    )


async def eliminar_documento_temporal(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int,
    segundos: int = 600,
) -> None:
    await asyncio.sleep(segundos)

    try:
        await context.bot.delete_message(
            chat_id=chat_id,
            message_id=message_id,
        )
    except TelegramError:
        pass


async def descargar_respaldo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    respaldo_id: int,
) -> None:
    query = update.callback_query
    respaldo = obtener_respaldo(respaldo_id)

    if not respaldo:
        await query.answer("El respaldo no existe.", show_alert=True)
        return

    ruta = Path(str(respaldo["ruta"] or ""))

    if not ruta.exists() or not ruta.is_file():
        await query.answer(
            "El archivo del respaldo no está disponible.",
            show_alert=True,
        )
        return

    await query.answer("Preparando descarga temporal…")

    with ruta.open("rb") as archivo:
        documento = await context.bot.send_document(
            chat_id=query.message.chat_id,
            document=archivo,
            filename=str(respaldo["archivo"]),
            caption=(
                f"📦 Respaldo #{respaldo_id}\n"
                f"🤖 {respaldo['bot_nombre']}\n"
                f"🔐 SHA-256: {respaldo['sha256'] or 'No disponible'}\n\n"
                "⏳ Este archivo se eliminará automáticamente en 10 minutos."
            ),
        )

    asyncio.create_task(
        eliminar_documento_temporal(
            context,
            documento.chat_id,
            documento.message_id,
            segundos=600,
        )
    )

    await query.edit_message_text(
        texto_detalle_respaldo(respaldo_id)
        + "\n\n✅ <b>DESCARGA TEMPORAL ENVIADA</b>\n"
        "El archivo desaparecerá del chat en 10 minutos.",
        parse_mode="HTML",
        reply_markup=teclado_detalle_respaldo(
            respaldo_id,
            int(respaldo["bot_id"]),
        ),
    )


def teclado_confirmar_respaldo(bot_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Crear respaldo ahora",
                    callback_data=f"bot_backup_confirmar:{bot_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Regresar",
                    callback_data=f"bot_detalle:{bot_id}",
                ),
                InlineKeyboardButton(
                    "🏠 Inicio",
                    callback_data="home",
                ),
            ],
        ]
    )


def teclado_resultado_respaldo(bot_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📂 Ver historial",
                    callback_data=f"bot_history:{bot_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Volver al bot",
                    callback_data=f"bot_detalle:{bot_id}",
                ),
                InlineKeyboardButton(
                    "🏠 Inicio",
                    callback_data="home",
                ),
            ],
        ]
    )


async def solicitar_respaldo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    bot_id: int,
) -> None:
    query = update.callback_query
    bot = obtener_bot(bot_id)

    if not bot:
        await query.answer("El bot no existe.", show_alert=True)
        return

    nombre = html.escape(str(bot["nombre"] or "Bot sin nombre"))
    ruta = html.escape(str(bot["ruta_proyecto"] or "No configurada"))
    base = html.escape(str(bot["ruta_base_datos"] or "No configurada"))

    await query.edit_message_text(
        "💾 <b>CONFIRMAR RESPALDO</b>\n\n"
        f"🤖 Bot: <b>{nombre}</b>\n\n"
        f"📂 Proyecto:\n<code>{ruta}</code>\n\n"
        f"🗃 Base de datos:\n<code>{base}</code>\n\n"
        "El sistema creará un archivo comprimido, calculará su "
        "firma SHA-256 y lo registrará en el historial.",
        parse_mode="HTML",
        reply_markup=teclado_confirmar_respaldo(bot_id),
    )


async def ejecutar_respaldo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    bot_id: int,
) -> None:
    query = update.callback_query
    bot = obtener_bot(bot_id)

    if not bot:
        await query.answer("El bot no existe.", show_alert=True)
        return

    nombre = html.escape(str(bot["nombre"] or "Bot sin nombre"))

    await query.edit_message_text(
        "⏳ <b>CREANDO RESPALDO</b>\n\n"
        f"🤖 {nombre}\n\n"
        "No cierres el panel. El proceso puede tardar unos segundos.",
        parse_mode="HTML",
    )

    resultado = await asyncio.to_thread(
        crear_respaldo_bot,
        bot_id,
        "MANUAL",
    )

    if not resultado.get("correcto"):
        mensaje = html.escape(
            str(resultado.get("mensaje") or "Error desconocido.")
        )
        await query.edit_message_text(
            "❌ <b>RESPALDO NO CREADO</b>\n\n"
            f"{mensaje}",
            parse_mode="HTML",
            reply_markup=teclado_resultado_respaldo(bot_id),
        )
        return

    archivo = html.escape(str(resultado.get("archivo") or "Sin nombre"))
    tamano = html.escape(
        formatear_tamano(resultado.get("tamano_bytes"))
    )
    cantidad = int(resultado.get("archivos_agregados") or 0)
    base_incluida = "Sí" if resultado.get("base_incluida") else "No"
    sha256 = html.escape(str(resultado.get("sha256") or ""))

    await query.edit_message_text(
        "✅ <b>RESPALDO CREADO CORRECTAMENTE</b>\n\n"
        f"🤖 Bot: <b>{nombre}</b>\n"
        f"📦 Archivo: <code>{archivo}</code>\n"
        f"📏 Tamaño: <b>{tamano}</b>\n"
        f"📄 Archivos incluidos: <b>{cantidad}</b>\n"
        f"🗃 Base de datos incluida: <b>{base_incluida}</b>\n\n"
        f"🔐 SHA-256:\n<code>{sha256}</code>",
        parse_mode="HTML",
        reply_markup=teclado_resultado_respaldo(bot_id),
    )


async def botones_generales(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    registrar_panel_desde_query(query, context)

    if not autorizado(query.from_user.id):
        await query.answer("No autorizado.", show_alert=True)
        return

    opcion = query.data

    if opcion == "home":
        limpiar_flujos(context)
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
            await query.answer("El bot ya no existe.", show_alert=True)
            return
        await query.edit_message_text(
            texto,
            parse_mode="HTML",
            reply_markup=teclado_detalle_bot(bot_id, bot["estado"]),
        )
        return

    if opcion.startswith("bot_estado:"):
        _, bot_id, estado = opcion.split(":")
        correcto, mensaje = cambiar_estado(int(bot_id), estado)
        await query.answer(mensaje, show_alert=not correcto)
        bot = obtener_bot(int(bot_id))
        texto = texto_detalle_bot(int(bot_id))
        if bot and texto:
            await query.edit_message_text(
                texto,
                parse_mode="HTML",
                reply_markup=teclado_detalle_bot(int(bot_id), bot["estado"]),
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
            "Esto elimina el registro administrativo, pero no borra el bot ni sus archivos.",
            parse_mode="HTML",
            reply_markup=teclado_confirmar_eliminacion(bot_id),
        )
        return

    if opcion.startswith("bot_backup_confirmar:"):
        bot_id = int(opcion.split(":")[1])
        await ejecutar_respaldo(update, context, bot_id)
        return

    if opcion.startswith("bot_backup:"):
        bot_id = int(opcion.split(":")[1])
        await solicitar_respaldo(update, context, bot_id)
        return

    if opcion.startswith("bot_restore:"):
        await query.answer(
            "La restauración se integrará en una mejora posterior.",
            show_alert=True,
        )
        return

    if opcion.startswith("respaldo_descargar:"):
        respaldo_id = int(opcion.split(":")[1])
        await descargar_respaldo(update, context, respaldo_id)
        return

    if opcion.startswith("respaldo_detalle:"):
        respaldo_id = int(opcion.split(":")[1])
        respaldo = obtener_respaldo(respaldo_id)

        if not respaldo:
            await query.answer("El respaldo no existe.", show_alert=True)
            return

        await query.edit_message_text(
            texto_detalle_respaldo(respaldo_id),
            parse_mode="HTML",
            reply_markup=teclado_detalle_respaldo(
                respaldo_id,
                int(respaldo["bot_id"]),
            ),
        )
        return

    if opcion.startswith("respaldo_restaurar:"):
        await query.answer(
            "La restauración se habilitará en el Bloque 3.2.",
            show_alert=True,
        )
        return

    if opcion.startswith("respaldo_eliminar:"):
        await query.answer(
            "La eliminación segura se habilitará en el Bloque 3.2.",
            show_alert=True,
        )
        return

    if opcion.startswith("bot_history:"):
        bot_id = int(opcion.split(":")[1])
        await query.edit_message_text(
            texto_historial_bot(bot_id),
            parse_mode="HTML",
            reply_markup=teclado_historial_bot(bot_id),
        )
        return

    textos = {
        "backup": "💾 <b>CREAR RESPALDO</b>\n\nSelecciona <b>Bots Registrados</b>, abre un bot y pulsa <b>💾 Respaldar</b>.",
        "restore": "📥 <b>RESTAURAR RESPALDO</b>\n\nLa restauración estará disponible cuando existan respaldos registrados.",
        "history": "📂 <b>HISTORIAL GENERAL</b>\n\nAbre <b>Bots Registrados</b>, selecciona un bot y pulsa <b>📂 Historial</b>.",
        "status": "❤️ <b>ESTADO DE BOTS</b>\n\nEl monitoreo automático se integrará en una próxima mejora.",
        "settings": "⚙️ <b>CONFIGURACIÓN</b>\n\nDesde <b>Bots Registrados</b> puedes agregar y editar los proyectos administrados.",
    }

    if opcion == "close":
        await query.edit_message_text(
            "✅ Panel cerrado.\n\nUsa /start para abrirlo nuevamente."
        )
        return

    await query.edit_message_text(
        textos.get(opcion, "Opción no reconocida."),
        parse_mode="HTML",
        reply_markup=teclado_regreso(),
    )


def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("Falta configurar BOT_TOKEN en el archivo .env")

    application = Application.builder().token(BOT_TOKEN).build()

    flujo = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(iniciar_registro, pattern=r"^bot_registrar$"),
            CallbackQueryHandler(abrir_editor_bot, pattern=r"^bot_editar:\d+$"),
            CallbackQueryHandler(
                seleccionar_campo_bot,
                pattern=r"^bot_editar_campo:\d+:[a-z_]+$",
            ),
        ],
        states={
            REGISTRO_NOMBRE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_nombre)
            ],
            REGISTRO_USERNAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_username),
                CallbackQueryHandler(
                    registro_omitir_username,
                    pattern=r"^bot_registro_omitir$",
                ),
            ],
            REGISTRO_DESCRIPCION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_descripcion),
                CallbackQueryHandler(
                    registro_omitir_descripcion,
                    pattern=r"^bot_registro_omitir$",
                ),
            ],
            REGISTRO_REPOSITORIO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_repositorio),
                CallbackQueryHandler(
                    registro_omitir_repositorio,
                    pattern=r"^bot_registro_omitir$",
                ),
            ],
            REGISTRO_SERVIDOR: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_servidor),
                CallbackQueryHandler(
                    registro_omitir_servidor,
                    pattern=r"^bot_registro_omitir$",
                ),
            ],
            REGISTRO_RUTA_PROYECTO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_ruta_proyecto),
                CallbackQueryHandler(
                    registro_omitir_ruta_proyecto,
                    pattern=r"^bot_registro_omitir$",
                ),
            ],
            REGISTRO_RUTA_DATABASE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_ruta_database),
                CallbackQueryHandler(
                    registro_omitir_ruta_database,
                    pattern=r"^bot_registro_omitir$",
                ),
            ],
            REGISTRO_CONFIRMACION: [
                CallbackQueryHandler(
                    guardar_registro,
                    pattern=r"^bot_registro_guardar$",
                ),
                CallbackQueryHandler(
                    abrir_editor_registro,
                    pattern=r"^bot_registro_editar$",
                ),
                CallbackQueryHandler(
                    seleccionar_campo_registro,
                    pattern=r"^bot_registro_editar_campo:[a-z_]+$",
                ),
                CallbackQueryHandler(
                    mostrar_confirmacion_registro,
                    pattern=r"^bot_registro_confirmacion$",
                ),
                CallbackQueryHandler(
                    abrir_editor_bot,
                    pattern=r"^bot_editar:\d+$",
                ),
                CallbackQueryHandler(
                    seleccionar_campo_bot,
                    pattern=r"^bot_editar_campo:\d+:[a-z_]+$",
                ),
            ],
            EDICION_VALOR: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    guardar_valor_editado,
                ),
                CallbackQueryHandler(
                    vaciar_valor_editado,
                    pattern=r"^bot_edicion_vaciar$",
                ),
                CallbackQueryHandler(
                    cancelar_edicion,
                    pattern=r"^bot_edicion_cancelar$",
                ),
                CallbackQueryHandler(
                    abrir_editor_registro,
                    pattern=r"^bot_registro_editar$",
                ),
                CallbackQueryHandler(
                    abrir_editor_bot,
                    pattern=r"^bot_editar:\d+$",
                ),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancelar_comando),
            CallbackQueryHandler(
                cancelar_registro_callback,
                pattern=r"^bot_registro_cancelar$",
            ),
            CallbackQueryHandler(
                cancelar_edicion,
                pattern=r"^bot_edicion_cancelar$",
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
    application.add_handler(flujo)
    application.add_handler(CallbackQueryHandler(botones_generales))

    print(f"BOT RESPALDOS PREMIUM {VERSION} iniciado.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
