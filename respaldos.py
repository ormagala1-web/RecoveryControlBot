import hashlib
import json
import shutil
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from database import obtener_bot, registrar_respaldo


BASE_DIR = Path(__file__).resolve().parent
BACKUPS_DIR = BASE_DIR / "backups"
CACHE_DIR = BASE_DIR / "cache_repositorios"

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
) -> dict:
    resultado = ejecutar_git(
        [
            "clone",
            "--depth",
            "1",
            "--single-branch",
            f"{repositorio}.git",
            str(destino),
        ]
    )

    if resultado.returncode != 0:
        detalle = (
            resultado.stderr.strip()
            or resultado.stdout.strip()
            or "Git no proporcionó detalles."
        )
        raise RuntimeError(
            "No se pudo descargar el repositorio desde GitHub. "
            f"Detalle: {detalle}"
        )

    commit = ejecutar_git(
        ["rev-parse", "HEAD"],
        cwd=destino,
    )
    rama = ejecutar_git(
        ["rev-parse", "--abbrev-ref", "HEAD"],
        cwd=destino,
    )

    return {
        "commit": commit.stdout.strip() if commit.returncode == 0 else "",
        "rama": rama.stdout.strip() if rama.returncode == 0 else "",
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
    fecha_local = datetime.now().strftime("%Y%m%d_%H%M%S")
    fecha_utc = datetime.now(timezone.utc).isoformat()

    carpeta_bot = BACKUPS_DIR / nombre_bot
    carpeta_bot.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    nombre_archivo = f"{nombre_bot}_{fecha_local}_github.tar.gz"
    ruta_respaldo = carpeta_bot / nombre_archivo

    temporario_base = CACHE_DIR / f"{nombre_bot}_{fecha_local}"

    if temporario_base.exists():
        shutil.rmtree(temporario_base, ignore_errors=True)

    try:
        temporario_base.mkdir(parents=True, exist_ok=False)
        carpeta_repo = temporario_base / "repositorio"

        datos_git = descargar_repositorio(
            repositorio,
            carpeta_repo,
        )

        manifest = {
            "version_manifest": 1,
            "tipo_respaldo": "CODIGO_GITHUB",
            "fecha_utc": fecha_utc,
            "bot_id": int(bot_id),
            "bot_nombre": str(bot["nombre"] or ""),
            "bot_username": str(bot["username"] or ""),
            "servidor_origen": str(bot["servidor"] or ""),
            "repositorio": repositorio,
            "rama": datos_git.get("rama", ""),
            "commit": datos_git.get("commit", ""),
            "base_datos_incluida": False,
            "observacion": (
                "Este respaldo contiene el código descargado desde GitHub. "
                "La base de datos activa alojada en JustRunMy se integrará "
                "mediante el módulo remoto de datos."
            ),
        }

        ruta_manifest = crear_manifest(
            temporario_base,
            manifest,
        )

        archivos_agregados = 0

        with tarfile.open(
            ruta_respaldo,
            mode="w:gz",
        ) as archivo_tar:
            archivos_agregados += agregar_directorio(
                archivo_tar,
                carpeta_repo,
                nombre_raiz="codigo",
            )

            archivo_tar.add(
                ruta_manifest,
                arcname="manifest.json",
                recursive=False,
            )
            archivos_agregados += 1

        if archivos_agregados <= 1:
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

        respaldo_id = registrar_respaldo(
            bot_id=int(bot_id),
            archivo=nombre_archivo,
            ruta=str(ruta_respaldo),
            tipo=str(tipo).upper(),
            estado="CREADO",
            tamano_bytes=tamano_bytes,
            sha256=sha256,
            observacion=(
                f"Respaldo remoto de código GitHub. "
                f"Repositorio: {repositorio}. "
                f"Rama: {datos_git.get('rama') or 'desconocida'}. "
                f"Commit: {datos_git.get('commit') or 'desconocido'}. "
                f"Archivos incluidos: {archivos_agregados - 1}. "
                "Base de datos activa de JustRunMy: pendiente."
            ),
        )

        return {
            "correcto": True,
            "mensaje": "Respaldo del código GitHub creado correctamente.",
            "respaldo_id": respaldo_id,
            "archivo": nombre_archivo,
            "ruta": str(ruta_respaldo),
            "tamano_bytes": tamano_bytes,
            "sha256": sha256,
            "archivos_agregados": archivos_agregados - 1,
            "base_incluida": False,
            "repositorio": repositorio,
            "rama": datos_git.get("rama", ""),
            "commit": datos_git.get("commit", ""),
            "tipo_respaldo": "CODIGO_GITHUB",
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
