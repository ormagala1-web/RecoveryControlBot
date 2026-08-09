import asyncio
import html
import logging
import os
import hashlib
import json
import shutil
import tarfile
import tempfile
import compileall
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
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
    actualizar_estado_respaldo,
    obtener_bot,
    obtener_bots,
    obtener_respaldo,
    obtener_respaldos_bot,
    obtener_ultimos_respaldos,
)
from respaldos import (
    crear_respaldo_bot,
    crear_respaldo_fuente_github,
    crear_respaldo_fuente_justrunmy,
    crear_respaldo_fuente_oracle,
    estado_fuente_oracle,
    resolver_agente_remoto_bot,
    formatear_tamano,
    importar_respaldo_externo,
)
from recovery_engine import restaurar_codigo_remoto
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
VERSION = "4.6 — ORQUESTADOR SECUENCIAL + MANUAL PERMANENTE"
ZONA_PERU = ZoneInfo("America/Lima")
MAX_EXTERNAL_UPLOAD_BYTES = int(os.getenv("MAX_EXTERNAL_UPLOAD_BYTES", str(50 * 1024 * 1024)))

PUBLICIDAD_AGENT_URL = os.getenv(
    "PUBLICIDAD_AGENT_URL",
    "https://publicidad-103.c.jrnm.app",
).rstrip("/")
PUBLICIDAD_AGENT_SECRET = os.getenv("PUBLICIDAD_AGENT_SECRET", "").strip()

PUBLICIDAD_DEPLOY_GIT_URL = os.getenv(
    "PUBLICIDAD_DEPLOY_GIT_URL",
    "",
).strip()
PUBLICIDAD_HEALTH_URL = os.getenv(
    "PUBLICIDAD_HEALTH_URL",
    f"{PUBLICIDAD_AGENT_URL}/health",
).strip()

MAXIMO_AGENT_URL = os.getenv(
    "MAXIMO_AGENT_URL",
    "https://maximocont-84c.d.jrnm.app",
).rstrip("/")
MAXIMO_AGENT_SECRET = os.getenv(
    "MAXIMO_AGENT_SECRET",
    "",
).strip()
MAXIMO_DEPLOY_GIT_URL = os.getenv(
    "MAXIMO_DEPLOY_GIT_URL",
    "",
).strip()
MAXIMO_HEALTH_URL = os.getenv(
    "MAXIMO_HEALTH_URL",
    f"{MAXIMO_AGENT_URL}/health",
).strip()

MEMBRESIAS_AGENT_URL = os.getenv(
    "MEMBRESIAS_AGENT_URL",
    "https://membresias-backup-4b9.d.jrnm.app",
).rstrip("/")
MEMBRESIAS_AGENT_SECRET = os.getenv(
    "MEMBRESIAS_AGENT_SECRET",
    "",
).strip()
MEMBRESIAS_DEPLOY_GIT_URL = os.getenv(
    "MEMBRESIAS_DEPLOY_GIT_URL",
    "",
).strip()
MEMBRESIAS_HEALTH_URL = os.getenv(
    "MEMBRESIAS_HEALTH_URL",
    f"{MEMBRESIAS_AGENT_URL}/health",
).strip()

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
        "restore_external_bot_id",
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
                InlineKeyboardButton("💾 Respaldo MANUAL", callback_data="backup"),
                InlineKeyboardButton("📥 Restauración MANUAL", callback_data="restore"),
            ],
            [InlineKeyboardButton("🧠 Centro de operaciones MASIVAS", callback_data="bulk_menu")],
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
        if fecha.tzinfo is None:
            fecha = fecha.replace(tzinfo=timezone.utc)
        return fecha.astimezone(ZONA_PERU).strftime("%d/%m/%Y %H:%M")
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




def sha256_archivo(ruta: Path) -> str:
    digest = hashlib.sha256()
    with ruta.open("rb") as archivo:
        for bloque in iter(lambda: archivo.read(1024 * 1024), b""):
            digest.update(bloque)
    return digest.hexdigest()


def _miembro_tar_seguro(nombre: str) -> bool:
    ruta = Path(nombre)
    return not ruta.is_absolute() and ".." not in ruta.parts


def inspeccionar_respaldo_para_restaurar(respaldo) -> dict:
    ruta = Path(str(respaldo["ruta"] or ""))
    if not ruta.is_file():
        raise RuntimeError("El archivo físico del respaldo no está disponible.")

    sha_esperado = str(respaldo["sha256"] or "").strip().lower()
    sha_real = sha256_archivo(ruta)
    if sha_esperado and sha_real != sha_esperado:
        raise RuntimeError("La firma SHA-256 no coincide. Restauración cancelada.")

    if not tarfile.is_tarfile(ruta):
        raise RuntimeError("Este respaldo no es un archivo TAR compatible.")

    with tarfile.open(ruta, "r:*") as paquete:
        miembros = paquete.getmembers()
        if not miembros:
            raise RuntimeError("El respaldo está vacío.")
        if any(not _miembro_tar_seguro(m.name) for m in miembros):
            raise RuntimeError("El respaldo contiene rutas inseguras.")

        nombres = {m.name for m in miembros if m.isfile()}
        codigo = sorted(n for n in nombres if n.startswith("codigo/"))
        if not codigo:
            raise RuntimeError("El respaldo no contiene la carpeta codigo/.")

        manifiesto = {}
        if "manifest.json" in nombres:
            archivo_manifest = paquete.extractfile("manifest.json")
            if archivo_manifest:
                manifiesto = json.loads(archivo_manifest.read().decode("utf-8"))

    return {
        "ruta": ruta,
        "sha256": sha_real,
        "manifiesto": manifiesto,
        "archivos_codigo": codigo,
    }


def teclado_restaurar_bots() -> InlineKeyboardMarkup:
    bots = obtener_bots()
    filas = []
    for bot in bots:
        filas.append([
            InlineKeyboardButton(
                f"🤖 {str(bot['nombre'] or 'Bot')}",
                callback_data=f"bot_restore:{bot['id']}",
            )
        ])
    filas.append([
        InlineKeyboardButton("🏠 Inicio", callback_data="home"),
        InlineKeyboardButton("❌ Cerrar", callback_data="close"),
    ])
    return InlineKeyboardMarkup(filas)


def texto_restaurar_bots() -> str:
    bots = obtener_bots()
    if not bots:
        return (
            "📥 <b>RESTAURAR RESPALDO</b>\n\n"
            "Todavía no existen bots registrados."
        )
    return (
        "📥 <b>RESTAURAR RESPALDO</b>\n\n"
        "Selecciona el bot. Podrás usar un respaldo del historial "
        "o adjuntar un archivo externo <code>.tar.gz</code>."
    )


def teclado_respaldos_restauracion(bot_id: int) -> InlineKeyboardMarkup:
    respaldos = obtener_respaldos_bot(bot_id, limite=40)
    filas = [
        [InlineKeyboardButton(
            "📎 Adjuntar respaldo externo .tar.gz",
            callback_data=f"restore_external:{bot_id}",
        )],
        [InlineKeyboardButton(
            "📤 Obtener copia actual por fuente",
            callback_data=f"restore_sources:{bot_id}",
        )],
    ]
    for respaldo in respaldos:
        tipo = str(respaldo["tipo"] or "").upper()
        if tipo.startswith("FUENTE_"):
            continue
        fecha = formatear_fecha_historial(respaldo["fecha_creacion"])
        etiqueta = "📎" if tipo == "EXTERNO" else "♻️"
        filas.append([
            InlineKeyboardButton(
                f"{etiqueta} #{respaldo['id']} · {fecha}",
                callback_data=f"respaldo_restaurar:{respaldo['id']}",
            )
        ])
    filas.append([
        InlineKeyboardButton("⬅️ Bots", callback_data="restore"),
        InlineKeyboardButton("🏠 Inicio", callback_data="home"),
    ])
    return InlineKeyboardMarkup(filas)


def teclado_fuentes_respaldo(bot_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🐙 GitHub · código", callback_data=f"source_panel:github:{bot_id}")],
        [InlineKeyboardButton("🚀 JustRunMy · base activa", callback_data=f"source_panel:justrunmy:{bot_id}")],
        [InlineKeyboardButton("☁️ Oracle · proyecto local", callback_data=f"source_panel:oracle:{bot_id}")],
        [InlineKeyboardButton("📚 Todas las copias guardadas", callback_data=f"source_library:{bot_id}")],
        [InlineKeyboardButton("🧠 Operaciones masivas", callback_data="bulk_menu")],
        [
            InlineKeyboardButton("⬅️ Restauración", callback_data=f"bot_restore:{bot_id}"),
            InlineKeyboardButton("🏠 Inicio", callback_data="home"),
        ],
    ])


def texto_fuentes_respaldo(bot) -> str:
    return (
        "📤 <b>COPIA ACTUAL POR FUENTE</b>\n\n"
        f"🤖 <b>{html.escape(str(bot['nombre'] or 'Bot'))}</b>\n\n"
        "Estas copias son independientes y se registran en el historial "
        "para auditoría, diagnóstico o mejoras.\n\n"
        "🐙 <b>GitHub</b>: código del repositorio.\n"
        "🚀 <b>JustRunMy</b>: base activa mediante agente remoto.\n"
        "☁️ <b>Oracle</b>: proyecto localizado en este servidor.\n\n"
        "Entrar a una fuente <b>no crea una copia automáticamente</b>. "
        "Dentro podrás crear una nueva, guardar la última creada, descargar "
        "la última guardada o revisar el historial ya almacenado.\n\n"
        "La auto-restauración principal continúa usando los paquetes completos "
        "del motor de respaldo."
    )


