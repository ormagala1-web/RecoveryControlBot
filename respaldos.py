import hashlib
import hmac
import json
import os
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
import zipfile
import unicodedata
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from dotenv import load_dotenv
from database import obtener_bot, registrar_respaldo

load_dotenv(Path(__file__).resolve().parent / '.env')


BASE_DIR = Path(__file__).resolve().parent
BACKUPS_DIR = BASE_DIR / "backups"
CACHE_DIR = BASE_DIR / "cache_repositorios"

ZONA_PERU = ZoneInfo("America/Lima")
MAX_EXTERNAL_BACKUP_BYTES = int(
    os.getenv("MAX_EXTERNAL_BACKUP_BYTES", str(50 * 1024 * 1024))
)


def sello_peru() -> str:
    return datetime.now(ZONA_PERU).strftime("%Y%m%d_%H%M%S")


def fecha_peru_iso() -> str:
    return datetime.now(ZONA_PERU).isoformat()

PUBLICIDAD_AGENT_URL = os.getenv(
    "PUBLICIDAD_AGENT_URL",
    "https://publicidad-103.c.jrnm.app",
).rstrip("/")
PUBLICIDAD_AGENT_SECRET = os.getenv(
    "PUBLICIDAD_AGENT_SECRET",
    "",
).strip()
PUBLICIDAD_AGENT_TIMEOUT = int(
    os.getenv("PUBLICIDAD_AGENT_TIMEOUT", "180")
)
PUBLICIDAD_BACKUP_GIT_BRANCH = os.getenv(
    "PUBLICIDAD_BACKUP_GIT_BRANCH",
    "motor-recuperacion-premium",
).strip()
MAXIMO_AGENT_URL = os.getenv(
    "MAXIMO_AGENT_URL",
    "",
).rstrip("/")
MAXIMO_AGENT_SECRET = os.getenv(
    "MAXIMO_AGENT_SECRET",
    "",
).strip()
MAXIMO_AGENT_TIMEOUT = int(
    os.getenv("MAXIMO_AGENT_TIMEOUT", "180")
)
MAXIMO_BACKUP_GIT_BRANCH = os.getenv(
    "MAXIMO_BACKUP_GIT_BRANCH",
    "motor-recuperacion-premium",
).strip()
MAXIMO_DB_FILENAME = os.getenv(
    "MAXIMO_DB_FILENAME",
    "maximo_control.db",
).strip()
MAXIMO_PRODUCT_NAME = os.getenv(
    "MAXIMO_PRODUCT_NAME",
    "MaximoControlGroup",
).strip()

MEMBRESIAS_AGENT_URL = os.getenv(
    "MEMBRESIAS_AGENT_URL",
    "",
).rstrip("/")
MEMBRESIAS_AGENT_SECRET = os.getenv(
    "MEMBRESIAS_AGENT_SECRET",
    "",
).strip()
MEMBRESIAS_AGENT_TIMEOUT = int(
    os.getenv("MEMBRESIAS_AGENT_TIMEOUT", "180")
)
MEMBRESIAS_BACKUP_GIT_BRANCH = os.getenv(
    "MEMBRESIAS_BACKUP_GIT_BRANCH",
    "main",
).strip()
MEMBRESIAS_DB_FILENAME = os.getenv(
    "MEMBRESIAS_DB_FILENAME",
    "membresias_consultas_denuncias.db",
).strip()
MEMBRESIAS_PRODUCT_NAME = os.getenv(
    "MEMBRESIAS_PRODUCT_NAME",
    "MembresiaConsultasDenunciasBot",
).strip()
MAX_REMOTE_BACKUP_BYTES = int(
    os.getenv(
        "MAX_REMOTE_BACKUP_BYTES",
        str(500 * 1024 * 1024),
    )
)

CARPETAS_EXCLUIDAS = {
    ".git",
    "__pycache__",
    "venv",
    ".venv",
    "backups",
    "restore",
    "logs",
}

EXTENSIONES_EXCLUIDAS = {
    ".pyc",
    ".pyo",
}

ARCHIVOS_SECRETOS_EXCLUIDOS = {
    ".env",
    ".env.local",
    ".env.production",
    "id_rsa",
    "id_ed25519",
}
EXTENSIONES_SECRETAS_EXCLUIDAS = {
    ".pem",
    ".ppk",
    ".key",
}


def nombre_seguro(texto: str) -> str:
    resultado = []

    for caracter in str(texto or "").strip():
        if caracter.isalnum() or caracter in {"-", "_"}:
            resultado.append(caracter)
        elif caracter.isspace():
            resultado.append("_")

    return "".join(resultado).strip("_") or "bot"


def normalizar_repositorio(url: str) -> str:
    valor = str(url or "").strip()

    if not valor:
        raise ValueError("El bot no tiene configurado un repositorio GitHub.")

    if valor.startswith("git@github.com:"):
        ruta = valor.removeprefix("git@github.com:")
        valor = f"https://github.com/{ruta}"

    if valor.endswith(".git"):
        valor = valor[:-4]

    analizado = urlparse(valor)

    if analizado.scheme not in {"http", "https"}:
        raise ValueError("El repositorio debe usar una dirección HTTPS de GitHub.")

    if analizado.netloc.lower() != "github.com":
        raise ValueError("Actualmente solo se admiten repositorios de GitHub.")

    partes = [parte for parte in analizado.path.split("/") if parte]

    if len(partes) != 2:
        raise ValueError(
            "El repositorio debe tener el formato "
            "https://github.com/usuario/proyecto"
        )

    return f"git@github.com:{partes[0]}/{partes[1]}"


