import os
import sqlite3
from datetime import datetime, timezone
from typing import Optional


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "database")
DATABASE_PATH = os.path.join(DATA_DIR, "recovery_control.db")


def ahora_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def conectar_db() -> sqlite3.Connection:
    os.makedirs(DATA_DIR, exist_ok=True)

    conexion = sqlite3.connect(DATABASE_PATH)
    conexion.row_factory = sqlite3.Row
    return conexion


def inicializar_base_datos() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)

    with conectar_db() as conexion:
        conexion.execute(
            """
            CREATE TABLE IF NOT EXISTS bots_registrados (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                username TEXT,
                descripcion TEXT,
                repositorio TEXT,
                servidor TEXT,
                ruta_proyecto TEXT,
                ruta_base_datos TEXT,
                estado TEXT NOT NULL DEFAULT 'ACTIVO',
                fecha_registro TEXT NOT NULL,
                fecha_actualizacion TEXT
            )
            """
        )

        conexion.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
            idx_bots_username
            ON bots_registrados(username)
            WHERE username IS NOT NULL
            """
        )

        conexion.execute(
            """
            CREATE TABLE IF NOT EXISTS historial_respaldos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_id INTEGER NOT NULL,
                archivo TEXT NOT NULL,
                ruta TEXT NOT NULL,
                tipo TEXT NOT NULL DEFAULT 'MANUAL',
                estado TEXT NOT NULL DEFAULT 'CREADO',
                tamano_bytes INTEGER,
                sha256 TEXT,
                fecha_creacion TEXT NOT NULL,
                observacion TEXT,
                FOREIGN KEY(bot_id)
                    REFERENCES bots_registrados(id)
                    ON DELETE CASCADE
            )
            """
        )

        conexion.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_historial_respaldos_bot
            ON historial_respaldos(bot_id, fecha_creacion)
            """
        )

        conexion.commit()


def registrar_bot(
    nombre: str,
    username: Optional[str] = None,
    descripcion: Optional[str] = None,
    repositorio: Optional[str] = None,
    servidor: Optional[str] = None,
    ruta_proyecto: Optional[str] = None,
    ruta_base_datos: Optional[str] = None,
) -> int:
    nombre = str(nombre or "").strip()

    if not nombre:
        raise ValueError("El nombre del bot es obligatorio.")

    username = str(username or "").strip() or None

    if username and not username.startswith("@"):
        username = f"@{username}"

    fecha = ahora_utc()

    with conectar_db() as conexion:
        cursor = conexion.execute(
            """
            INSERT INTO bots_registrados (
                nombre,
                username,
                descripcion,
                repositorio,
                servidor,
                ruta_proyecto,
                ruta_base_datos,
                estado,
                fecha_registro
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 'ACTIVO', ?)
            """,
            (
                nombre,
                username,
                descripcion,
                repositorio,
                servidor,
                ruta_proyecto,
                ruta_base_datos,
                fecha,
            ),
        )

        conexion.commit()
        return int(cursor.lastrowid)


def obtener_bots() -> list[sqlite3.Row]:
    with conectar_db() as conexion:
        return conexion.execute(
            """
            SELECT *
            FROM bots_registrados
            ORDER BY
                CASE estado
                    WHEN 'ACTIVO' THEN 0
                    WHEN 'PAUSADO' THEN 1
                    ELSE 2
                END,
                nombre COLLATE NOCASE
            """
        ).fetchall()


def obtener_bot(bot_id: int) -> Optional[sqlite3.Row]:
    with conectar_db() as conexion:
        return conexion.execute(
            """
            SELECT *
            FROM bots_registrados
            WHERE id = ?
            LIMIT 1
            """,
            (int(bot_id),),
        ).fetchone()


def obtener_bot_por_username(
    username: str,
) -> Optional[sqlite3.Row]:
    username = str(username or "").strip()

    if username and not username.startswith("@"):
        username = f"@{username}"

    with conectar_db() as conexion:
        return conexion.execute(
            """
            SELECT *
            FROM bots_registrados
            WHERE LOWER(username) = LOWER(?)
            LIMIT 1
            """,
            (username,),
        ).fetchone()