def codigo_tipo_fuente(fuente: str) -> str:
    return {
        "github": "FUENTE_GITHUB",
        "justrunmy": "FUENTE_JUSTRUNMY",
        "oracle": "FUENTE_ORACLE",
    }.get(str(fuente or "").lower(), "")


def nombre_fuente(fuente: str) -> str:
    return {
        "github": "🐙 GitHub · código",
        "justrunmy": "🚀 JustRunMy · base activa",
        "oracle": "☁️ Oracle · proyecto local",
    }.get(str(fuente or "").lower(), "📦 Fuente")


def copias_fuente(bot_id: int, fuente: str, limite: int = 30):
    tipo_objetivo = codigo_tipo_fuente(fuente)
    if not tipo_objetivo:
        return []
    resultado = []
    for respaldo in obtener_respaldos_bot(int(bot_id), limite=max(60, int(limite) * 4)):
        if str(respaldo["tipo"] or "").upper() == tipo_objetivo:
            resultado.append(respaldo)
            if len(resultado) >= int(limite):
                break
    return resultado


def ultima_copia_fuente(bot_id: int, fuente: str, estados=None):
    estados_validos = {str(e).upper() for e in (estados or [])}
    for respaldo in copias_fuente(bot_id, fuente, limite=40):
        estado = str(respaldo["estado"] or "").upper()
        if not estados_validos or estado in estados_validos:
            return respaldo
    return None


def estado_disponibilidad_fuente(bot, fuente: str) -> tuple[bool, str]:
    fuente = str(fuente or "").lower()
    if fuente == "github":
        repo = str(bot["repositorio"] or "").strip()
        return (bool(repo), "Repositorio configurado." if repo else "Repositorio no configurado.")

    if fuente == "justrunmy":
        cfg = resolver_agente_remoto_bot(bot)
        disponible = bool(cfg and cfg.get("agent_url") and cfg.get("agent_secret"))
        return (
            disponible,
            "Agente remoto configurado." if disponible else "Agente remoto no configurado para este bot.",
        )

    if fuente == "oracle":
        estado = estado_fuente_oracle(int(bot["id"]))
        ruta = str(estado.get("ruta") or "")
        mensaje = str(estado.get("mensaje") or "")
        if estado.get("disponible") and ruta:
            return True, f"Proyecto localizado: {ruta}"
        return False, mensaje or "Proyecto Oracle no disponible."

    return False, "Fuente desconocida."


def texto_panel_fuente(bot_id: int, fuente: str) -> str:
    bot = obtener_bot(int(bot_id))
    if not bot:
        return "❌ El bot ya no existe."

    disponible, detalle = estado_disponibilidad_fuente(bot, fuente)
    ultima_guardada = ultima_copia_fuente(bot_id, fuente, {"GUARDADO"})
    ultima_disponible = ultima_copia_fuente(bot_id, fuente, {"DISPONIBLE"})

    estado_txt = "✅ Disponible" if disponible else "⚠️ No disponible"
    lineas = [
        "📦 <b>CENTRO DE COPIAS POR FUENTE</b>",
        "",
        f"🤖 <b>{html.escape(str(bot['nombre'] or 'Bot'))}</b>",
        f"Fuente: <b>{nombre_fuente(fuente)}</b>",
        f"Estado: <b>{estado_txt}</b>",
        f"Detalle: {html.escape(detalle)}",
        "",
    ]

    if ultima_guardada:
        lineas.extend([
            "💾 <b>Última copia guardada</b>",
            f"• #{ultima_guardada['id']} · {formatear_fecha_historial(ultima_guardada['fecha_creacion'])}",
            f"• {formatear_tamano(ultima_guardada['tamano_bytes'])}",
            "",
        ])
    else:
        lineas.extend(["💾 <b>Última copia guardada:</b> ninguna", ""])

    if ultima_disponible:
        lineas.extend([
            "🆕 <b>Última copia creada sin guardar</b>",
            f"• #{ultima_disponible['id']} · {formatear_fecha_historial(ultima_disponible['fecha_creacion'])}",
            "",
        ])

    lineas.append(
        "Entrar o revisar esta pantalla no genera ningún respaldo nuevo. "
        "Solo <b>➕ Crear copia nueva</b> inicia una captura."
    )
    return "\n".join(lineas)


def teclado_panel_fuente(bot_id: int, fuente: str) -> InlineKeyboardMarkup:
    bot = obtener_bot(int(bot_id))
    disponible = False
    if bot:
        disponible, _ = estado_disponibilidad_fuente(bot, fuente)

    ultima_guardada = ultima_copia_fuente(bot_id, fuente, {"GUARDADO"})
    ultima_disponible = ultima_copia_fuente(bot_id, fuente, {"DISPONIBLE"})

    filas = []
    if disponible:
        filas.append([
            InlineKeyboardButton(
                "➕ Crear copia nueva",
                callback_data=f"backup_source:{fuente}:{bot_id}",
            )
        ])
    else:
        filas.append([
            InlineKeyboardButton(
                "⚠️ Crear copia · fuente no disponible",
                callback_data=f"source_unavailable:{fuente}:{bot_id}",
            )
        ])

    if ultima_disponible:
        filas.append([
            InlineKeyboardButton(
                "💾 Guardar última copia creada",
                callback_data=f"source_save:{ultima_disponible['id']}",
            )
        ])

    if ultima_guardada:
        filas.append([
            InlineKeyboardButton(
                "⬇️ Descargar última guardada",
                callback_data=f"respaldo_descargar:{ultima_guardada['id']}",
            )
        ])

    filas.append([
        InlineKeyboardButton(
            "📚 Ver copias guardadas",
            callback_data=f"source_library_source:{fuente}:{bot_id}",
        )
    ])
    filas.append([
        InlineKeyboardButton("⬅️ Fuentes", callback_data=f"restore_sources:{bot_id}"),
        InlineKeyboardButton("🏠 Inicio", callback_data="home"),
    ])
    return InlineKeyboardMarkup(filas)


def texto_biblioteca_fuente(bot_id: int, fuente: str) -> str:
    bot = obtener_bot(int(bot_id))
    if not bot:
        return "❌ El bot ya no existe."
    guardadas = [
        r for r in copias_fuente(bot_id, fuente, limite=30)
        if str(r["estado"] or "").upper() == "GUARDADO"
    ]
    return (
        "📚 <b>COPIAS GUARDADAS</b>\n\n"
        f"🤖 <b>{html.escape(str(bot['nombre'] or 'Bot'))}</b>\n"
        f"Fuente: <b>{nombre_fuente(fuente)}</b>\n\n"
        + (
            f"Total mostrado: <b>{len(guardadas)}</b>\\n\\n"
            "Selecciona una copia para verla o descargarla."
            if guardadas
            else "Todavía no hay copias guardadas para esta fuente."
        )
    )


def teclado_biblioteca_fuente(bot_id: int, fuente: str) -> InlineKeyboardMarkup:
    filas = []
    for respaldo in copias_fuente(bot_id, fuente, limite=30):
        if str(respaldo["estado"] or "").upper() != "GUARDADO":
            continue
        filas.append([
            InlineKeyboardButton(
                f"#{respaldo['id']} · {formatear_fecha_historial(respaldo['fecha_creacion'])}",
                callback_data=f"source_saved_detail:{respaldo['id']}",
            )
        ])
    filas.append([
        InlineKeyboardButton("⬅️ Fuente", callback_data=f"source_panel:{fuente}:{bot_id}"),
        InlineKeyboardButton("🏠 Inicio", callback_data="home"),
    ])
    return InlineKeyboardMarkup(filas)


def respaldos_fuente_guardados(bot_id: int, limite: int = 30):
    filas = []
    for respaldo in obtener_respaldos_bot(int(bot_id), limite=max(40, int(limite) * 3)):
        tipo = str(respaldo["tipo"] or "").upper()
        estado = str(respaldo["estado"] or "").upper()
        if tipo.startswith("FUENTE_") and estado == "GUARDADO":
            filas.append(respaldo)
            if len(filas) >= int(limite):
                break
    return filas


def etiqueta_fuente(tipo: str) -> str:
    tipo = str(tipo or "").upper()
    return {
        "FUENTE_GITHUB": "🐙 GitHub",
        "FUENTE_JUSTRUNMY": "🚀 JustRunMy",
        "FUENTE_ORACLE": "☁️ Oracle",
    }.get(tipo, "📦 Fuente")


def texto_biblioteca_fuentes(bot_id: int) -> str:
    bot = obtener_bot(int(bot_id))
    if not bot:
        return "❌ El bot ya no existe."
    copias = respaldos_fuente_guardados(bot_id)
    if not copias:
        return (
            "📚 <b>COPIAS GUARDADAS POR FUENTE</b>\n\n"
            f"🤖 <b>{html.escape(str(bot['nombre'] or 'Bot'))}</b>\n\n"
            "Todavía no guardaste ninguna copia de GitHub, JustRunMy u Oracle.\n\n"
            "Genera una copia y pulsa <b>💾 Guardar en Bot Respaldos Premium</b>."
        )
    return (
        "📚 <b>COPIAS GUARDADAS POR FUENTE</b>\n\n"
        f"🤖 <b>{html.escape(str(bot['nombre'] or 'Bot'))}</b>\n\n"
        "Estas copias quedan conservadas dentro del Bot Respaldos Premium "
        "para auditoría, diagnóstico, comparación o mejoras.\n\n"
        f"Total mostrado: <b>{len(copias)}</b>"
    )


def teclado_biblioteca_fuentes(bot_id: int) -> InlineKeyboardMarkup:
    filas = []
    for respaldo in respaldos_fuente_guardados(bot_id):
        fecha = formatear_fecha_historial(respaldo["fecha_creacion"])
        fuente = etiqueta_fuente(respaldo["tipo"])
        filas.append([
            InlineKeyboardButton(
                f"{fuente} · #{respaldo['id']} · {fecha}",
                callback_data=f"source_saved_detail:{respaldo['id']}",
            )
        ])
    filas.append([
        InlineKeyboardButton("⬅️ Fuentes", callback_data=f"restore_sources:{bot_id}"),
        InlineKeyboardButton("🏠 Inicio", callback_data="home"),
    ])
    return InlineKeyboardMarkup(filas)