def calcular_sha256(ruta_archivo: Path) -> str:
    sha256 = hashlib.sha256()

    with ruta_archivo.open("rb") as archivo:
        while True:
            bloque = archivo.read(1024 * 1024)

            if not bloque:
                break

            sha256.update(bloque)

    return sha256.hexdigest()


def validar_sqlite(ruta: Path) -> None:
    if not ruta.is_file() or ruta.stat().st_size <= 0:
        raise RuntimeError("La base de datos remota no existe o está vacía.")

    conexion = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)
    try:
        resultado = conexion.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0]

        if str(resultado).lower() != "ok":
            raise RuntimeError(
                f"La base remota no superó integrity_check: {resultado}"
            )
    finally:
        conexion.close()


def ejecutar_git(
    argumentos: list[str],
    cwd: Optional[Path] = None,
    timeout: int = 180,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *argumentos],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def descargar_repositorio(
    repositorio: str,
    destino: Path,
    rama: Optional[str] = None,
) -> dict:
    argumentos = [
        "clone",
        "--depth",
        "1",
        "--single-branch",
    ]

    rama = str(rama or "").strip()
    if rama:
        argumentos.extend(["--branch", rama])

    argumentos.extend([
        f"{repositorio}.git",
        str(destino),
    ])

    resultado = ejecutar_git(argumentos)

    if resultado.returncode != 0:
        detalle = (
            resultado.stderr.strip()
            or resultado.stdout.strip()
            or "Git no proporcionó detalles."
        )
        if rama:
            raise RuntimeError(
                "No se pudo descargar desde GitHub la rama "
                f"{rama!r}. Detalle: {detalle}"
            )
        raise RuntimeError(
            "No se pudo descargar el repositorio desde GitHub. "
            f"Detalle: {detalle}"
        )

    commit = ejecutar_git(
        ["rev-parse", "HEAD"],
        cwd=destino,
    )
    rama_real = ejecutar_git(
        ["rev-parse", "--abbrev-ref", "HEAD"],
        cwd=destino,
    )

    return {
        "commit": commit.stdout.strip() if commit.returncode == 0 else "",
        "rama": rama_real.stdout.strip() if rama_real.returncode == 0 else "",
        "rama_solicitada": rama,
    }


def agregar_directorio(
    archivo_tar: tarfile.TarFile,
    ruta_origen: Path,
    nombre_raiz: str,
) -> int:
    archivos_agregados = 0

    for ruta in sorted(ruta_origen.rglob("*")):
        if ruta.is_symlink():
            continue

        relativa = ruta.relative_to(ruta_origen)

        if any(parte in CARPETAS_EXCLUIDAS for parte in relativa.parts):
            continue

        if ruta.is_file() and ruta.suffix.lower() in EXTENSIONES_EXCLUIDAS:
            continue

        if ruta.is_file() and ruta.name.lower() in ARCHIVOS_SECRETOS_EXCLUIDOS:
            continue

        if ruta.is_file() and ruta.suffix.lower() in EXTENSIONES_SECRETAS_EXCLUIDAS:
            continue

        if ruta.is_file():
            archivo_tar.add(
                ruta,
                arcname=str(Path(nombre_raiz) / relativa),
                recursive=False,
            )
            archivos_agregados += 1

    return archivos_agregados


def crear_manifest(
    carpeta: Path,
    datos: dict,
) -> Path:
    ruta_manifest = carpeta / "manifest.json"

    with ruta_manifest.open("w", encoding="utf-8") as archivo:
        json.dump(
            datos,
            archivo,
            ensure_ascii=False,
            indent=2,
        )

    return ruta_manifest


def es_publicidad_bot(bot) -> bool:
    nombre = str(bot["nombre"] or "").strip().upper()
    username = str(bot["username"] or "").strip().lower()
    repositorio = str(bot["repositorio"] or "").strip().lower()

    return (
        username == "@publicidadcontrolstreaming_bot"
        or nombre == "PUBLICIDAD CONTROL STREAMING"
        or repositorio.endswith("/publicidadbot")
        or repositorio.endswith("/publicidadbot.git")
    )


def es_maximo_o_union_bot(bot) -> bool:
    nombre = str(bot["nombre"] or "").strip().upper()
    username = str(bot["username"] or "").strip().lower()
    repositorio = str(bot["repositorio"] or "").strip().lower()

    return (
        username in {
            "@maximocontrolgroup_bot",
            "@unionmembresia_bot",
        }
        or nombre in {
            "MAXIMO CONTROL GROUP",
            "MÁXIMO CONTROL GROUP",
            "MEMBRESÍA DE USUARIO",
            "MEMBRESIA DE USUARIO",
            "UNION MEMBRESIA",
            "UNIÓN MEMBRESÍA",
        }
        or repositorio.endswith("/maximocontrolgroup")
        or repositorio.endswith("/maximocontrolgroup.git")
    )



def es_membresias_consultas_denuncias_bot(bot) -> bool:
    nombre = str(bot["nombre"] or "").strip().upper()
    username = str(bot["username"] or "").strip().lower()
    repositorio = str(bot["repositorio"] or "").strip().lower()

    return (
        username == "@membresiaconsultasdenuncias_bot"
        or nombre in {
            "MEMBRESIAS CONSULTAS Y DENUNCIAS",
            "MEMBRESÍAS CONSULTAS Y DENUNCIAS",
            "MEMBRESIAS, CONSULTAS Y DENUNCIAS",
            "MEMBRESÍAS, CONSULTAS Y DENUNCIAS",
        }
        or repositorio.endswith("/membresiaconsultasdenunciasbot")
        or repositorio.endswith("/membresiaconsultasdenunciasbot.git")
    )


