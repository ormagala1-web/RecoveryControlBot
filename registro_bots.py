import html
import sqlite3
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from database import (
    actualizar_bot,
    cambiar_estado_bot,
    contar_bots,
    eliminar_bot,
    obtener_bot,
    obtener_bots,
    registrar_bot,
)


ZONA_PERU = ZoneInfo("America/Lima")

ESTADOS_VISUALES = {
    "ACTIVO": ("🟢", "Activo"),
    "PAUSADO": ("🟡", "Pausado"),
    "INACTIVO": ("⚪", "Inactivo"),
    "ERROR": ("🔴", "Error"),
}


def normalizar_username(username: Optional[str]) -> Optional[str]:
    valor = str(username or "").strip()

    if not valor:
        return None

    if not valor.startswith("@"):
        valor = f"@{valor}"

    return valor


def formatear_fecha_peru(fecha_iso: Optional[str]) -> str:
    valor = str(fecha_iso or "").strip()

    if not valor:
        return "Sin fecha"

    try:
        fecha = datetime.fromisoformat(valor.replace("Z", "+00:00"))

        if fecha.tzinfo is None:
            fecha = fecha.replace(tzinfo=timezone.utc)

        fecha_peru = fecha.astimezone(ZONA_PERU)
        return fecha_peru.strftime("%d/%m/%Y %H:%M")
    except (TypeError, ValueError):
        return valor


def obtener_estado_visual(estado: Optional[str]) -> tuple[str, str]:
    clave = str(estado or "INACTIVO").upper()
    return ESTADOS_VISUALES.get(clave, ("⚪", clave.title()))


def texto_lista_bots() -> str:
    bots = obtener_bots()

    if not bots:
        return (
            "🤖 <b>BOTS REGISTRADOS</b>\n\n"
            "Todavía no hay bots registrados.\n\n"
            "Pulsa <b>➕ Registrar Bot</b> para agregar el primero."
        )

    lineas = [
        "🤖 <b>BOTS REGISTRADOS</b>",
        "",
        f"Total: <b>{len(bots)}</b>",
        "",
    ]

    for bot in bots:
        icono, estado_legible = obtener_estado_visual(bot["estado"])
        nombre = html.escape(str(bot["nombre"] or "Sin nombre"))
        username = html.escape(str(bot["username"] or "Sin usuario"))

        lineas.append(
            f"{icono} <b>{nombre}</b>\n"
            f"   {username} · {html.escape(estado_legible)}"
        )

    return "\n".join(lineas)


def teclado_lista_bots() -> InlineKeyboardMarkup:
    bots = obtener_bots()
    filas = []

    for bot in bots:
        icono, _ = obtener_estado_visual(bot["estado"])
        nombre = str(bot["nombre"] or "Sin nombre")

        filas.append(
            [
                InlineKeyboardButton(
                    f"{icono} {nombre}",
                    callback_data=f"bot_detalle:{bot['id']}",
                )
            ]
        )

    filas.append(
        [
            InlineKeyboardButton(
                "➕ Registrar Bot",
                callback_data="bot_registrar",
            )
        ]
    )

    filas.append(
        [
            InlineKeyboardButton(
                "🔄 Actualizar",
                callback_data="bots",
            ),
            InlineKeyboardButton(
                "🏠 Menú Principal",
                callback_data="home",
            ),
        ]
    )

    filas.append(
        [
            InlineKeyboardButton(
                "❌ Cerrar",
                callback_data="close",
            )
        ]
    )

    return InlineKeyboardMarkup(filas)


def texto_detalle_bot(bot_id: int) -> Optional[str]:
    bot = obtener_bot(bot_id)

    if not bot:
        return None

    icono_estado, estado_legible = obtener_estado_visual(bot["estado"])

    nombre = html.escape(str(bot["nombre"] or "Sin nombre"))
    username = html.escape(str(bot["username"] or "No configurado"))
    descripcion = html.escape(
        str(bot["descripcion"] or "Sin descripción")
    )
    repositorio = html.escape(
        str(bot["repositorio"] or "No configurado")
    )
    servidor = html.escape(
        str(bot["servidor"] or "No configurado")
    )
    ruta_proyecto = html.escape(
        str(bot["ruta_proyecto"] or "No configurada")
    )
    ruta_base = html.escape(
        str(bot["ruta_base_datos"] or "No configurada")
    )
    fecha = html.escape(formatear_fecha_peru(bot["fecha_registro"]))

    return (
        f"{icono_estado} <b>{nombre}</b>\n\n"
        f"🆔 ID: <code>{bot['id']}</code>\n"
        f"👤 Usuario: {username}\n"
        f"{icono_estado} Estado: <b>{html.escape(estado_legible)}</b>\n\n"
        f"📝 <b>Descripción</b>\n"
        f"{descripcion}\n\n"
        f"🌐 <b>Repositorio</b>\n"
        f"{repositorio}\n\n"
        f"🖥 <b>Servidor</b>\n"
        f"{servidor}\n\n"
        f"📂 <b>Ruta del proyecto</b>\n"
        f"{ruta_proyecto}\n\n"
        f"🗃 <b>Base de datos</b>\n"
        f"{ruta_base}\n\n"
        f"📅 <b>Registrado</b>\n"
        f"{fecha} (Perú)"
    )