def teclado_espera_archivo_externo(bot_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancelar", callback_data=f"restore_external_cancel:{bot_id}")],
        [InlineKeyboardButton("⬅️ Restauración", callback_data=f"bot_restore:{bot_id}")],
    ])


def es_publicidad_bot(bot) -> bool:
    nombre = str(bot["nombre"] or "").strip().lower()
    username = str(bot["username"] or "").strip().lower()
    return (
        username == "@publicidadcontrolstreaming_bot"
        or "publicidad control streaming" in nombre
    )


def es_maximo_o_union_bot(bot) -> bool:
    nombre = str(bot["nombre"] or "").strip().lower()
    username = str(bot["username"] or "").strip().lower()
    return (
        username in {
            "@maximocontrolgroup_bot",
            "@unionmembresia_bot",
        }
        or "máximo control group" in nombre
        or "maximo control group" in nombre
        or "membresía de usuario" in nombre
        or "membresia de usuario" in nombre
        or "unión membresía" in nombre
        or "union membresia" in nombre
    )


def obtener_configuracion_recuperacion(bot) -> Optional[dict]:
    if es_membresias_consultas_denuncias_bot(bot):
        return {
            "producto": "MembresiaConsultasDenunciasBot",
            "archivo_base": "membresias_consultas_denuncias.db",
            "agent_url": MEMBRESIAS_AGENT_URL,
            "agent_secret": MEMBRESIAS_AGENT_SECRET,
            "deploy_git_url": MEMBRESIAS_DEPLOY_GIT_URL,
            "health_url": MEMBRESIAS_HEALTH_URL,
        }

    if es_publicidad_bot(bot):
        return {
            "producto": "PublicidadBot",
            "archivo_base": "publicidad.db",
            "agent_url": PUBLICIDAD_AGENT_URL,
            "agent_secret": PUBLICIDAD_AGENT_SECRET,
            "deploy_git_url": PUBLICIDAD_DEPLOY_GIT_URL,
            "health_url": PUBLICIDAD_HEALTH_URL,
        }

    if es_maximo_o_union_bot(bot):
        return {
            "producto": "MaximoControlGroup",
            "archivo_base": "maximo_control.db",
            "agent_url": MAXIMO_AGENT_URL,
            "agent_secret": MAXIMO_AGENT_SECRET,
            "deploy_git_url": MAXIMO_DEPLOY_GIT_URL,
            "health_url": MAXIMO_HEALTH_URL,
        }

    return None


def teclado_confirmar_restauracion(
    respaldo_id: int,
    bot_id: int,
) -> InlineKeyboardMarkup:
    bot = obtener_bot(bot_id)
    configuracion = obtener_configuracion_recuperacion(bot) if bot else None
    filas = []

    if configuracion:
        filas.extend([
            [InlineKeyboardButton(
                "🗃 Restaurar solo base",
                callback_data=f"respaldo_restaurar_base_confirmar:{respaldo_id}",
            )],
            [InlineKeyboardButton(
                "🚀 Restaurar código + base",
                callback_data=f"respaldo_restaurar_completo_confirmar:{respaldo_id}",
            )],
        ])
    else:
        filas.append([InlineKeyboardButton(
            "⚠️ Confirmar restauración",
            callback_data=f"respaldo_restaurar_confirmar:{respaldo_id}",
        )])

    filas.append([
        InlineKeyboardButton(
            "⬅️ Cancelar",
            callback_data=f"bot_restore:{bot_id}",
        ),
        InlineKeyboardButton("🏠 Inicio", callback_data="home"),
    ])
    return InlineKeyboardMarkup(filas)


def _extraer_db_desde_tar(
    ruta_tar: Path,
    destino_db: Path,
    archivo_base: str,
) -> dict:
    with tarfile.open(ruta_tar, "r:*") as paquete:
        miembros = [m for m in paquete.getmembers() if m.isfile()]
        if any(not _miembro_tar_seguro(m.name) for m in miembros):
            raise RuntimeError("El respaldo contiene rutas inseguras.")

        elegido = None
        for miembro in miembros:
            normalizado = miembro.name.lstrip("./")
            if (
                normalizado == archivo_base
                or normalizado.endswith("/" + archivo_base)
            ):
                elegido = miembro
                break

        if elegido is None:
            raise RuntimeError(
                f"Este respaldo no incluye {archivo_base}. "
                "Los respaldos antiguos de código no pueden restaurar "
                "la base de datos remota."
            )

        origen = paquete.extractfile(elegido)
        if origen is None:
            raise RuntimeError(
                f"No se pudo extraer {archivo_base} del respaldo."
            )

        with destino_db.open("wb") as salida:
            shutil.copyfileobj(origen, salida, length=1024 * 1024)

        manifiesto = {}
        manifest_member = next(
            (m for m in miembros if m.name.lstrip("./") == "manifest.json"),
            None,
        )
        if manifest_member is not None:
            archivo_manifest = paquete.extractfile(manifest_member)
            if archivo_manifest:
                try:
                    manifiesto = json.loads(
                        archivo_manifest.read().decode("utf-8-sig")
                    )
                except (UnicodeDecodeError, json.JSONDecodeError):
                    manifiesto = {}

    return manifiesto


def validar_sqlite_local(ruta: Path) -> None:
    import sqlite3

    if not ruta.is_file() or ruta.stat().st_size <= 0:
        raise RuntimeError("La base de datos restaurable no existe o está vacía.")

    conexion = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)
    try:
        resultado = conexion.execute("PRAGMA integrity_check").fetchone()[0]
        if str(resultado).lower() != "ok":
            raise RuntimeError(f"Integridad SQLite: {resultado}")
    finally:
        conexion.close()


def preparar_zip_restore_remoto(
    respaldo,
    configuracion: dict,
) -> tuple[Path, bool]:
    ruta = Path(str(respaldo["ruta"] or ""))
    if not ruta.is_file():
        raise RuntimeError("El archivo físico del respaldo no está disponible.")

    if zipfile.is_zipfile(ruta):
        return ruta, False

    if not tarfile.is_tarfile(ruta):
        raise RuntimeError("El respaldo no es ZIP ni TAR compatible.")

    archivo_base = str(configuracion["archivo_base"])
    producto = str(configuracion["producto"])

    carpeta = Path(
        tempfile.mkdtemp(
            prefix=f"{producto.lower()}_remote_restore_"
        )
    )
    ruta_db = carpeta / archivo_base
    ruta_zip = carpeta / f"{producto}_restore_{respaldo['id']}.zip"

    try:
        manifiesto_original = _extraer_db_desde_tar(
            ruta,
            ruta_db,
            archivo_base,
        )
        validar_sqlite_local(ruta_db)

        manifiesto = {
            "producto": producto,
            "tipo": "BASE_DATOS_REMOTA",
            "fecha_utc": datetime.utcnow().isoformat() + "Z",
            "archivo_base": archivo_base,
            "tamano_bytes": ruta_db.stat().st_size,
            "sha256": sha256_archivo(ruta_db),
            "respaldo_origen_id": int(respaldo["id"]),
            "manifest_origen": manifiesto_original,
        }

        with zipfile.ZipFile(
            ruta_zip,
            "w",
            zipfile.ZIP_DEFLATED,
        ) as paquete:
            paquete.write(ruta_db, arcname=archivo_base)
            paquete.writestr(
                "manifest.json",
                json.dumps(
                    manifiesto,
                    ensure_ascii=False,
                    indent=2,
                ),
            )

        return ruta_zip, True
    except Exception:
        shutil.rmtree(carpeta, ignore_errors=True)
        raise


def restaurar_base_remota(
    respaldo_id: int,
    bot=None,
) -> dict:
    respaldo = obtener_respaldo(respaldo_id)
    if not respaldo:
        raise RuntimeError("El respaldo no existe.")

    if bot is None:
        bot = obtener_bot(int(respaldo["bot_id"]))
    if not bot:
        raise RuntimeError("El bot asociado ya no existe.")

    configuracion = obtener_configuracion_recuperacion(bot)
    if not configuracion:
        raise RuntimeError(
            "Este bot no tiene configurado un agente remoto de restauración."
        )

    agent_url = str(configuracion["agent_url"] or "").rstrip("/")
    agent_secret = str(configuracion["agent_secret"] or "").strip()

    if not agent_url:
        raise RuntimeError(
            f"Falta configurar la URL del agente para "
            f"{configuracion['producto']}."
        )
    if not agent_secret:
        raise RuntimeError(
            f"Falta configurar el secreto del agente para "
            f"{configuracion['producto']}."
        )

    ruta_zip, temporal = preparar_zip_restore_remoto(
        respaldo,
        configuracion,
    )

    try:
        sha_zip = sha256_archivo(ruta_zip)
        datos = ruta_zip.read_bytes()

        solicitud = urllib.request.Request(
            f"{agent_url}/restore",
            data=datos,
            method="POST",
            headers={
                "Authorization": f"Bearer {agent_secret}",
                "Content-Type": "application/zip",
                "Content-Length": str(len(datos)),
                "X-Archive-SHA256": sha_zip,
            },
        )

        try:
            with urllib.request.urlopen(
                solicitud,
                timeout=180,
            ) as respuesta:
                cuerpo = respuesta.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            detalle = error.read().decode(
                "utf-8",
                errors="replace",
            )
            raise RuntimeError(
                f"El agente remoto respondió HTTP "
                f"{error.code}: {detalle}"
            ) from error
        except urllib.error.URLError as error:
            raise RuntimeError(
                "No fue posible conectar con el agente remoto: "
                f"{error.reason}"
            ) from error

        try:
            resultado = json.loads(cuerpo)
        except json.JSONDecodeError as error:
            raise RuntimeError(
                "El agente remoto devolvió una respuesta inválida: "
                f"{cuerpo[:300]}"
            ) from error

        if not resultado.get("ok"):
            raise RuntimeError(
                str(
                    resultado.get("error")
                    or "La restauración remota falló."
                )
            )

        return {
            "correcto": True,
            "remoto": True,
            "destino": str(
                resultado.get("archivo_restaurado")
                or f"/app/data/{configuracion['archivo_base']}"
            ),
            "respaldo_previo": str(
                resultado.get("respaldo_preventivo")
                or "Creado por el agente remoto"
            ),
            "archivos": 1,
            "sha256": str(resultado.get("sha256_base") or ""),
            "detalle_remoto": resultado,
        }
    finally:
        if temporal:
            shutil.rmtree(ruta_zip.parent, ignore_errors=True)