def obtener_configuracion_respaldo(bot) -> dict:
    if es_membresias_consultas_denuncias_bot(bot):
        return {
            "incluir_base": True,
            "agent_url": MEMBRESIAS_AGENT_URL,
            "agent_secret": MEMBRESIAS_AGENT_SECRET,
            "agent_timeout": MEMBRESIAS_AGENT_TIMEOUT,
            "git_branch": MEMBRESIAS_BACKUP_GIT_BRANCH,
            "db_filename": MEMBRESIAS_DB_FILENAME,
            "product_name": MEMBRESIAS_PRODUCT_NAME,
            "product_aliases": {
                MEMBRESIAS_PRODUCT_NAME.lower(),
                "membresiaconsultasdenunciasbot",
            },
        }

    if es_publicidad_bot(bot):
        return {
            "incluir_base": True,
            "agent_url": PUBLICIDAD_AGENT_URL,
            "agent_secret": PUBLICIDAD_AGENT_SECRET,
            "agent_timeout": PUBLICIDAD_AGENT_TIMEOUT,
            "git_branch": PUBLICIDAD_BACKUP_GIT_BRANCH,
            "db_filename": "publicidad.db",
            "product_name": "PublicidadBot",
            "product_aliases": {"publicidadbot"},
        }

    if es_maximo_o_union_bot(bot):
        return {
            "incluir_base": True,
            "agent_url": MAXIMO_AGENT_URL,
            "agent_secret": MAXIMO_AGENT_SECRET,
            "agent_timeout": MAXIMO_AGENT_TIMEOUT,
            "git_branch": MAXIMO_BACKUP_GIT_BRANCH,
            "db_filename": MAXIMO_DB_FILENAME,
            "product_name": MAXIMO_PRODUCT_NAME,
            "product_aliases": {
                MAXIMO_PRODUCT_NAME.lower(),
                "maximocontrolgroup",
            },
        }

    return {
        "incluir_base": False,
        "agent_url": "",
        "agent_secret": "",
        "agent_timeout": 180,
        "git_branch": "",
        "db_filename": "",
        "product_name": "",
        "product_aliases": set(),
    }


def _nombre_zip_seguro(nombre: str) -> bool:
    ruta = Path(nombre)
    return (
        bool(nombre)
        and not ruta.is_absolute()
        and ".." not in ruta.parts
        and "\\" not in nombre
    )


def descargar_base_remota(
    carpeta_temporal: Path,
    configuracion: dict,
) -> dict:
    agent_url = str(configuracion.get("agent_url") or "").rstrip("/")
    agent_secret = str(configuracion.get("agent_secret") or "").strip()
    agent_timeout = int(configuracion.get("agent_timeout") or 180)
    db_filename = str(configuracion.get("db_filename") or "").strip()
    product_name = str(configuracion.get("product_name") or "").strip()
    product_aliases = {
        str(valor).strip().lower()
        for valor in configuracion.get("product_aliases", set())
        if str(valor).strip()
    }

    if not agent_url:
        raise RuntimeError(
            f"Falta configurar la URL del agente remoto para {product_name or 'este bot'}."
        )

    if not agent_secret:
        raise RuntimeError(
            f"Falta configurar el secreto del agente remoto para {product_name or 'este bot'}."
        )

    if not db_filename:
        raise RuntimeError("No se configuró el nombre del archivo SQLite remoto.")

    ruta_zip = carpeta_temporal / f"{nombre_seguro(product_name)}_remota.zip"
    ruta_db = carpeta_temporal / db_filename

    solicitud = Request(
        f"{agent_url}/backup",
        data=b"",
        method="POST",
        headers={
            "Authorization": f"Bearer {agent_secret}",
            "User-Agent": "BotRespaldosPremium/4.1",
        },
    )

    try:
        with urlopen(
            solicitud,
            timeout=agent_timeout,
        ) as respuesta:
            estado = int(getattr(respuesta, "status", 200))
            if estado != 200:
                raise RuntimeError(
                    f"El agente remoto respondió HTTP {estado}."
                )

            longitud_texto = respuesta.headers.get(
                "Content-Length",
                "",
            ).strip()

            if longitud_texto:
                try:
                    longitud = int(longitud_texto)
                except ValueError:
                    longitud = 0

                if longitud > MAX_REMOTE_BACKUP_BYTES:
                    raise RuntimeError(
                        "El respaldo remoto supera el tamaño máximo permitido."
                    )

            recibidos = 0
            with ruta_zip.open("wb") as archivo:
                while True:
                    bloque = respuesta.read(1024 * 1024)
                    if not bloque:
                        break

                    recibidos += len(bloque)
                    if recibidos > MAX_REMOTE_BACKUP_BYTES:
                        raise RuntimeError(
                            "El respaldo remoto supera el tamaño máximo permitido."
                        )

                    archivo.write(bloque)

    except HTTPError as error:
        detalle = ""
        try:
            detalle = error.read().decode(
                "utf-8",
                errors="replace",
            )
        except Exception:
            detalle = ""

        raise RuntimeError(
            f"El agente remoto rechazó el respaldo "
            f"(HTTP {error.code}). {detalle}".strip()
        ) from error

    except URLError as error:
        raise RuntimeError(
            f"No se pudo conectar con el agente remoto: {error.reason}"
        ) from error

    if not zipfile.is_zipfile(ruta_zip):
        raise RuntimeError("El agente remoto no devolvió un ZIP válido.")

    with zipfile.ZipFile(ruta_zip, "r") as paquete:
        nombres = paquete.namelist()

        if any(not _nombre_zip_seguro(nombre) for nombre in nombres):
            raise RuntimeError("El respaldo remoto contiene rutas inseguras.")

        if db_filename not in nombres:
            raise RuntimeError(
                f"El respaldo remoto no contiene {db_filename}."
            )

        if "manifest.json" not in nombres:
            raise RuntimeError(
                "El respaldo remoto no contiene manifest.json."
            )

        try:
            manifest_remoto = json.loads(
                paquete.read("manifest.json").decode("utf-8-sig")
            )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as error:
            raise RuntimeError(
                f"El manifest remoto no es válido: {error}"
            ) from error

        producto = str(
            manifest_remoto.get("producto") or ""
        ).strip()

        if product_aliases and producto.lower() not in product_aliases:
            raise RuntimeError(
                f"El respaldo remoto pertenece a otro producto: "
                f"{producto or 'desconocido'}."
            )

        with paquete.open(
            db_filename,
            "r",
        ) as origen, ruta_db.open("wb") as destino:
            shutil.copyfileobj(
                origen,
                destino,
                length=1024 * 1024,
            )

    validar_sqlite(ruta_db)

    sha_real = calcular_sha256(ruta_db)
    sha_esperado = str(
        manifest_remoto.get("sha256") or ""
    ).strip().lower()

    if sha_esperado and not hmac.compare_digest(
        sha_esperado,
        sha_real.lower(),
    ):
        raise RuntimeError(
            f"El SHA-256 de {db_filename} no coincide con el manifest remoto."
        )

    tamano_esperado = manifest_remoto.get("tamano_bytes")
    if tamano_esperado is not None:
        try:
            tamano_esperado = int(tamano_esperado)
        except (TypeError, ValueError) as error:
            raise RuntimeError(
                "tamano_bytes del manifest remoto no es válido."
            ) from error

        if tamano_esperado != ruta_db.stat().st_size:
            raise RuntimeError(
                f"El tamaño de {db_filename} no coincide con el manifest remoto."
            )

    return {
        "ruta_db": ruta_db,
        "archivo_db": db_filename,
        "sha256": sha_real,
        "tamano_bytes": ruta_db.stat().st_size,
        "manifest": manifest_remoto,
        "url_agente": agent_url,
        "producto": product_name,
    }


