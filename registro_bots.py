import html
import sqlite3
from typing import Optional

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


ESTADOS_VISUALES = {
    "ACTIVO": "🟢",
    "PAUSADO": "🟡",
    "INACTIVO": "⚪",
    "ERROR": "🔴",
}


def normalizar_username(username: Optional[str]) -> Optional[str]:
    valor = str(username or "").strip()

    if not valor:
        return None

    if not valor.startswith("@"):
        valor = f"@{valor}"

    return valor


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
        estado = str(bot["estado"] or "INACTIVO").upper()
        icono = ESTADOS_VISUALES.get(estado, "⚪")
        nombre = html.escape(str(bot["nombre"] or "Sin nombre"))
        username = html.escape(str(bot["username"] or "Sin usuario"))

        lineas.append(
            f"{icono} <b>#{bot['id']} · {nombre}</b>\n"
            f"   {username}"
        )

    return "\n".join(lineas)


def teclado_lista_bots() -> InlineKeyboardMarkup:
    bots = obtener_bots()
    filas = []

    for bot in bots:
        estado = str(bot["estado"] or "INACTIVO").upper()
        icono = ESTADOS_VISUALES.get(estado, "⚪")
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
                "⬅️ Menú Principal",
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

    estado = str(bot["estado"] or "INACTIVO").upper()
    icono = ESTADOS_VISUALES.get(estado, "⚪")

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
    fecha = html.escape(str(bot["fecha_registro"] or "Sin fecha"))

    return (
        f"{icono} <b>{nombre}</b>\n\n"
        f"🆔 ID interno: <code>{bot['id']}</code>\n"
        f"👤 Usuario: {username}\n"
        f"📊 Estado: <b>{html.escape(estado)}</b>\n\n"
        f"📝 Descripción:\n{descripcion}\n\n"
        f"🌐 Repositorio:\n{repositorio}\n\n"
        f"🖥 Servidor:\n{servidor}\n\n"
        f"📂 Ruta del proyecto:\n{ruta_proyecto}\n\n"
        f"🗃 Base de datos:\n{ruta_base}\n\n"
        f"📅 Registrado:\n{fecha}"
    )


def teclado_detalle_bot(
    bot_id: int,
    estado: str,
) -> InlineKeyboardMarkup:
    estado = str(estado or "INACTIVO").upper()
    filas = []

    if estado == "ACTIVO":
        filas.append(
            [
                InlineKeyboardButton(
                    "⏸ Pausar",
                    callback_data=f"bot_estado:{bot_id}:PAUSADO",
                )
            ]
        )
    else:
        filas.append(
            [
                InlineKeyboardButton(
                    "▶️ Activar",
                    callback_data=f"bot_estado:{bot_id}:ACTIVO",
                )
            ]
        )

    filas.extend(
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
                InlineKeyboardButton(
                    "🗑 Eliminar",
                    callback_data=f"bot_eliminar:{bot_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Bots Registrados",
                    callback_data="bots",
                ),
                InlineKeyboardButton(
                    "🏠 Menú Principal",
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

    return InlineKeyboardMarkup(filas)


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

        return True, f"Estado cambiado a {estado.upper()}."

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