def restaurar_respaldo_local(respaldo_id: int) -> dict:
    respaldo = obtener_respaldo(respaldo_id)
    if not respaldo:
        raise RuntimeError("El respaldo no existe.")

    bot = obtener_bot(int(respaldo["bot_id"]))
    if not bot:
        raise RuntimeError("El bot asociado ya no existe.")

    destino = Path(str(bot["ruta_proyecto"] or "").strip())
    if not destino.is_absolute():
        raise RuntimeError("La ruta del proyecto no es absoluta.")
    if not destino.is_dir():
        raise RuntimeError(
            "La ruta del proyecto no está disponible en este servidor. "
            "No se realizó ningún cambio."
        )

    info = inspeccionar_respaldo_para_restaurar(respaldo)
    raiz_seguridad = (
        Path(__file__).resolve().parent
        / "restauraciones_seguridad"
    )
    raiz_seguridad.mkdir(parents=True, exist_ok=True)
    sello = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    respaldo_previo = (
        raiz_seguridad
        / f"antes_restaurar_bot_{bot['id']}_{sello}.tar.gz"
    )

    with tarfile.open(respaldo_previo, "w:gz") as salida:
        salida.add(destino, arcname="proyecto_actual")

    carpeta_temp = Path(
        tempfile.mkdtemp(
            prefix="restore_",
            dir=str(raiz_seguridad),
        )
    )
    try:
        with tarfile.open(info["ruta"], "r:*") as paquete:
            miembros_codigo = [
                m for m in paquete.getmembers()
                if (
                    m.name.startswith("codigo/")
                    and _miembro_tar_seguro(m.name)
                )
            ]
            paquete.extractall(
                carpeta_temp,
                members=miembros_codigo,
            )

        codigo = carpeta_temp / "codigo"
        if not codigo.is_dir():
            raise RuntimeError(
                "No se pudo preparar el contenido del respaldo."
            )

        if not compileall.compile_dir(
            str(codigo),
            quiet=1,
            force=True,
        ):
            raise RuntimeError(
                "El código recuperado no superó la validación de Python."
            )

        for origen in codigo.rglob("*"):
            relativo = origen.relative_to(codigo)
            destino_final = destino / relativo

            if origen.is_dir():
                destino_final.mkdir(parents=True, exist_ok=True)
            elif origen.is_file():
                destino_final.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )
                temporal = destino_final.with_name(
                    destino_final.name + ".restore_tmp"
                )
                shutil.copy2(origen, temporal)
                os.replace(temporal, destino_final)

        return {
            "correcto": True,
            "respaldo_previo": str(respaldo_previo),
            "destino": str(destino),
            "archivos": len(info["archivos_codigo"]),
            "sha256": info["sha256"],
        }
    finally:
        shutil.rmtree(carpeta_temp, ignore_errors=True)


async def ejecutar_restauracion(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    respaldo_id: int,
) -> None:
    query = update.callback_query
    respaldo = obtener_respaldo(respaldo_id)
    if not respaldo:
        await query.answer("El respaldo no existe.", show_alert=True)
        return

    await query.edit_message_text(
        "⏳ <b>RESTAURANDO RESPALDO</b>\n\n"
        "Se está verificando SHA-256 y la base de datos.\n"
        "Antes de reemplazarla se creará una copia preventiva.",
        parse_mode="HTML",
    )

    bot = obtener_bot(int(respaldo["bot_id"]))
    try:
        configuracion = (
            obtener_configuracion_recuperacion(bot)
            if bot
            else None
        )
        if configuracion:
            resultado = await asyncio.to_thread(
                restaurar_base_remota,
                respaldo_id,
                bot,
            )
        else:
            resultado = await asyncio.to_thread(
                restaurar_respaldo_local,
                respaldo_id,
            )
    except Exception as error:
        await query.edit_message_text(
            "❌ <b>RESTAURACIÓN NO REALIZADA</b>\n\n"
            f"{html.escape(str(error))}",
            parse_mode="HTML",
            reply_markup=teclado_detalle_respaldo(
                respaldo_id,
                int(respaldo["bot_id"]),
            ),
        )
        return

    await query.edit_message_text(
        "✅ <b>RESTAURACIÓN COMPLETADA</b>\n\n"
        f"🤖 Bot: <b>{html.escape(str(respaldo['bot_nombre']))}</b>\n"
        f"📄 Archivos restaurados: <b>{resultado['archivos']}</b>\n"
        f"📂 Destino: <code>{html.escape(resultado['destino'])}</code>\n\n"
        "🛡 Copia previa creada en:\n"
        f"<code>{html.escape(resultado['respaldo_previo'])}</code>\n\n"
        + (
            "La base de datos fue restaurada directamente en JustRunMy."
            if resultado.get("remoto")
            else
            "La restauración local de archivos terminó."
        ),
        parse_mode="HTML",
        reply_markup=teclado_detalle_respaldo(
            respaldo_id,
            int(respaldo["bot_id"]),
        ),
    )