def validar_codigo_respaldo(carpeta_repo: Path) -> None:
    obligatorios = (
        "bot.py",
        "agente_respaldo_remoto.py",
        "Dockerfile",
        "requirements.txt",
    )

    faltantes = [
        nombre
        for nombre in obligatorios
        if not (carpeta_repo / nombre).is_file()
    ]

    if faltantes:
        raise RuntimeError(
            "La rama seleccionada no contiene "
            "todos los archivos críticos. Faltan: "
            + ", ".join(faltantes)
        )



def crear_respaldo_bot(
    bot_id: int,
    tipo: str = "MANUAL",
) -> dict:
    bot = obtener_bot(bot_id)

    if not bot:
        return {
            "correcto": False,
            "mensaje": "No se encontró el bot registrado.",
        }

    try:
        repositorio = normalizar_repositorio(bot["repositorio"])
    except ValueError as error:
        return {
            "correcto": False,
            "mensaje": str(error),
        }

    nombre_bot = nombre_seguro(bot["nombre"])
    fecha_local = datetime.now(ZONA_PERU).strftime("%Y%m%d_%H%M%S")
    fecha_utc = datetime.now(timezone.utc).isoformat()

    carpeta_bot = BACKUPS_DIR / nombre_bot
    carpeta_bot.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    configuracion = obtener_configuracion_respaldo(bot)
    incluir_base_remota = bool(configuracion.get("incluir_base"))
    sufijo = "completo" if incluir_base_remota else "github"
    nombre_archivo = f"{nombre_bot}_{fecha_local}_{sufijo}.tar.gz"
    ruta_respaldo = carpeta_bot / nombre_archivo

    temporario_base = CACHE_DIR / f"{nombre_bot}_{fecha_local}"

    if temporario_base.exists():
        shutil.rmtree(temporario_base, ignore_errors=True)

    try:
        temporario_base.mkdir(parents=True, exist_ok=False)
        carpeta_repo = temporario_base / "repositorio"

        rama_respaldo = (
            configuracion.get("git_branch")
            if incluir_base_remota
            else None
        )

        datos_git = descargar_repositorio(
            repositorio,
            carpeta_repo,
            rama=rama_respaldo,
        )

        if incluir_base_remota:
            validar_codigo_respaldo(carpeta_repo)

        datos_base = None
        if incluir_base_remota:
            datos_base = descargar_base_remota(
                temporario_base,
                configuracion,
            )

        base_incluida = bool(datos_base)

        manifest = {
            "version_manifest": 2,
            "tipo_respaldo": (
                "CODIGO_GITHUB_Y_BASE_REMOTA"
                if base_incluida
                else "CODIGO_GITHUB"
            ),
            "fecha_utc": fecha_utc,
            "bot_id": int(bot_id),
            "bot_nombre": str(bot["nombre"] or ""),
            "bot_username": str(bot["username"] or ""),
            "servidor_origen": str(bot["servidor"] or ""),
            "repositorio": repositorio,
            "rama": datos_git.get("rama", ""),
            "rama_solicitada": datos_git.get("rama_solicitada", ""),
            "commit": datos_git.get("commit", ""),
            "base_datos_incluida": base_incluida,
            "archivo_base_datos": (
                datos_base["archivo_db"]
                if datos_base
                else None
            ),
            "sha256_base_datos": (
                datos_base["sha256"]
                if datos_base
                else None
            ),
            "tamano_base_datos_bytes": (
                datos_base["tamano_bytes"]
                if datos_base
                else None
            ),
            "agente_remoto": (
                datos_base["url_agente"]
                if datos_base
                else None
            ),
            "manifest_base_remota": (
                datos_base["manifest"]
                if datos_base
                else None
            ),
            "observacion": (
                "Este respaldo contiene el código descargado desde GitHub "
                f"y la base de datos activa {datos_base['archivo_db']} obtenida "
                "mediante el agente remoto de JustRunMy."
                if base_incluida
                else
                "Este respaldo contiene el código descargado desde GitHub."
            ),
        }

        ruta_manifest = crear_manifest(
            temporario_base,
            manifest,
        )

        archivos_codigo = 0
        archivos_totales = 0

        with tarfile.open(
            ruta_respaldo,
            mode="w:gz",
        ) as archivo_tar:
            archivos_codigo = agregar_directorio(
                archivo_tar,
                carpeta_repo,
                nombre_raiz="codigo",
            )
            archivos_totales += archivos_codigo

            if datos_base:
                archivo_tar.add(
                    datos_base["ruta_db"],
                    arcname=datos_base["archivo_db"],
                    recursive=False,
                )
                archivos_totales += 1

            archivo_tar.add(
                ruta_manifest,
                arcname="manifest.json",
                recursive=False,
            )
            archivos_totales += 1

        if archivos_codigo <= 0:
            ruta_respaldo.unlink(missing_ok=True)

            return {
                "correcto": False,
                "mensaje": (
                    "El repositorio fue descargado, pero no contenía "
                    "archivos válidos para respaldar."
                ),
            }

        tamano_bytes = ruta_respaldo.stat().st_size
        sha256 = calcular_sha256(ruta_respaldo)

        observacion = (
            f"Respaldo remoto completo. "
            f"Repositorio: {repositorio}. "
            f"Rama: {datos_git.get('rama') or 'desconocida'}. "
            f"Commit: {datos_git.get('commit') or 'desconocido'}. "
            f"Archivos de código: {archivos_codigo}. "
            f"Base de datos "
            f"{datos_base['archivo_db'] if datos_base else 'no configurada'} "
            f"incluida: {'sí' if base_incluida else 'no'}."
        )

        respaldo_id = registrar_respaldo(
            bot_id=int(bot_id),
            archivo=nombre_archivo,
            ruta=str(ruta_respaldo),
            tipo=str(tipo).upper(),
            estado="CREADO",
            tamano_bytes=tamano_bytes,
            sha256=sha256,
            observacion=observacion,
        )

        return {
            "correcto": True,
            "mensaje": (
                "Respaldo completo de código y base remota creado correctamente."
                if base_incluida
                else
                "Respaldo del código GitHub creado correctamente."
            ),
            "respaldo_id": respaldo_id,
            "archivo": nombre_archivo,
            "ruta": str(ruta_respaldo),
            "tamano_bytes": tamano_bytes,
            "sha256": sha256,
            "archivos_agregados": archivos_totales,
            "archivos_codigo": archivos_codigo,
            "base_incluida": base_incluida,
            "repositorio": repositorio,
            "rama": datos_git.get("rama", ""),
            "commit": datos_git.get("commit", ""),
            "tipo_respaldo": manifest["tipo_respaldo"],
            "sha256_base_datos": (
                datos_base["sha256"]
                if datos_base
                else ""
            ),
            "tamano_base_datos_bytes": (
                datos_base["tamano_bytes"]
                if datos_base
                else 0
            ),
        }

    except subprocess.TimeoutExpired:
        ruta_respaldo.unlink(missing_ok=True)

        return {
            "correcto": False,
            "mensaje": (
                "GitHub tardó demasiado en responder. "
                "Intenta crear el respaldo nuevamente."
            ),
        }

    except (
        OSError,
        PermissionError,
        RuntimeError,
        tarfile.TarError,
        zipfile.BadZipFile,
    ) as error:
        ruta_respaldo.unlink(missing_ok=True)

        return {
            "correcto": False,
            "mensaje": f"No se pudo crear el respaldo remoto: {error}",
        }

    finally:
        shutil.rmtree(
            temporario_base,
            ignore_errors=True,
        )