def teclado_detalle_bot(
    bot_id: int,
    estado: str,
) -> InlineKeyboardMarkup:
    estado = str(estado or "INACTIVO").upper()

    if estado == "ACTIVO":
        boton_estado = InlineKeyboardButton(
            "⏸ Pausar",
            callback_data=f"bot_estado:{bot_id}:PAUSADO",
        )
    else:
        boton_estado = InlineKeyboardButton(
            "▶️ Activar",
            callback_data=f"bot_estado:{bot_id}:ACTIVO",
        )

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✏️ Editar",
                    callback_data=f"bot_editar:{bot_id}",
                ),
                InlineKeyboardButton(
                    "💾 Respaldar",
                    callback_data=f"bot_backup:{bot_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    "📥 Restaurar",
                    callback_data=f"bot_restore:{bot_id}",
                ),
                InlineKeyboardButton(
                    "📂 Historial",
                    callback_data=f"bot_history:{bot_id}",
                ),
            ],
            [
                boton_estado,
                InlineKeyboardButton(
                    "🗑 Eliminar",
                    callback_data=f"bot_eliminar:{bot_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Bots",
                    callback_data="bots",
                ),
                InlineKeyboardButton(
                    "🏠 Inicio",
                    callback_data="home",
                ),
            ],
            [
                InlineKeyboardButton(
                    "❌ Cerrar",
                    callback_data="close",
                )
            ],
        ]
    )


def teclado_confirmar_eliminacion(
    bot_id: int,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Sí, eliminar",
                    callback_data=f"bot_eliminar_confirmar:{bot_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Cancelar",
                    callback_data=f"bot_detalle:{bot_id}",
                ),
                InlineKeyboardButton(
                    "🏠 Menú Principal",
                    callback_data="home",
                ),
            ],
        ]
    )


def crear_bot_desde_datos(datos: dict) -> tuple[bool, str, Optional[int]]:
    nombre = str(datos.get("nombre") or "").strip()
    username = normalizar_username(datos.get("username"))

    if not nombre:
        return False, "El nombre del bot es obligatorio.", None

    try:
        bot_id = registrar_bot(
            nombre=nombre,
            username=username,
            descripcion=str(
                datos.get("descripcion") or ""
            ).strip() or None,
            repositorio=str(
                datos.get("repositorio") or ""
            ).strip() or None,
            servidor=str(
                datos.get("servidor") or ""
            ).strip() or None,
            ruta_proyecto=str(
                datos.get("ruta_proyecto") or ""
            ).strip() or None,
            ruta_base_datos=str(
                datos.get("ruta_base_datos") or ""
            ).strip() or None,
        )

        return True, "Bot registrado correctamente.", bot_id

    except sqlite3.IntegrityError:
        return (
            False,
            "Ya existe un bot registrado con ese usuario.",
            None,
        )

    except ValueError as error:
        return False, str(error), None


def cambiar_estado(
    bot_id: int,
    estado: str,
) -> tuple[bool, str]:
    try:
        actualizado = cambiar_estado_bot(
            bot_id,
            estado,
        )

        if not actualizado:
            return False, "No se encontró el bot."

        _, estado_legible = obtener_estado_visual(estado)
        return True, f"Estado cambiado a {estado_legible}."

    except ValueError as error:
        return False, str(error)


def borrar_bot(
    bot_id: int,
) -> tuple[bool, str]:
    eliminado = eliminar_bot(bot_id)

    if not eliminado:
        return False, "No se encontró el bot."

    return True, "Bot eliminado del registro."


def resumen_general() -> str:
    total = contar_bots()
    bots = obtener_bots()

    activos = sum(
        1
        for bot in bots
        if str(bot["estado"] or "").upper() == "ACTIVO"
    )
    pausados = sum(
        1
        for bot in bots
        if str(bot["estado"] or "").upper() == "PAUSADO"
    )
    errores = sum(
        1
        for bot in bots
        if str(bot["estado"] or "").upper() == "ERROR"
    )

    return (
        "📊 <b>RESUMEN DE BOTS</b>\n\n"
        f"🤖 Registrados: <b>{total}</b>\n"
        f"🟢 Activos: <b>{activos}</b>\n"
        f"🟡 Pausados: <b>{pausados}</b>\n"
        f"🔴 Con error: <b>{errores}</b>"
    )