async def ejecutar_restauracion_completa(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    respaldo_id: int,
) -> None:
    query = update.callback_query
    respaldo = obtener_respaldo(respaldo_id)
    if not respaldo:
        await query.answer("El respaldo no existe.", show_alert=True)
        return

    bot = obtener_bot(int(respaldo["bot_id"]))
    configuracion = (
        obtener_configuracion_recuperacion(bot)
        if bot
        else None
    )

    if not bot or not configuracion:
        await query.answer(
            "Este bot no tiene configurada la recuperación completa.",
            show_alert=True,
        )
        return

    deploy_git_url = str(
        configuracion["deploy_git_url"] or ""
    ).strip()
    health_url = str(
        configuracion["health_url"] or ""
    ).strip()

    if not deploy_git_url:
        await query.edit_message_text(
            "❌ <b>CONFIGURACIÓN INCOMPLETA</b>\n\n"
            f"Falta configurar la URL Git de despliegue para "
            f"<b>{html.escape(str(bot['nombre']))}</b>.",
            parse_mode="HTML",
            reply_markup=teclado_detalle_respaldo(
                respaldo_id,
                int(respaldo["bot_id"]),
            ),
        )
        return

    if not health_url:
        await query.edit_message_text(
            "❌ <b>CONFIGURACIÓN INCOMPLETA</b>\n\n"
            "Falta configurar la URL de verificación /health.",
            parse_mode="HTML",
            reply_markup=teclado_detalle_respaldo(
                respaldo_id,
                int(respaldo["bot_id"]),
            ),
        )
        return

    archivo_base = str(configuracion["archivo_base"])

    await query.edit_message_text(
        "⏳ <b>RECUPERACIÓN COMPLETA EN CURSO</b>\n\n"
        "1️⃣ Validando respaldo y código\n"
        "2️⃣ Creando respaldo preventivo\n"
        "3️⃣ Preparando rollback automático\n"
        "4️⃣ Desplegando en JustRunMy\n"
        "5️⃣ Verificando /health\n"
        f"6️⃣ Restaurando {html.escape(archivo_base)}\n\n"
        "No cierres este proceso.",
        parse_mode="HTML",
    )

    try:
        preventivo = await asyncio.to_thread(
            crear_respaldo_bot,
            int(respaldo["bot_id"]),
            "PRE_RESTORE",
        )
        if not preventivo.get("correcto"):
            raise RuntimeError(
                "No se pudo crear el respaldo preventivo: "
                + str(
                    preventivo.get("mensaje")
                    or "error desconocido"
                )
            )

        resultado_codigo = await asyncio.to_thread(
            restaurar_codigo_remoto,
            ruta_respaldo=str(respaldo["ruta"]),
            sha256_esperado=str(respaldo["sha256"] or ""),
            respaldo_id=respaldo_id,
            bot_nombre=str(respaldo["bot_nombre"] or "Bot"),
            repositorio_actual=str(bot["repositorio"] or ""),
            deploy_git_url=deploy_git_url,
            health_url=health_url,
        )

        resultado_base = await asyncio.to_thread(
            restaurar_base_remota,
            respaldo_id,
            bot,
        )
    except Exception as error:
        await query.edit_message_text(
            "❌ <b>RECUPERACIÓN COMPLETA NO REALIZADA</b>\n\n"
            f"{html.escape(str(error))}",
            parse_mode="HTML",
            reply_markup=teclado_detalle_respaldo(
                respaldo_id,
                int(respaldo["bot_id"]),
            ),
        )
        return

    health = resultado_codigo.get("health") or {}
    await query.edit_message_text(
        "✅ <b>RECUPERACIÓN COMPLETA FINALIZADA</b>\n\n"
        f"🤖 Bot: <b>{html.escape(str(respaldo['bot_nombre']))}</b>\n"
        f"📦 Código desplegado: "
        f"<b>{resultado_codigo['archivos_codigo']} archivos</b>\n"
        f"❤️ Health: "
        f"<b>{html.escape(str(health.get('servicio') or 'OK'))}</b>\n"
        f"🗃 Base restaurada: "
        f"<code>{html.escape(resultado_base['destino'])}</code>\n"
        f"🛡 Respaldo preventivo registrado: "
        f"<b>#{preventivo.get('respaldo_id')}</b>\n\n"
        "El código fue desplegado, el servicio superó /health "
        "y la base de datos fue restaurada.",
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


async def recibir_respaldo_externo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    mensaje = update.effective_message
    usuario = update.effective_user
    bot_id = context.user_data.get("restore_external_bot_id")
    if not mensaje or not usuario or not bot_id:
        return
    if not autorizado(usuario.id):
        return

    documento = mensaje.document
    if not documento:
        return

    bot = obtener_bot(int(bot_id))
    if not bot:
        context.user_data.pop("restore_external_bot_id", None)
        await borrar_mensaje_seguro(mensaje)
        return

    nombre_original = str(documento.file_name or "").strip()
    if not nombre_original.lower().endswith((".tar.gz", ".tgz")):
        await actualizar_panel(
            update, context,
            "❌ <b>ARCHIVO NO COMPATIBLE</b>\n\n"
            "Adjunta un respaldo <code>.tar.gz</code> generado por Bot Respaldos Premium.",
            parse_mode="HTML",
            reply_markup=teclado_espera_archivo_externo(int(bot_id)),
        )
        return

    if documento.file_size and int(documento.file_size) > MAX_EXTERNAL_UPLOAD_BYTES:
        await actualizar_panel(
            update, context,
            "❌ <b>ARCHIVO DEMASIADO GRANDE</b>\n\n"
            f"Máximo admitido: <b>{formatear_tamano(MAX_EXTERNAL_UPLOAD_BYTES)}</b>.",
            parse_mode="HTML",
            reply_markup=teclado_espera_archivo_externo(int(bot_id)),
        )
        return

    carpeta_temp = Path(__file__).resolve().parent / "cache_importaciones"
    carpeta_temp.mkdir(parents=True, exist_ok=True)
    temporal = carpeta_temp / f"externo_{usuario.id}_{int(bot_id)}_{datetime.now(ZONA_PERU).strftime('%Y%m%d_%H%M%S')}.tar.gz"

    try:
        archivo_telegram = await context.bot.get_file(documento.file_id)
        await archivo_telegram.download_to_drive(custom_path=str(temporal))
        resultado = await asyncio.to_thread(
            importar_respaldo_externo,
            int(bot_id),
            str(temporal),
            nombre_original,
        )
    except Exception as error:
        resultado = {"correcto": False, "mensaje": str(error)}
    finally:
        temporal.unlink(missing_ok=True)

    context.user_data.pop("restore_external_bot_id", None)

    if not resultado.get("correcto"):
        await actualizar_panel(
            update, context,
            "❌ <b>RESPALDO EXTERNO RECHAZADO</b>\n\n"
            + html.escape(str(resultado.get("mensaje") or "No superó la validación.")),
            parse_mode="HTML",
            reply_markup=teclado_respaldos_restauracion(int(bot_id)),
        )
        return

    respaldo_id = int(resultado["respaldo_id"])
    await actualizar_panel(
        update, context,
        "✅ <b>RESPALDO EXTERNO VALIDADO</b>\n\n"
        f"🤖 Bot: <b>{html.escape(str(bot['nombre']))}</b>\n"
        f"📦 Archivo registrado: <code>{html.escape(str(resultado['archivo']))}</code>\n"
        f"📏 Tamaño: <b>{formatear_tamano(resultado['tamano_bytes'])}</b>\n"
        f"📄 Código: <b>{int(resultado['archivos_codigo'])} archivos</b>\n"
        f"🔐 SHA-256:\n<code>{html.escape(str(resultado['sha256']))}</code>\n"
        f"🇵🇪 Validado: <b>{datetime.now(ZONA_PERU).strftime('%d/%m/%Y %H:%M')}</b>\n\n"
        "El archivo ya forma parte del historial y puede entrar al flujo normal de restauración.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("♻️ Validar y restaurar", callback_data=f"respaldo_restaurar:{respaldo_id}")
        ], [
            InlineKeyboardButton("⬅️ Restauración", callback_data=f"bot_restore:{bot_id}"),
            InlineKeyboardButton("🏠 Inicio", callback_data="home"),
        ]]),
    )



OPERACIONES_MASIVAS_ACTIVAS = set()

# Estado efímero de la última operación masiva.
# NO reemplaza los flujos manuales: solo permite reintentar fallidos.
ULTIMOS_FALLIDOS_MASIVOS = {}


def _ultimo_respaldo_valido_bot(bot_id: int):
    """
    Devuelve el respaldo recuperable más reciente.
    Ignora copias FUENTE_* porque son de auditoría, no de auto-restauración.
    Si el más nuevo está dañado, intenta los anteriores.
    """
    for respaldo in obtener_respaldos_bot(int(bot_id), limite=60):
        tipo = str(respaldo["tipo"] or "").upper()
        if tipo.startswith("FUENTE_"):
            continue
        try:
            inspeccionar_respaldo_para_restaurar(respaldo)
            return respaldo
        except Exception:
            continue
    return None


def _plan_restauracion_masiva():
    filas = []
    for bot in obtener_bots():
        respaldo = _ultimo_respaldo_valido_bot(int(bot["id"]))
        if respaldo:
            filas.append({
                "bot_id": int(bot["id"]),
                "bot_nombre": str(bot["nombre"] or "Bot"),
                "respaldo_id": int(respaldo["id"]),
                "archivo": str(respaldo["archivo"] or ""),
                "fecha": str(respaldo["fecha_creacion"] or ""),
                "valido": True,
            })
        else:
            filas.append({
                "bot_id": int(bot["id"]),
                "bot_nombre": str(bot["nombre"] or "Bot"),
                "respaldo_id": None,
                "archivo": "",
                "fecha": "",
                "valido": False,
            })
    return filas


def texto_plan_restauracion_masiva() -> str:
    plan = _plan_restauracion_masiva()
    lineas = [
        "♻️ <b>PLAN DE RESTAURACIÓN MASIVA</b>",
        "",
        "La opción MANUAL permanece disponible en todo momento.",
        "Este plan usa el <b>respaldo recuperable más reciente</b> de cada bot.",
        "",
    ]
    todos_validos = True
    for indice, item in enumerate(plan, start=1):
        nombre = html.escape(item["bot_nombre"])
        if item["valido"]:
            lineas.append(
                f"✅ {indice}. {nombre} · respaldo <b>#{item['respaldo_id']}</b>"
            )
        else:
            todos_validos = False
            lineas.append(f"❌ {indice}. {nombre} · sin respaldo válido")
    lineas.extend([
        "",
        "🔐 Política:",
        "• se procesa un bot a la vez;",
        "• se crea respaldo preventivo antes de restaurar;",
        "• si una restauración falla, la cola se DETIENE;",
        "• los bots todavía no procesados quedan intactos;",
        "• siempre puedes restaurar cualquier bot manualmente.",
    ])
    if not todos_validos:
        lineas.extend([
            "",
            "⚠️ El lote no podrá iniciarse hasta que todos tengan al menos "
            "un respaldo válido. Puedes resolver cada caso manualmente.",
        ])
    return "\\n".join(lineas)


def teclado_plan_restauracion_masiva() -> InlineKeyboardMarkup:
    plan = _plan_restauracion_masiva()
    listo = bool(plan) and all(item["valido"] for item in plan)
    filas = []
    if listo:
        filas.append([
            InlineKeyboardButton(
                "⚠️ Preparar restauración de TODOS",
                callback_data="bulk_restore_prepare",
            )
        ])
    filas.extend([
        [InlineKeyboardButton("📥 Restauración MANUAL", callback_data="restore")],
        [InlineKeyboardButton("⬅️ Operaciones masivas", callback_data="bulk_menu")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="home")],
    ])
    return InlineKeyboardMarkup(filas)


def teclado_confirmar_restauracion_masiva() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🚨 CONFIRMAR RESTAURACIÓN SECUENCIAL",
            callback_data="bulk_restore_confirm",
        )],
        [InlineKeyboardButton("❌ Cancelar", callback_data="bulk_restore_plan")],
        [InlineKeyboardButton("📥 Ir a restauración MANUAL", callback_data="restore")],
    ])


def _resultado_lote_linea(indice, total, nombre, correcto, detalle):
    icono = "✅" if correcto else "❌"
    return (
        f"{icono} {indice}/{total} · {html.escape(str(nombre))} · "
        f"{html.escape(str(detalle))}"
    )




def texto_menu_masivo() -> str:
    return (
        "🧠 <b>CENTRO DE OPERACIONES MASIVAS</b>\n\n"
        "La operación MANUAL <b>nunca desaparece</b>. Este centro es adicional.\n\n"
        "🔁 Cola secuencial: un bot termina y recién comienza el siguiente.\n"
        "📦 Respaldos y copias: si uno falla, se registra el error y la cola CONTINÚA.\n"
        "♻️ Restauraciones: ante un fallo serio, la cola se DETIENE y no toca los siguientes.\n"
        "🗃 Los respaldos completos incluyen la base cuando el bot tiene agente/configuración disponible.\n\n"
        "Selecciona una operación."
    )