def actualizar_bot(bot_id: int, **campos) -> bool:
    permitidos = {
        "nombre",
        "username",
        "descripcion",
        "repositorio",
        "servidor",
        "ruta_proyecto",
        "ruta_base_datos",
        "estado",
    }

    datos = {
        clave: valor
        for clave, valor in campos.items()
        if clave in permitidos
    }

    if not datos:
        return False

    if "username" in datos:
        username = str(datos["username"] or "").strip()

        if username and not username.startswith("@"):
            username = f"@{username}"

        datos["username"] = username or None

    datos["fecha_actualizacion"] = ahora_utc()

    columnas = [f"{clave} = ?" for clave in datos]
    valores = list(datos.values())
    valores.append(int(bot_id))

    with conectar_db() as conexion:
        cursor = conexion.execute(
            f"""
            UPDATE bots_registrados
            SET {", ".join(columnas)}
            WHERE id = ?
            """,
            valores,
        )

        conexion.commit()
        return cursor.rowcount > 0


def cambiar_estado_bot(
    bot_id: int,
    estado: str,
) -> bool:
    estados_permitidos = {
        "ACTIVO",
        "PAUSADO",
        "INACTIVO",
        "ERROR",
    }

    estado = str(estado or "").strip().upper()

    if estado not in estados_permitidos:
        raise ValueError("Estado de bot no válido.")

    return actualizar_bot(
        bot_id,
        estado=estado,
    )


def eliminar_bot(bot_id: int) -> bool:
    with conectar_db() as conexion:
        cursor = conexion.execute(
            """
            DELETE FROM bots_registrados
            WHERE id = ?
            """,
            (int(bot_id),),
        )

        conexion.commit()
        return cursor.rowcount > 0


def contar_bots() -> int:
    with conectar_db() as conexion:
        fila = conexion.execute(
            """
            SELECT COUNT(*) AS total
            FROM bots_registrados
            """
        ).fetchone()

        return int(fila["total"] if fila else 0)


def registrar_respaldo(
    bot_id: int,
    archivo: str,
    ruta: str,
    tipo: str = "MANUAL",
    estado: str = "CREADO",
    tamano_bytes: Optional[int] = None,
    sha256: Optional[str] = None,
    observacion: Optional[str] = None,
) -> int:
    fecha = ahora_utc()

    with conectar_db() as conexion:
        cursor = conexion.execute(
            """
            INSERT INTO historial_respaldos (
                bot_id,
                archivo,
                ruta,
                tipo,
                estado,
                tamano_bytes,
                sha256,
                fecha_creacion,
                observacion
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(bot_id),
                str(archivo),
                str(ruta),
                str(tipo).upper(),
                str(estado).upper(),
                tamano_bytes,
                sha256,
                fecha,
                observacion,
            ),
        )

        conexion.commit()
        return int(cursor.lastrowid)


def obtener_respaldos_bot(
    bot_id: int,
    limite: int = 20,
) -> list[sqlite3.Row]:
    with conectar_db() as conexion:
        return conexion.execute(
            """
            SELECT *
            FROM historial_respaldos
            WHERE bot_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (
                int(bot_id),
                max(1, int(limite)),
            ),
        ).fetchall()


def obtener_respaldo(respaldo_id: int) -> Optional[sqlite3.Row]:
    with conectar_db() as conexion:
        return conexion.execute(
            """
            SELECT
                h.*,
                b.nombre AS bot_nombre,
                b.username AS bot_username
            FROM historial_respaldos AS h
            JOIN bots_registrados AS b
                ON b.id = h.bot_id
            WHERE h.id = ?
            LIMIT 1
            """,
            (int(respaldo_id),),
        ).fetchone()


def obtener_ultimos_respaldos(
    limite: int = 30,
) -> list[sqlite3.Row]:
    with conectar_db() as conexion:
        return conexion.execute(
            """
            SELECT
                h.*,
                b.nombre AS bot_nombre,
                b.username AS bot_username
            FROM historial_respaldos AS h
            JOIN bots_registrados AS b
                ON b.id = h.bot_id
            ORDER BY h.id DESC
            LIMIT ?
            """,
            (max(1, int(limite)),),
        ).fetchall()


inicializar_base_datos()
