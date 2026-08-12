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

        # Migración idempotente del historial, compatible con v1.1.1.
        columnas = {
            fila["name"]
            for fila in conexion.execute(
                "PRAGMA table_info(historial_respaldos)"
            ).fetchall()
        }

        nuevas_columnas = [
            ("numero_bot", "INTEGER"),
            ("version", "TEXT"),
            ("version_estado", "TEXT NOT NULL DEFAULT 'LEGADO'"),
            ("fuente", "TEXT"),
            ("fecha_peru", "TEXT"),
        ]

        columna_numero_nueva = "numero_bot" not in columnas
        for nombre, tipo in nuevas_columnas:
            if nombre not in columnas:
                conexion.execute(
                    f"ALTER TABLE historial_respaldos ADD COLUMN {nombre} {tipo}"
                )

        if columna_numero_nueva:
            bots = conexion.execute(
                "SELECT id FROM bots_registrados ORDER BY id"
            ).fetchall()
            for bot in bots:
                filas = conexion.execute(
                    """
                    SELECT id, fecha_creacion, tipo
                    FROM historial_respaldos
                    WHERE bot_id = ?
                    ORDER BY fecha_creacion ASC, id ASC
                    """,
                    (int(bot["id"]),),
                ).fetchall()
                for numero, fila in enumerate(filas, start=1):
                    tipo_normalizado = str(fila["tipo"] or "").upper()
                    fuente = {
                        "FUENTE_GITHUB": "GITHUB",
                        "FUENTE_JUSTRUNMY": "JUSTRUNMY",
                        "FUENTE_ORACLE": "ORACLE",
                        "MANUAL": "COMPLETO",
                        "MASIVO": "COMPLETO",
                    }.get(tipo_normalizado, tipo_normalizado or "DESCONOCIDA")

                    fecha_peru = None
                    try:
                        from zoneinfo import ZoneInfo
                        fecha_dt = datetime.fromisoformat(
                            str(fila["fecha_creacion"]).replace("Z", "+00:00")
                        )
                        if fecha_dt.tzinfo is None:
                            fecha_dt = fecha_dt.replace(tzinfo=timezone.utc)
                        fecha_peru = fecha_dt.astimezone(
                            ZoneInfo("America/Lima")
                        ).strftime("%d/%m/%Y %H:%M:%S")
                    except Exception:
                        pass

                    conexion.execute(
                        """
                        UPDATE historial_respaldos
                        SET numero_bot = ?,
                            version_estado = COALESCE(NULLIF(version_estado, ''), 'LEGADO'),
                            fuente = COALESCE(NULLIF(fuente, ''), ?),
                            fecha_peru = COALESCE(NULLIF(fecha_peru, ''), ?)
                        WHERE id = ?
                        """,
                        (numero, fuente, fecha_peru, int(fila["id"])),
                    )

        conexion.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
            idx_historial_bot_numero
            ON historial_respaldos (bot_id, numero_bot)
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
    version: Optional[str] = None,
    version_estado: Optional[str] = None,
) -> int:
    fecha = ahora_utc()
    tipo_normalizado = str(tipo).upper()

    mapa_fuentes = {
        "FUENTE_GITHUB": "GITHUB",
        "FUENTE_JUSTRUNMY": "JUSTRUNMY",
        "FUENTE_ORACLE": "ORACLE",
        "MANUAL": "COMPLETO",
        "MASIVO": "COMPLETO",
    }
    fuente = mapa_fuentes.get(tipo_normalizado, tipo_normalizado or "DESCONOCIDA")

    try:
        from zoneinfo import ZoneInfo
        fecha_dt = datetime.fromisoformat(fecha.replace("Z", "+00:00"))
        fecha_peru = fecha_dt.astimezone(
            ZoneInfo("America/Lima")
        ).strftime("%d/%m/%Y %H:%M:%S")
    except Exception:
        fecha_peru = None

    version_limpia = str(version or "").strip() or None
    estado_version = str(version_estado or "").strip().upper()
    if not estado_version:
        estado_version = "IDENTIFICADA" if version_limpia else "SIN_VERSION"

    with conectar_db() as conexion:
        conexion.execute("BEGIN IMMEDIATE")

        fila = conexion.execute(
            """
            SELECT COALESCE(MAX(numero_bot), 0) + 1 AS siguiente
            FROM historial_respaldos
            WHERE bot_id = ?
            """,
            (int(bot_id),),
        ).fetchone()

        numero_bot = int(fila["siguiente"])

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
                observacion,
                numero_bot,
                version,
                version_estado,
                fuente,
                fecha_peru
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(bot_id),
                str(archivo),
                str(ruta),
                tipo_normalizado,
                str(estado).upper(),
                tamano_bytes,
                sha256,
                fecha,
                observacion,
                numero_bot,
                version_limpia,
                estado_version,
                fuente,
                fecha_peru,
            ),
        )

        conexion.commit()
        return int(cursor.lastrowid)

def actualizar_archivo_respaldo(
    respaldo_id: int,
    archivo: str,
    ruta: str,
) -> bool:
    with conectar_db() as conexion:
        cursor = conexion.execute(
            """
            UPDATE historial_respaldos
            SET archivo = ?,
                ruta = ?
            WHERE id = ?
            """,
            (
                str(archivo),
                str(ruta),
                int(respaldo_id),
            ),
        )
        conexion.commit()
        return cursor.rowcount > 0


def actualizar_estado_respaldo(
    respaldo_id: int,
    estado: str,
) -> bool:
    with conectar_db() as conexion:
        cursor = conexion.execute(
            """
            UPDATE historial_respaldos
            SET estado = ?
            WHERE id = ?
            """,
            (
                str(estado).upper(),
                int(respaldo_id),
            ),
        )
        conexion.commit()
        return cursor.rowcount > 0


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
            ORDER BY numero_bot DESC, id DESC
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