def teclado_menu_masivo() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 Respaldo COMPLETO de todos", callback_data="bulk_run:completo")],
        [InlineKeyboardButton("🐙 GitHub · todos", callback_data="bulk_run:github")],
        [InlineKeyboardButton("🚀 JustRunMy · todos", callback_data="bulk_run:justrunmy")],
        [InlineKeyboardButton("☁️ Oracle · todos", callback_data="bulk_run:oracle")],
        [InlineKeyboardButton("✅ Validar últimos respaldos", callback_data="bulk_validate")],
        [InlineKeyboardButton("♻️ Plan de restauración masiva", callback_data="bulk_restore_plan")],
        [
            InlineKeyboardButton("💾 Respaldo MANUAL", callback_data="bots"),
            InlineKeyboardButton("📥 Restauración MANUAL", callback_data="restore"),
        ],
        [InlineKeyboardButton("🏠 Inicio", callback_data="home")],
    ])


async def editar_progreso_masivo(query, titulo: str, lineas: list[str]) -> None:
    texto = titulo + "\n\n" + "\n".join(lineas[-25:])
    try:
        await query.edit_message_text(
            texto,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 Inicio", callback_data="home")]
            ]),
        )
    except TelegramError:
        pass


def _nombre_bot_corto(bot) -> str:
    return html.escape(str(bot["nombre"] or bot["username"] or f"Bot #{bot['id']}"))


async def ejecutar_lote_fuente(query, fuente: str, solo_bot_ids=None) -> None:
    clave = f"fuente:{fuente}"
    if clave in OPERACIONES_MASIVAS_ACTIVAS:
        await query.answer("Ya hay una operación masiva de esta fuente en curso.", show_alert=True)
        return

    OPERACIONES_MASIVAS_ACTIVAS.add(clave)
    fallidos = []
    try:
        bots = obtener_bots()
        if solo_bot_ids:
            permitidos = {int(x) for x in solo_bot_ids}
            bots = [b for b in bots if int(b["id"]) in permitidos]

        total = len(bots)
        lineas = []
        await editar_progreso_masivo(
            query,
            f"🧠 <b>LOTE {nombre_fuente(fuente)}</b>",
            [f"Preparando <b>{total}</b> bots..."],
        )

        for indice, bot in enumerate(bots, start=1):
            disponible, detalle = estado_disponibilidad_fuente(bot, fuente)
            nombre = _nombre_bot_corto(bot)

            if not disponible:
                fallidos.append(int(bot["id"]))
                lineas.append(
                    f"⚠️ {indice}/{total} · {nombre} · OMITIDO · {html.escape(detalle)}"
                )
                await editar_progreso_masivo(
                    query,
                    f"🧠 <b>LOTE {nombre_fuente(fuente)}</b>",
                    lineas,
                )
                await asyncio.sleep(2)
                continue

            try:
                resultado = await asyncio.to_thread(
                    crear_respaldo_fuente,
                    int(bot["id"]),
                    fuente,
                )
            except Exception as exc:
                resultado = {"correcto": False, "mensaje": str(exc)}

            if resultado.get("correcto"):
                rid = resultado.get("respaldo_id")
                lineas.append(f"✅ {indice}/{total} · {nombre} · copia #{rid or '?'}")
            else:
                fallidos.append(int(bot["id"]))
                lineas.append(
                    f"❌ {indice}/{total} · {nombre} · "
                    f"{html.escape(str(resultado.get('mensaje') or 'Error desconocido'))}"
                )

            await editar_progreso_masivo(
                query,
                f"🧠 <b>LOTE {nombre_fuente(fuente)}</b>",
                lineas,
            )
            await asyncio.sleep(3)

        ULTIMOS_FALLIDOS_MASIVOS[clave] = list(fallidos)

        filas = []
        if fallidos:
            filas.append([
                InlineKeyboardButton(
                    f"🔁 Reintentar fallidos ({len(fallidos)})",
                    callback_data=f"bulk_retry:{fuente}",
                )
            ])
        filas.extend([
            [InlineKeyboardButton("🤖 Operación MANUAL por bot", callback_data="bots")],
            [InlineKeyboardButton("⬅️ Operaciones masivas", callback_data="bulk_menu")],
            [InlineKeyboardButton("🏠 Inicio", callback_data="home")],
        ])

        await query.edit_message_text(
            f"✅ <b>LOTE FINALIZADO · {nombre_fuente(fuente)}</b>\\n\\n"
            + "\\n".join(lineas)
            + f"\\n\\n🇵🇪 Fin: {datetime.now(ZONA_PERU).strftime('%d/%m/%Y %H:%M:%S')}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(filas),
        )
    finally:
        OPERACIONES_MASIVAS_ACTIVAS.discard(clave)


async def ejecutar_lote_completo(query, solo_bot_ids=None) -> None:
    clave = "completo"
    if clave in OPERACIONES_MASIVAS_ACTIVAS:
        await query.answer("Ya hay un respaldo completo masivo en curso.", show_alert=True)
        return

    OPERACIONES_MASIVAS_ACTIVAS.add(clave)
    fallidos = []
    try:
        bots = obtener_bots()
        if solo_bot_ids:
            permitidos = {int(x) for x in solo_bot_ids}
            bots = [b for b in bots if int(b["id"]) in permitidos]

        total = len(bots)
        lineas = []
        for indice, bot in enumerate(bots, start=1):
            nombre = _nombre_bot_corto(bot)
            try:
                resultado = await asyncio.to_thread(
                    crear_respaldo_bot,
                    int(bot["id"]),
                    "MASIVO",
                )
            except Exception as exc:
                resultado = {"correcto": False, "mensaje": str(exc)}

            if resultado.get("correcto"):
                base = "🗃 DB incluida" if resultado.get("base_incluida") else "📄 solo código"
                lineas.append(
                    f"✅ {indice}/{total} · {nombre} · respaldo #{resultado.get('respaldo_id') or '?'} · {base}"
                )
            else:
                fallidos.append(int(bot["id"]))
                lineas.append(
                    f"❌ {indice}/{total} · {nombre} · "
                    f"{html.escape(str(resultado.get('mensaje') or 'Error desconocido'))}"
                )

            await editar_progreso_masivo(
                query,
                "📦 <b>RESPALDO COMPLETO MASIVO</b>",
                lineas,
            )
            await asyncio.sleep(3)

        ULTIMOS_FALLIDOS_MASIVOS[clave] = list(fallidos)

        filas = []
        if fallidos:
            filas.append([
                InlineKeyboardButton(
                    f"🔁 Reintentar fallidos ({len(fallidos)})",
                    callback_data="bulk_retry:completo",
                )
            ])
        filas.extend([
            [InlineKeyboardButton("💾 Respaldo MANUAL", callback_data="bots")],
            [InlineKeyboardButton("⬅️ Operaciones masivas", callback_data="bulk_menu")],
            [InlineKeyboardButton("🏠 Inicio", callback_data="home")],
        ])

        await query.edit_message_text(
            "✅ <b>RESPALDO COMPLETO MASIVO FINALIZADO</b>\\n\\n"
            + "\\n".join(lineas)
            + f"\\n\\n🇵🇪 Fin: {datetime.now(ZONA_PERU).strftime('%d/%m/%Y %H:%M:%S')}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(filas),
        )
    finally:
        OPERACIONES_MASIVAS_ACTIVAS.discard(clave)


async def ejecutar_validacion_masiva(query) -> None:
    bots = obtener_bots()
    total = len(bots)
    lineas = []

    for indice, bot in enumerate(bots, start=1):
        respaldo = _ultimo_respaldo_valido_bot(int(bot["id"]))
        if respaldo:
            lineas.append(
                f"✅ {indice}/{total} · {_nombre_bot_corto(bot)} · "
                f"respaldo #{respaldo['id']} válido"
            )
        else:
            lineas.append(
                f"❌ {indice}/{total} · {_nombre_bot_corto(bot)} · "
                "sin respaldo recuperable"
            )

    await query.edit_message_text(
        "✅ <b>VALIDACIÓN MASIVA</b>\\n\\n"
        + "\\n".join(lineas)
        + f"\\n\\n🇵🇪 {datetime.now(ZONA_PERU).strftime('%d/%m/%Y %H:%M:%S')}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("♻️ Ver plan de restauración", callback_data="bulk_restore_plan")],
            [InlineKeyboardButton("📥 Restauración MANUAL", callback_data="restore")],
            [InlineKeyboardButton("⬅️ Operaciones masivas", callback_data="bulk_menu")],
        ]),
    )


def _restaurar_respaldo_programatico(respaldo_id: int) -> dict:
    respaldo = obtener_respaldo(int(respaldo_id))
    if not respaldo:
        raise RuntimeError("El respaldo no existe.")

    bot = obtener_bot(int(respaldo["bot_id"]))
    if not bot:
        raise RuntimeError("El bot asociado no existe.")

    # La inspección SHA/TAR/código ocurre ANTES de crear cualquier cambio.
    info = inspeccionar_respaldo_para_restaurar(respaldo)
    configuracion = obtener_configuracion_recuperacion(bot)

    # Si el bot tiene recuperación remota y además despliegue+health,
    # aplicamos la misma filosofía de código + base de la restauración manual completa.
    if configuracion:
        deploy_git_url = str(configuracion.get("deploy_git_url") or "").strip()
        health_url = str(configuracion.get("health_url") or "").strip()
        agent_secret = str(configuracion.get("agent_secret") or "").strip()

        if not deploy_git_url or not health_url or not agent_secret:
            raise RuntimeError(
                "Configuración de recuperación remota incompleta. "
                "Usa la opción MANUAL para resolver este bot sin afectar a los demás."
            )

        preventivo = crear_respaldo_bot(
            int(respaldo["bot_id"]),
            "PRE_RESTORE_MASIVO",
        )
        if not preventivo.get("correcto"):
            raise RuntimeError(
                "No se pudo crear el respaldo preventivo: "
                + str(preventivo.get("mensaje") or "error desconocido")
            )

        resultado_codigo = restaurar_codigo_remoto(
            ruta_respaldo=str(respaldo["ruta"]),
            sha256_esperado=str(respaldo["sha256"] or ""),
            respaldo_id=int(respaldo_id),
            bot_nombre=str(respaldo["bot_nombre"] or "Bot"),
            repositorio_actual=str(bot["repositorio"] or ""),
            deploy_git_url=deploy_git_url,
            health_url=health_url,
        )

        resultado_base = restaurar_base_remota(
            int(respaldo_id),
            bot,
        )

        return {
            "correcto": True,
            "modo": "REMOTO_CODIGO_BASE",
            "preventivo": preventivo.get("respaldo_id"),
            "codigo": resultado_codigo,
            "base": resultado_base,
        }

    # Proyectos realmente locales en Oracle conservan la restauración local manual existente.
    resultado_local = restaurar_respaldo_local(int(respaldo_id))
    return {
        "correcto": True,
        "modo": "LOCAL",
        "resultado": resultado_local,
    }