def formatear_tamano(tamano_bytes: Optional[int]) -> str:
    tamano = float(tamano_bytes or 0)

    unidades = [
        "B",
        "KB",
        "MB",
        "GB",
        "TB",
    ]

    for unidad in unidades:
        if tamano < 1024 or unidad == unidades[-1]:
            if unidad == "B":
                return f"{int(tamano)} {unidad}"

            return f"{tamano:.2f} {unidad}"

        tamano /= 1024

    return f"{int(tamano_bytes or 0)} B"


# =========================================================
# RESPALDOS POR FUENTE + IMPORTACIÓN EXTERNA
# =========================================================

def _manifest_identidad_coincide(manifest: dict, bot) -> bool:
    if not manifest or not bot:
        return False

    try:
        if manifest.get("bot_id") is not None and int(manifest.get("bot_id")) == int(bot["id"]):
            return True
    except (TypeError, ValueError):
        pass

    username_manifest = str(manifest.get("bot_username") or "").strip().lower()
    username_bot = str(bot["username"] or "").strip().lower()
    if username_manifest and username_bot and username_manifest == username_bot:
        return True

    nombre_manifest = str(manifest.get("bot_nombre") or "").strip().casefold()
    nombre_bot = str(bot["nombre"] or "").strip().casefold()
    if nombre_manifest and nombre_bot and nombre_manifest == nombre_bot:
        return True

    return False


