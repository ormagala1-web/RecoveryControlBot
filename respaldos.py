import hashlib
import os
import tarfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from database import obtener_bot, registrar_respaldo


BASE_DIR = Path(__file__).resolve().parent
BACKUPS_DIR = BASE_DIR / "backups"

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


def calcular_sha256(ruta_archivo: Path) -> str:
    sha256 = hashlib.sha256()

    with ruta_archivo.open("rb") as archivo:
        while True:
            bloque = archivo.read(1024 * 1024)

            if not bloque:
                break

            sha256.update(bloque)

    return sha256.hexdigest()


def agregar_directorio(
    archivo_tar: tarfile.TarFile,
    ruta_origen: Path,
    nombre_raiz: str,
) -> int:
    archivos_agregados = 0

    for raiz, carpetas, archivos in os.walk(
        ruta_origen,
        topdown=True,
        followlinks=False,
    ):
        raiz_path = Path(raiz)

        carpetas[:] = [
            carpeta
            for carpeta in carpetas
            if carpeta not in CARPETAS_EXCLUIDAS
            and not (raiz_path / carpeta).is_symlink()
        ]

        for nombre_archivo in archivos:
            ruta_archivo = raiz_path / nombre_archivo

            if ruta_archivo.suffix.lower() in EXTENSIONES_EXCLUIDAS:
                continue

            if ruta_archivo.is_symlink():
                continue

            try:
                ruta_relativa = ruta_archivo.relative_to(ruta_origen)
                ruta_interna = Path(nombre_raiz) / ruta_relativa

                archivo_tar.add(
                    ruta_archivo,
                    arcname=str(ruta_interna),
                    recursive=False,
                )

                archivos_agregados += 1

            except (OSError, PermissionError):
                continue

    return archivos_agregados


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

    ruta_proyecto_texto = str(
        bot["ruta_proyecto"] or ""
    ).strip()

    if not ruta_proyecto_texto:
        return {
            "correcto": False,
            "mensaje": "El bot no tiene configurada la ruta del proyecto.",
        }

    ruta_proyecto = Path(ruta_proyecto_texto)

    if not ruta_proyecto.exists():
        return {
            "correcto": False,
            "mensaje": (
                "La ruta del proyecto no existe en este servidor:\n"
                f"{ruta_proyecto}"
            ),
        }

    if not ruta_proyecto.is_dir():
        return {
            "correcto": False,
            "mensaje": (
                "La ruta configurada no es una carpeta:\n"
                f"{ruta_proyecto}"
            ),
        }

    nombre_bot = nombre_seguro(bot["nombre"])
    fecha = datetime.now().strftime("%Y%m%d_%H%M%S")

    carpeta_bot = BACKUPS_DIR / nombre_bot
    carpeta_bot.mkdir(parents=True, exist_ok=True)

    nombre_archivo = f"{nombre_bot}_{fecha}.tar.gz"
    ruta_respaldo = carpeta_bot / nombre_archivo

    ruta_base_texto = str(
        bot["ruta_base_datos"] or ""
    ).strip()

    ruta_base: Optional[Path] = (
        Path(ruta_base_texto)
        if ruta_base_texto
        else None
    )

    archivos_agregados = 0
    base_incluida = False

    try:
        with tarfile.open(
            ruta_respaldo,
            mode="w:gz",
        ) as archivo_tar:
            archivos_agregados += agregar_directorio(
                archivo_tar,
                ruta_proyecto,
                nombre_raiz="proyecto",
            )

            if (
                ruta_base
                and ruta_base.exists()
                and ruta_base.is_file()
            ):
                try:
                    ruta_base.relative_to(ruta_proyecto)
                    base_incluida = True

                except ValueError:
                    archivo_tar.add(
                        ruta_base,
                        arcname=(
                            f"base_datos_externa/"
                            f"{ruta_base.name}"
                        ),
                        recursive=False,
                    )

                    archivos_agregados += 1
                    base_incluida = True

        if archivos_agregados == 0:
            ruta_respaldo.unlink(missing_ok=True)

            return {
                "correcto": False,
                "mensaje": (
                    "No se encontraron archivos válidos "
                    "para incluir en el respaldo."
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
                f"Archivos incluidos: {archivos_agregados}. "
                f"Base de datos incluida: "
                f"{'Sí' if base_incluida else 'No'}."
            ),
        )

        return {
            "correcto": True,
            "mensaje": "Respaldo creado correctamente.",
            "respaldo_id": respaldo_id,
            "archivo": nombre_archivo,
            "ruta": str(ruta_respaldo),
            "tamano_bytes": tamano_bytes,
            "sha256": sha256,
            "archivos_agregados": archivos_agregados,
            "base_incluida": base_incluida,
        }

    except (OSError, PermissionError, tarfile.TarError) as error:
        ruta_respaldo.unlink(missing_ok=True)

        return {
            "correcto": False,
            "mensaje": f"No se pudo crear el respaldo: {error}",
        }


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