async def ejecutar_restauracion_masiva(query) -> None:
    clave = "restore"
    if clave in OPERACIONES_MASIVAS_ACTIVAS:
        await query.answer("Ya existe una restauración masiva en curso.", show_alert=True)
        return

    plan = _plan_restauracion_masiva()
    if not plan or not all(item["valido"] for item in plan):
        await query.answer(
            "No todos los bots tienen un respaldo válido. Usa el plan o la opción manual.",
            show_alert=True,
        )
        return

    OPERACIONES_MASIVAS_ACTIVAS.add(clave)
    lineas = []
    try:
        total = len(plan)
        for indice, item in enumerate(plan, start=1):
            nombre = item["bot_nombre"]
            rid = int(item["respaldo_id"])

            await query.edit_message_text(
                "♻️ <b>RESTAURACIÓN MASIVA EN CURSO</b>\\n\\n"
                + "\\n".join(lineas)
                + (
                    "\\n" if lineas else ""
                )
                + f"⏳ {indice}/{total} · {html.escape(nombre)} · respaldo #{rid}\\n\\n"
                + "La cola es estricta: si este paso falla, no se toca el siguiente bot.",
                parse_mode="HTML",
            )

            try:
                resultado = await asyncio.to_thread(
                    _restaurar_respaldo_programatico,
                    rid,
                )
            except Exception as exc:
                lineas.append(
                    f"❌ {indice}/{total} · {html.escape(nombre)} · {html.escape(str(exc))}"
                )
                await query.edit_message_text(
                    "🛑 <b>RESTAURACIÓN MASIVA DETENIDA</b>\\n\\n"
                    + "\\n".join(lineas)
                    + "\\n\\nLos bots posteriores NO fueron modificados. "
                    "La restauración MANUAL sigue disponible.",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📥 Restauración MANUAL", callback_data="restore")],
                        [InlineKeyboardButton("♻️ Revisar plan", callback_data="bulk_restore_plan")],
                        [InlineKeyboardButton("🏠 Inicio", callback_data="home")],
                    ]),
                )
                return

            lineas.append(
                f"✅ {indice}/{total} · {html.escape(nombre)} · restaurado"
            )
            await asyncio.sleep(4)

        await query.edit_message_text(
            "✅ <b>RESTAURACIÓN MASIVA FINALIZADA</b>\\n\\n"
            + "\\n".join(lineas)
            + f"\\n\\n🇵🇪 Fin: {datetime.now(ZONA_PERU).strftime('%d/%m/%Y %H:%M:%S')}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📥 Restauración MANUAL", callback_data="restore")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="home")],
            ]),
        )
    finally:
        OPERACIONES_MASIVAS_ACTIVAS.discard(clave)