def inspeccionar_archivo_externo(ruta: Path, bot) -> dict:
    ruta = Path(ruta)
    if not ruta.is_file():
        raise RuntimeError("El archivo externo no existe.")
    if ruta.stat().st_size <= 0:
        raise RuntimeError("El archivo externo está vacío.")
    if ruta.stat().st_size > MAX_EXTERNAL_BACKUP_BYTES:
        raise RuntimeError("El archivo externo supera el tamaño máximo permitido.")
    if not tarfile.is_tarfile(ruta):
        raise RuntimeError("Solo se admiten respaldos TAR compatibles (.tar.gz).")

    with tarfile.open(ruta, "r:*") as paquete:
        miembros = paquete.getmembers()
        if not miembros:
            raise RuntimeError("El respaldo externo está vacío.")
        for miembro in miembros:
            nombre = miembro.name
            path = Path(nombre)
            if path.is_absolute() or ".." in path.parts or "\\" in nombre:
                raise RuntimeError("El respaldo externo contiene rutas inseguras.")

        nombres = {m.name for m in miembros if m.isfile()}
        codigo = sorted(n for n in nombres if n.startswith("codigo/"))
        if not codigo:
            raise RuntimeError(
                "El respaldo externo no contiene codigo/. "
                "Para auto-restauración debe ser un paquete completo compatible."
            )

        if "manifest.json" not in nombres:
            raise RuntimeError("El respaldo externo no contiene manifest.json.")

        archivo_manifest = paquete.extractfile("manifest.json")
        if not archivo_manifest:
            raise RuntimeError("No se pudo leer manifest.json.")
        try:
            manifest = json.loads(archivo_manifest.read().decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RuntimeError(f"manifest.json no es válido: {error}") from error

    if not _manifest_identidad_coincide(manifest, bot):
        raise RuntimeError(
            "El respaldo externo no corresponde al bot seleccionado. "
            "Se canceló la importación para evitar una restauración cruzada."
        )

    return {
        "manifest": manifest,
        "archivos_codigo": codigo,
        "sha256": calcular_sha256(ruta),
        "tamano_bytes": ruta.stat().st_size,
    }


def importar_respaldo_externo(bot_id: int, ruta_origen: str, nombre_original: str) -> dict:
    bot = obtener_bot(int(bot_id))
    if not bot:
        return {"correcto": False, "mensaje": "El bot seleccionado no existe."}

    origen = Path(ruta_origen)
    try:
        info = inspeccionar_archivo_externo(origen, bot)
        nombre_bot = nombre_seguro(bot["nombre"])
        carpeta = BACKUPS_DIR / nombre_bot / "externos"
        carpeta.mkdir(parents=True, exist_ok=True)
        nombre = f"{nombre_bot}_{sello_peru()}_externo.tar.gz"
        destino = carpeta / nombre
        shutil.copy2(origen, destino)
        sha256 = calcular_sha256(destino)

        respaldo_id = registrar_respaldo(
            bot_id=int(bot_id),
            archivo=nombre,
            ruta=str(destino),
            tipo="EXTERNO",
            estado="VALIDADO",
            tamano_bytes=destino.stat().st_size,
            sha256=sha256,
            observacion=(
                f"Respaldo externo importado desde Telegram. "
                f"Nombre original: {nombre_original}. "
                f"Validado para auto-restauración. "
                f"Archivos de código: {len(info['archivos_codigo'])}."
            ),
        )
        return {
            "correcto": True,
            "respaldo_id": respaldo_id,
            "archivo": nombre,
            "ruta": str(destino),
            "sha256": sha256,
            "tamano_bytes": destino.stat().st_size,
            "archivos_codigo": len(info["archivos_codigo"]),
            "manifest": info["manifest"],
        }
    except Exception as error:
        return {"correcto": False, "mensaje": str(error)}


def _registrar_paquete_fuente(bot, ruta: Path, tipo: str, observacion: str, archivos: int, base_incluida: bool = False) -> dict:
    sha256 = calcular_sha256(ruta)
    respaldo_id = registrar_respaldo(
        bot_id=int(bot["id"]),
        archivo=ruta.name,
        ruta=str(ruta),
        tipo=tipo,
        estado="DISPONIBLE",
        tamano_bytes=ruta.stat().st_size,
        sha256=sha256,
        observacion=observacion,
    )
    return {
        "correcto": True,
        "respaldo_id": respaldo_id,
        "archivo": ruta.name,
        "ruta": str(ruta),
        "tamano_bytes": ruta.stat().st_size,
        "sha256": sha256,
        "archivos_agregados": int(archivos),
        "base_incluida": bool(base_incluida),
    }


def crear_respaldo_fuente_github(bot_id: int) -> dict:
    bot = obtener_bot(int(bot_id))
    if not bot:
        return {"correcto": False, "mensaje": "El bot no existe."}
    try:
        repositorio = normalizar_repositorio(bot["repositorio"])
        nombre_bot = nombre_seguro(bot["nombre"])
        sello = sello_peru()
        carpeta_bot = BACKUPS_DIR / nombre_bot / "fuentes"
        carpeta_bot.mkdir(parents=True, exist_ok=True)
        temporal = Path(tempfile.mkdtemp(prefix="fuente_github_", dir=str(CACHE_DIR if CACHE_DIR.exists() else BASE_DIR)))
        try:
            repo = temporal / "repositorio"
            datos_git = descargar_repositorio(repositorio, repo)
            manifest = {
                "version_manifest": 3,
                "tipo_respaldo": "AUDITORIA_GITHUB",
                "origen": "GITHUB",
                "fecha_peru": fecha_peru_iso(),
                "bot_id": int(bot["id"]),
                "bot_nombre": str(bot["nombre"] or ""),
                "bot_username": str(bot["username"] or ""),
                "repositorio": repositorio,
                "rama": datos_git.get("rama", ""),
                "commit": datos_git.get("commit", ""),
                "base_datos_incluida": False,
                "uso_recomendado": "AUDITORIA_MEJORAS_CODIGO",
            }
            ruta_manifest = crear_manifest(temporal, manifest)
            ruta = carpeta_bot / f"{nombre_bot}_{sello}_github.tar.gz"
            with tarfile.open(ruta, "w:gz") as tar:
                cantidad = agregar_directorio(tar, repo, "codigo")
                tar.add(ruta_manifest, arcname="manifest.json", recursive=False)
            if cantidad <= 0:
                ruta.unlink(missing_ok=True)
                raise RuntimeError("GitHub no devolvió archivos válidos.")
            return _registrar_paquete_fuente(
                bot, ruta, "FUENTE_GITHUB",
                f"Copia individual de GitHub para auditoría/mejoras. Rama {datos_git.get('rama') or 'desconocida'}, commit {datos_git.get('commit') or 'desconocido'}.",
                cantidad + 1,
            )
        finally:
            shutil.rmtree(temporal, ignore_errors=True)
    except Exception as error:
        return {"correcto": False, "mensaje": str(error)}



def resolver_agente_remoto_bot(bot) -> dict:
    cfg = obtener_configuracion_recuperacion(bot) or {}
    if cfg.get("agent_url") and cfg.get("agent_secret"):
        return cfg

    base = _normalizar_nombre_oracle(bot["nombre"]).upper()
    username = _normalizar_nombre_oracle(bot["username"]).upper()
    candidatos = []
    for prefijo in {base, username}:
        if not prefijo:
            continue
        candidatos.extend([
            (f"{prefijo}_AGENT_URL", f"{prefijo}_AGENT_SECRET"),
            (f"{prefijo}_URL", f"{prefijo}_SECRET"),
        ])

    # Convenciones históricas conocidas del proyecto.
    nombre_normalizado = _normalizar_nombre_oracle(bot["nombre"])
    if "membresiaconsultasdenuncias" in nombre_normalizado:
        candidatos.insert(0, ("MEMBRESIAS_AGENT_URL", "MEMBRESIAS_AGENT_SECRET"))
    if "publicidadcontrolstreaming" in nombre_normalizado:
        candidatos.insert(0, ("PUBLICIDAD_AGENT_URL", "PUBLICIDAD_AGENT_SECRET"))

    for clave_url, clave_secret in candidatos:
        url = os.environ.get(clave_url, "").strip()
        secret = os.environ.get(clave_secret, "").strip()
        if url and secret:
            nuevo = dict(cfg)
            nuevo["agent_url"] = url
            nuevo["agent_secret"] = secret
            return nuevo

    return cfg


def crear_respaldo_fuente_justrunmy(bot_id: int) -> dict:
    bot = obtener_bot(int(bot_id))
    if not bot:
        return {"correcto": False, "mensaje": "El bot no existe."}
    configuracion = obtener_configuracion_respaldo(bot)
    if not configuracion.get("incluir_base"):
        return {
            "correcto": False,
            "mensaje": "Este bot todavía no tiene agente de respaldo JustRunMy configurado.",
        }
    temporal = Path(tempfile.mkdtemp(prefix="fuente_jrm_", dir=str(BASE_DIR)))
    try:
        datos_base = descargar_base_remota(temporal, configuracion)
        nombre_bot = nombre_seguro(bot["nombre"])
        carpeta_bot = BACKUPS_DIR / nombre_bot / "fuentes"
        carpeta_bot.mkdir(parents=True, exist_ok=True)
        manifest = {
            "version_manifest": 3,
            "tipo_respaldo": "AUDITORIA_JUSTRUNMY",
            "origen": "JUSTRUNMY",
            "fecha_peru": fecha_peru_iso(),
            "bot_id": int(bot["id"]),
            "bot_nombre": str(bot["nombre"] or ""),
            "bot_username": str(bot["username"] or ""),
            "base_datos_incluida": True,
            "archivo_base_datos": datos_base["archivo_db"],
            "sha256_base_datos": datos_base["sha256"],
            "agente_remoto": datos_base["url_agente"],
            "manifest_base_remota": datos_base["manifest"],
            "uso_recomendado": "AUDITORIA_BASE_DATOS",
        }
        ruta_manifest = crear_manifest(temporal, manifest)
        ruta = carpeta_bot / f"{nombre_bot}_{sello_peru()}_justrunmy.tar.gz"
        with tarfile.open(ruta, "w:gz") as tar:
            tar.add(datos_base["ruta_db"], arcname=datos_base["archivo_db"], recursive=False)
            tar.add(ruta_manifest, arcname="manifest.json", recursive=False)
        return _registrar_paquete_fuente(
            bot, ruta, "FUENTE_JUSTRUNMY",
            f"Copia individual de JustRunMy para auditoría de base activa {datos_base['archivo_db']}.",
            2, True,
        )
    except Exception as error:
        return {"correcto": False, "mensaje": str(error)}
    finally:
        shutil.rmtree(temporal, ignore_errors=True)



ORACLE_PROJECT_ALIASES = {
    "publicidadcontrolstreamingbot": ["/opt/PublicidadBot"],
    "publicidadcontrolstreaming": ["/opt/PublicidadBot"],
    "maximocontrolgroupbot": ["/opt/MaximoControlGroup"],
    "maximocontrolgroup": ["/opt/MaximoControlGroup"],
    "botrespaldospremium": ["/opt/RecoveryControlBot"],
    "recoverycontrolbot": ["/opt/RecoveryControlBot"],
}


def _normalizar_nombre_oracle(valor: str) -> str:
    texto = unicodedata.normalize("NFKD", str(valor or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return "".join(c.lower() for c in texto if c.isalnum())


def resolver_proyecto_oracle(bot):
    """
    Resuelve de forma conservadora la carpeta real del proyecto en este Oracle.

    Prioridad:
    1) ruta_proyecto registrada y existente;
    2) coincidencia exacta en /opt usando nombre del repo, username o nombre del bot.

    Nunca selecciona una ruta ambigua por aproximación.
    """
    ruta_registrada = Path(str(bot["ruta_proyecto"] or "").strip())
    if ruta_registrada.is_absolute() and ruta_registrada.is_dir():
        return ruta_registrada

    alias_tokens = {
        _normalizar_nombre_oracle(bot["nombre"]),
        _normalizar_nombre_oracle(bot["username"]),
    }
    for token in list(alias_tokens):
        for ruta_alias in ORACLE_PROJECT_ALIASES.get(token, []):
            candidato = Path(ruta_alias)
            if candidato.is_dir():
                return candidato

    tokens = set()

    repo = str(bot["repositorio"] or "").strip().rstrip("/")
    if repo:
        base_repo = repo.split("/")[-1]
        if base_repo.endswith(".git"):
            base_repo = base_repo[:-4]
        if base_repo:
            tokens.add(_normalizar_nombre_oracle(base_repo))

    username = str(bot["username"] or "").strip().lstrip("@")
    if username:
        tokens.add(_normalizar_nombre_oracle(username))
        if username.lower().endswith("_bot"):
            tokens.add(_normalizar_nombre_oracle(username[:-4]))

    nombre = str(bot["nombre"] or "").strip()
    if nombre:
        tokens.add(_normalizar_nombre_oracle(nombre))

    if ruta_registrada.name:
        tokens.add(_normalizar_nombre_oracle(ruta_registrada.name))

    tokens.discard("")
    if not tokens:
        return None

    raiz = Path("/opt")
    if not raiz.is_dir():
        return None

    candidatos = []
    for carpeta in raiz.iterdir():
        if not carpeta.is_dir():
            continue
        nombre_norm = _normalizar_nombre_oracle(carpeta.name)
        if nombre_norm not in tokens:
            continue
        # Exigimos señales mínimas de proyecto para no empaquetar una carpeta arbitraria.
        if not (
            (carpeta / "bot.py").is_file()
            or (carpeta / "Dockerfile").is_file()
            or (carpeta / ".git").exists()
            or any(carpeta.glob("*.py"))
        ):
            continue
        candidatos.append(carpeta)

    if len(candidatos) == 1:
        return candidatos[0]

    return None


def estado_fuente_oracle(bot_id: int) -> dict:
    bot = obtener_bot(int(bot_id))
    if not bot:
        return {"disponible": False, "ruta": "", "mensaje": "Bot no encontrado."}
    proyecto = resolver_proyecto_oracle(bot)
    if not proyecto:
        return {
            "disponible": False,
            "ruta": "",
            "mensaje": "No existe una ruta Oracle válida y única para este bot.",
        }
    return {
        "disponible": True,
        "ruta": str(proyecto),
        "mensaje": "Proyecto Oracle localizado.",
    }


def crear_respaldo_fuente_oracle(bot_id: int) -> dict:
    bot = obtener_bot(int(bot_id))
    if not bot:
        return {"correcto": False, "mensaje": "El bot no existe."}
    proyecto = resolver_proyecto_oracle(bot)
    if not proyecto:
        return {
            "correcto": False,
            "mensaje": (
                "No se encontró una ruta Oracle válida y única para este bot. "
                "Registra la ruta real del proyecto o verifica que exista en /opt."
            ),
        }
    nombre_bot = nombre_seguro(bot["nombre"])
    carpeta_bot = BACKUPS_DIR / nombre_bot / "fuentes"
    carpeta_bot.mkdir(parents=True, exist_ok=True)
    temporal = Path(tempfile.mkdtemp(prefix="fuente_oracle_", dir=str(BASE_DIR)))
    try:
        ruta_db = Path(str(bot["ruta_base_datos"] or "").strip()) if str(bot["ruta_base_datos"] or "").strip() else None
        base_incluida = bool(ruta_db and ruta_db.is_absolute() and ruta_db.is_file())
        manifest = {
            "version_manifest": 3,
            "tipo_respaldo": "AUDITORIA_ORACLE",
            "origen": "ORACLE",
            "fecha_peru": fecha_peru_iso(),
            "bot_id": int(bot["id"]),
            "bot_nombre": str(bot["nombre"] or ""),
            "bot_username": str(bot["username"] or ""),
            "servidor_origen": str(bot["servidor"] or ""),
            "ruta_proyecto": str(proyecto),
            "base_datos_incluida": base_incluida,
            "archivo_base_datos": ruta_db.name if base_incluida else None,
            "uso_recomendado": "AUDITORIA_ESTADO_ORACLE",
        }
        ruta_manifest = crear_manifest(temporal, manifest)
        ruta = carpeta_bot / f"{nombre_bot}_{sello_peru()}_oracle.tar.gz"
        with tarfile.open(ruta, "w:gz") as tar:
            cantidad = agregar_directorio(tar, proyecto, "codigo")
            if base_incluida:
                tar.add(ruta_db, arcname=ruta_db.name, recursive=False)
                cantidad += 1
            tar.add(ruta_manifest, arcname="manifest.json", recursive=False)
            cantidad += 1
        return _registrar_paquete_fuente(
            bot, ruta, "FUENTE_ORACLE",
            f"Copia individual del estado local en Oracle: {proyecto}. Base incluida: {'sí' if base_incluida else 'no'}.",
            cantidad, base_incluida,
        )
    except Exception as error:
        return {"correcto": False, "mensaje": str(error)}
    finally:
        shutil.rmtree(temporal, ignore_errors=True)