async def ejecutar_respaldo_fuente(update: Update, context: ContextTypes.DEFAULT_TYPE, fuente: str, bot_id: int) -> None:
    query = update.callback_query
    bot = obtener_bot(int(bot_id))
    if not bot:
        await query.answer("El bot no existe.", show_alert=True)
        return

    mapa = {
        "github": ("🐙 GitHub", crear_respaldo_fuente_github),
        "justrunmy": ("🚀 JustRunMy", crear_respaldo_fuente_justrunmy),
        "oracle": ("☁️ Oracle", crear_respaldo_fuente_oracle),
    }
    if fuente not in mapa:
        await query.answer("Fuente no válida.", show_alert=True)
        return

    etiqueta, funcion = mapa[fuente]
    await query.edit_message_text(
        "⏳ <b>OBTENIENDO COPIA POR FUENTE</b>\n\n"
        f"{etiqueta}\n"
        f"🤖 <b>{html.escape(str(bot['nombre']))}</b>\n\n"
        "La copia será registrada separadamente en el historial.",
        parse_mode="HTML",
    )
    resultado = await asyncio.to_thread(funcion, int(bot_id))
    if not resultado.get("correcto"):
        await query.edit_message_text(
            "❌ <b>COPIA NO DISPONIBLE</b>\n\n"
            f"{etiqueta}\n\n{html.escape(str(resultado.get('mensaje') or 'Error desconocido.'))}",
            parse_mode="HTML",
            reply_markup=teclado_fuentes_respaldo(int(bot_id)),
        )
        return

    respaldo_id = int(resultado["respaldo_id"])
    await query.edit_message_text(
        "✅ <b>COPIA POR FUENTE CREADA</b>\n\n"
        f"{etiqueta}\n"
        f"🤖 <b>{html.escape(str(bot['nombre']))}</b>\n"
        f"📦 <code>{html.escape(str(resultado['archivo']))}</code>\n"
        f"📏 <b>{formatear_tamano(resultado['tamano_bytes'])}</b>\n"
        f"🔐 <code>{html.escape(str(resultado['sha256']))}</code>\n"
        f"🇵🇪 {datetime.now(ZONA_PERU).strftime('%d/%m/%Y %H:%M')}\n\n"
        "La copia está lista. Puedes descargarla o marcarla para conservarla "
        "en la biblioteca interna del Bot Respaldos Premium.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬇️ Descargar", callback_data=f"respaldo_descargar:{respaldo_id}")],
            [InlineKeyboardButton(
                "💾 Guardar en Bot Respaldos Premium",
                callback_data=f"source_save:{respaldo_id}",
            )],
            [
                InlineKeyboardButton("⬅️ Volver a la fuente", callback_data=f"source_panel:{fuente}:{bot_id}"),
                InlineKeyboardButton("🏠 Inicio", callback_data="home"),
            ],
        ]),
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
        bot_id = int(opcion.split(":")[1])
        context.user_data.pop("restore_external_bot_id", None)
        bot = obtener_bot(bot_id)
        if not bot:
            await query.answer("El bot no existe.", show_alert=True)
            return
        await query.edit_message_text(
            "📥 <b>RESPALDOS DISPONIBLES</b>\n\n"
            f"🤖 <b>{html.escape(str(bot['nombre']))}</b>\n\n"
            "Selecciona el respaldo que deseas validar y restaurar.",
            parse_mode="HTML",
            reply_markup=teclado_respaldos_restauracion(bot_id),
        )
        return

    if opcion.startswith("restore_external_cancel:"):
        bot_id = int(opcion.split(":")[1])
        context.user_data.pop("restore_external_bot_id", None)
        await query.edit_message_text(
            "📥 <b>RESPALDOS DISPONIBLES</b>\n\n"
            "La carga externa fue cancelada.",
            parse_mode="HTML",
            reply_markup=teclado_respaldos_restauracion(bot_id),
        )
        return

    if opcion.startswith("restore_external:"):
        bot_id = int(opcion.split(":")[1])
        bot = obtener_bot(bot_id)
        if not bot:
            await query.answer("El bot no existe.", show_alert=True)
            return
        context.user_data["restore_external_bot_id"] = bot_id
        await query.edit_message_text(
            "📎 <b>ADJUNTAR RESPALDO EXTERNO</b>\n\n"
            f"🤖 <b>{html.escape(str(bot['nombre']))}</b>\n\n"
            "Envía ahora el archivo <code>.tar.gz</code> generado por Bot Respaldos Premium.\n\n"
            "Antes de registrarlo se validarán rutas, manifest, identidad del bot, tamaño y SHA-256. "
            "No se restaurará nada automáticamente: primero aparecerá la confirmación normal.",
            parse_mode="HTML",
            reply_markup=teclado_espera_archivo_externo(bot_id),
        )
        return

    if opcion.startswith("restore_sources:"):
        bot_id = int(opcion.split(":")[1])
        bot = obtener_bot(bot_id)
        if not bot:
            await query.answer("El bot no existe.", show_alert=True)
            return
        context.user_data.pop("restore_external_bot_id", None)
        await query.edit_message_text(
            texto_fuentes_respaldo(bot),
            parse_mode="HTML",
            reply_markup=teclado_fuentes_respaldo(bot_id),
        )
        return

    if opcion == "bulk_menu":
        await query.edit_message_text(
            texto_menu_masivo(),
            parse_mode="HTML",
            reply_markup=teclado_menu_masivo(),
        )
        return

    if opcion.startswith("bulk_run:"):
        fuente = opcion.split(":", 1)[1]
        await query.answer()
        if fuente == "completo":
            asyncio.create_task(ejecutar_lote_completo(query))
        else:
            asyncio.create_task(ejecutar_lote_fuente(query, fuente))
        return

    if opcion.startswith("bulk_retry:"):
        tipo = opcion.split(":", 1)[1]
        clave = "completo" if tipo == "completo" else f"fuente:{tipo}"
        ids = list(ULTIMOS_FALLIDOS_MASIVOS.get(clave) or [])
        if not ids:
            await query.answer("No hay fallidos pendientes para reintentar.", show_alert=True)
            return
        await query.answer()
        if tipo == "completo":
            asyncio.create_task(ejecutar_lote_completo(query, ids))
        else:
            asyncio.create_task(ejecutar_lote_fuente(query, tipo, ids))
        return

    if opcion == "bulk_validate":
        await query.answer()
        await ejecutar_validacion_masiva(query)
        return

    if opcion == "bulk_restore_plan":
        await query.edit_message_text(
            texto_plan_restauracion_masiva(),
            parse_mode="HTML",
            reply_markup=teclado_plan_restauracion_masiva(),
        )
        return

    if opcion == "bulk_restore_prepare":
        await query.edit_message_text(
            "🚨 <b>CONFIRMACIÓN DE RESTAURACIÓN MASIVA</b>\n\n"
            "Esta acción restaurará los bots <b>uno por uno</b> usando el último "
            "respaldo válido de cada uno.\n\n"
            "Antes de cada bot se aplicarán las validaciones y respaldo preventivo "
            "correspondientes. Si uno falla, el proceso se detendrá inmediatamente.\n\n"
            "La restauración MANUAL seguirá disponible aunque canceles este proceso.",
            parse_mode="HTML",
            reply_markup=teclado_confirmar_restauracion_masiva(),
        )
        return

    if opcion == "bulk_restore_confirm":
        await query.answer()
        asyncio.create_task(ejecutar_restauracion_masiva(query))
        return

    if opcion.startswith("source_panel:"):
        _, fuente, bot_id_texto = opcion.split(":", 2)
        bot_id = int(bot_id_texto)
        await query.edit_message_text(
            texto_panel_fuente(bot_id, fuente),
            parse_mode="HTML",
            reply_markup=teclado_panel_fuente(bot_id, fuente),
        )
        return

    if opcion.startswith("source_unavailable:"):
        _, fuente, bot_id_texto = opcion.split(":", 2)
        bot_id = int(bot_id_texto)
        bot = obtener_bot(bot_id)
        if not bot:
            await query.answer("El bot no existe.", show_alert=True)
            return
        _, detalle = estado_disponibilidad_fuente(bot, fuente)
        await query.answer(detalle, show_alert=True)
        return

    if opcion.startswith("source_library_source:"):
        _, fuente, bot_id_texto = opcion.split(":", 2)
        bot_id = int(bot_id_texto)
        await query.edit_message_text(
            texto_biblioteca_fuente(bot_id, fuente),
            parse_mode="HTML",
            reply_markup=teclado_biblioteca_fuente(bot_id, fuente),
        )
        return

    if opcion.startswith("backup_source:"):
        _, fuente, bot_id_texto = opcion.split(":", 2)
        await ejecutar_respaldo_fuente(update, context, fuente, int(bot_id_texto))
        return

    if opcion.startswith("source_library:"):
        bot_id = int(opcion.split(":", 1)[1])
        await query.edit_message_text(
            texto_biblioteca_fuentes(bot_id),
            parse_mode="HTML",
            reply_markup=teclado_biblioteca_fuentes(bot_id),
        )
        return

    if opcion.startswith("source_save:"):
        respaldo_id = int(opcion.split(":", 1)[1])
        respaldo = obtener_respaldo(respaldo_id)
        if not respaldo or not str(respaldo["tipo"] or "").upper().startswith("FUENTE_"):
            await query.answer("La copia por fuente no existe.", show_alert=True)
            return
        ruta = Path(str(respaldo["ruta"] or ""))
        if not ruta.is_file():
            await query.answer("El archivo ya no existe en almacenamiento.", show_alert=True)
            return
        actualizar_estado_respaldo(respaldo_id, "GUARDADO")
        await query.answer("Copia guardada en Bot Respaldos Premium.", show_alert=False)
        bot_id = int(respaldo["bot_id"])
        await query.edit_message_text(
            "💾 <b>COPIA GUARDADA</b>\n\n"
            f"{etiqueta_fuente(respaldo['tipo'])}\n"
            f"🤖 <b>{html.escape(str(respaldo['bot_nombre'] or 'Bot'))}</b>\n"
            f"📦 <code>{html.escape(str(respaldo['archivo']))}</code>\n"
            f"📏 <b>{formatear_tamano(respaldo['tamano_bytes'])}</b>\n"
            f"🔐 <code>{html.escape(str(respaldo['sha256'] or ''))}</code>\n"
            f"🇵🇪 Guardado: <b>{datetime.now(ZONA_PERU).strftime('%d/%m/%Y %H:%M')}</b>\n\n"
            "Queda conservada en la biblioteca interna para auditoría, diagnóstico o mejoras.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬇️ Descargar", callback_data=f"respaldo_descargar:{respaldo_id}")],
                [InlineKeyboardButton(
                    "📚 Ver copias guardadas",
                    callback_data=f"source_library_source:{str(respaldo['tipo'] or '').replace('FUENTE_', '').lower()}:{bot_id}",
                )],
                [InlineKeyboardButton(
                    "⬅️ Volver a la fuente",
                    callback_data=f"source_panel:{str(respaldo['tipo'] or '').replace('FUENTE_', '').lower()}:{bot_id}",
                )],
            ]),
        )
        return

    if opcion.startswith("source_saved_detail:"):
        respaldo_id = int(opcion.split(":", 1)[1])
        respaldo = obtener_respaldo(respaldo_id)
        if not respaldo:
            await query.answer("La copia no existe.", show_alert=True)
            return
        bot_id = int(respaldo["bot_id"])
        await query.edit_message_text(
            "📚 <b>COPIA GUARDADA POR FUENTE</b>\n\n"
            f"{etiqueta_fuente(respaldo['tipo'])}\n"
            f"🤖 <b>{html.escape(str(respaldo['bot_nombre'] or 'Bot'))}</b>\n"
            f"📦 <code>{html.escape(str(respaldo['archivo']))}</code>\n"
            f"📏 <b>{formatear_tamano(respaldo['tamano_bytes'])}</b>\n"
            f"🧾 Estado: <b>{html.escape(str(respaldo['estado'] or 'GUARDADO'))}</b>\n"
            f"🔐 <code>{html.escape(str(respaldo['sha256'] or ''))}</code>\n"
            f"🕐 {formatear_fecha_historial(respaldo['fecha_creacion'])}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬇️ Descargar", callback_data=f"respaldo_descargar:{respaldo_id}")],
                [InlineKeyboardButton(
                    "⬅️ Biblioteca de esta fuente",
                    callback_data=f"source_library_source:{str(respaldo['tipo'] or '').replace('FUENTE_', '').lower()}:{bot_id}",
                )],
            ]),
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

    if opcion.startswith("respaldo_restaurar_completo_confirmar:"):
        respaldo_id = int(opcion.split(":")[1])
        await ejecutar_restauracion_completa(update, context, respaldo_id)
        return

    if opcion.startswith("respaldo_restaurar_base_confirmar:"):
        respaldo_id = int(opcion.split(":")[1])
        await ejecutar_restauracion(update, context, respaldo_id)
        return

    if opcion.startswith("respaldo_restaurar_confirmar:"):
        respaldo_id = int(opcion.split(":")[1])
        await ejecutar_restauracion(update, context, respaldo_id)
        return

    if opcion.startswith("respaldo_restaurar:"):
        respaldo_id = int(opcion.split(":")[1])
        respaldo = obtener_respaldo(respaldo_id)
        if not respaldo:
            await query.answer("El respaldo no existe.", show_alert=True)
            return
        try:
            info = await asyncio.to_thread(inspeccionar_respaldo_para_restaurar, respaldo)
            manifest = info.get("manifiesto") or {}
            commit = html.escape(str(manifest.get("commit") or "No informado"))
            rama = html.escape(str(manifest.get("rama") or "No informada"))
            cantidad = len(info.get("archivos_codigo") or [])
            await query.edit_message_text(
                texto_detalle_respaldo(respaldo_id)
                + "\n\n⚠️ <b>CONFIRMAR RESTAURACIÓN</b>\n"
                + f"Archivos de código validados: <b>{cantidad}</b>\n"
                + f"Rama: <code>{rama}</code>\n"
                + f"Commit: <code>{commit}</code>\n\n"
                + "Se creará una copia del proyecto actual antes de reemplazar archivos.",
                parse_mode="HTML",
                reply_markup=teclado_confirmar_restauracion(
                    respaldo_id, int(respaldo["bot_id"])
                ),
            )
        except Exception as error:
            await query.answer(str(error), show_alert=True)
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
        "backup": "💾 <b>RESPALDO MANUAL</b>\n\nLa operación manual permanece siempre disponible. Selecciona <b>Bots Registrados</b>, abre un bot y pulsa <b>💾 Respaldar</b>.",
        "restore": texto_restaurar_bots(),
        "history": "📂 <b>HISTORIAL GENERAL</b>\n\nAbre <b>Bots Registrados</b>, selecciona un bot y pulsa <b>📂 Historial</b>.",
        "status": "❤️ <b>ESTADO DE BOTS</b>\n\nEl monitoreo automático se integrará en una próxima mejora.",
        "settings": "⚙️ <b>CONFIGURACIÓN</b>\n\nDesde <b>Bots Registrados</b> puedes agregar y editar los proyectos administrados.",
    }

    if opcion == "close":
        await query.edit_message_text(
            "✅ Panel cerrado.\n\nUsa /start para abrirlo nuevamente."
        )
        return

    if opcion == "restore":
        await query.edit_message_text(
            texto_restaurar_bots(),
            parse_mode="HTML",
            reply_markup=teclado_restaurar_bots(),
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
    application.add_handler(MessageHandler(filters.Document.ALL, recibir_respaldo_externo), group=1)
    application.add_handler(CallbackQueryHandler(botones_generales))

    print(f"BOT RESPALDOS PREMIUM {VERSION} iniciado.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
