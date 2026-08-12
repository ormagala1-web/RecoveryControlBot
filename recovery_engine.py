import compileall
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import time
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


MAX_CODIGO_BYTES = int(
    os.getenv("RECOVERY_MAX_CODE_BYTES", str(250 * 1024 * 1024))
)
GIT_TIMEOUT = int(os.getenv("RECOVERY_GIT_TIMEOUT", "600"))
HEALTH_TIMEOUT = int(os.getenv("RECOVERY_HEALTH_TIMEOUT", "600"))
HEALTH_INTERVAL = int(os.getenv("RECOVERY_HEALTH_INTERVAL", "10"))


def _sha256_archivo(ruta: Path) -> str:
    digest = hashlib.sha256()
    with ruta.open("rb") as archivo:
        for bloque in iter(lambda: archivo.read(1024 * 1024), b""):
            digest.update(bloque)
    return digest.hexdigest()


def _ruta_segura(nombre: str) -> bool:
    ruta = Path(nombre)
    return (
        bool(nombre)
        and not ruta.is_absolute()
        and ".." not in ruta.parts
        and "\\" not in nombre
    )


def _ejecutar(
    argumentos: list[str],
    cwd: Optional[Path] = None,
    timeout: int = GIT_TIMEOUT,
) -> subprocess.CompletedProcess:
    proceso = subprocess.run(
        argumentos,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
        env={
            **os.environ,
            "GIT_TERMINAL_PROMPT": "0",
        },
    )
    if proceso.returncode != 0:
        detalle = (
            proceso.stderr.strip()
            or proceso.stdout.strip()
            or "El proceso no proporcionó detalles."
        )
        raise RuntimeError(
            f"Falló {' '.join(argumentos[:2])}: {detalle}"
        )
    return proceso


def _extraer_codigo(
    ruta_respaldo: Path,
    destino: Path,
) -> tuple[dict, list[str]]:
    if not tarfile.is_tarfile(ruta_respaldo):
        raise RuntimeError("El respaldo no es un archivo TAR compatible.")

    total = 0
    archivos: list[str] = []
    manifest: dict = {}

    with tarfile.open(ruta_respaldo, "r:*") as paquete:
        miembros = paquete.getmembers()
        if not miembros:
            raise RuntimeError("El respaldo está vacío.")

        for miembro in miembros:
            if not _ruta_segura(miembro.name):
                raise RuntimeError(
                    f"Ruta insegura dentro del respaldo: {miembro.name}"
                )
            if miembro.issym() or miembro.islnk():
                raise RuntimeError(
                    "El respaldo contiene enlaces simbólicos no permitidos."
                )
            if miembro.isfile():
                total += int(miembro.size or 0)
                if total > MAX_CODIGO_BYTES:
                    raise RuntimeError(
                        "El código del respaldo supera el tamaño máximo permitido."
                    )

        nombres = {m.name.lstrip("./"): m for m in miembros if m.isfile()}
        manifest_member = nombres.get("manifest.json")
        if manifest_member:
            archivo = paquete.extractfile(manifest_member)
            if archivo:
                try:
                    manifest = json.loads(
                        archivo.read().decode("utf-8-sig")
                    )
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise RuntimeError(
                        f"manifest.json no es válido: {error}"
                    ) from error

        codigo = [
            m for m in miembros
            if m.isfile() and m.name.lstrip("./").startswith("codigo/")
        ]
        if not codigo:
            raise RuntimeError(
                "El respaldo no contiene archivos dentro de codigo/."
            )

        destino.mkdir(parents=True, exist_ok=True)
        for miembro in codigo:
            nombre = miembro.name.lstrip("./")
            relativo = Path(nombre).relative_to("codigo")
            ruta_salida = destino / relativo
            ruta_salida.parent.mkdir(parents=True, exist_ok=True)

            origen = paquete.extractfile(miembro)
            if origen is None:
                raise RuntimeError(
                    f"No se pudo extraer {nombre}."
                )
            with ruta_salida.open("wb") as salida:
                shutil.copyfileobj(origen, salida, length=1024 * 1024)
            archivos.append(str(relativo))

    return manifest, archivos


def _validar_codigo(carpeta_codigo: Path) -> None:
    bot_py = carpeta_codigo / "bot.py"
    if not bot_py.is_file():
        raise RuntimeError("El respaldo no contiene codigo/bot.py.")

    if not compileall.compile_dir(
        str(carpeta_codigo),
        quiet=1,
        force=True,
    ):
        raise RuntimeError(
            "El código recuperado no superó la compilación de Python."
        )

    texto_bot = bot_py.read_text(encoding="utf-8-sig")
    agente = carpeta_codigo / "agente_respaldo_remoto.py"

    if not agente.is_file():
        raise RuntimeError(
            "El código restaurable no incluye agente_respaldo_remoto.py. "
            "Se cancela para no perder /health, /backup y /restore."
        )

    if "iniciar_agente_respaldo" not in texto_bot:
        raise RuntimeError(
            "bot.py no contiene la integración del agente remoto."
        )

    py_compile = subprocess.run(
        [os.sys.executable, "-m", "py_compile", str(agente)],
        capture_output=True,
        text=True,
        check=False,
    )
    if py_compile.returncode != 0:
        raise RuntimeError(
            "agente_respaldo_remoto.py no compila: "
            + (py_compile.stderr.strip() or "error desconocido")
        )


def _preparar_git(carpeta_codigo: Path, mensaje: str) -> None:
    git_dir = carpeta_codigo / ".git"
    if git_dir.exists():
        shutil.rmtree(git_dir, ignore_errors=True)

    _ejecutar(["git", "init"], cwd=carpeta_codigo)
    _ejecutar(
        ["git", "config", "user.name", "Bot Respaldos Premium"],
        cwd=carpeta_codigo,
    )
    _ejecutar(
        ["git", "config", "user.email", "recovery@localhost"],
        cwd=carpeta_codigo,
    )
    _ejecutar(["git", "add", "-A"], cwd=carpeta_codigo)
    _ejecutar(
        ["git", "commit", "-m", mensaje],
        cwd=carpeta_codigo,
    )


def _desplegar(
    carpeta_codigo: Path,
    deploy_git_url: str,
) -> str:
    if not deploy_git_url.strip():
        raise RuntimeError(
            "Falta configurar la URL Git de despliegue."
        )

    resultado = _ejecutar(
        [
            "git",
            "push",
            "--force",
            deploy_git_url.strip(),
            "HEAD:deploy",
        ],
        cwd=carpeta_codigo,
        timeout=GIT_TIMEOUT,
    )
    return (resultado.stdout + "\n" + resultado.stderr).strip()


def _clonar_rollback(
    repositorio: str,
    destino: Path,
) -> bool:
    valor = str(repositorio or "").strip()
    if not valor:
        return False

    if valor.startswith("git@github.com:"):
        ruta = valor.removeprefix("git@github.com:")
        valor = f"https://github.com/{ruta}"

    if not valor.endswith(".git"):
        valor += ".git"

    try:
        _ejecutar(
            ["git", "clone", "--depth", "1", valor, str(destino)],
            timeout=GIT_TIMEOUT,
        )
        return True
    except Exception:
        shutil.rmtree(destino, ignore_errors=True)
        return False


def _consultar_health(
    health_url: str,
    timeout_total: int = HEALTH_TIMEOUT,
) -> dict:
    url = str(health_url or "").strip()
    if not url:
        raise RuntimeError("Falta configurar la URL de verificación /health.")

    limite = time.monotonic() + max(30, int(timeout_total))
    ultimo_error = "Sin respuesta"

    while time.monotonic() < limite:
        try:
            solicitud = Request(
                url,
                method="GET",
                headers={"User-Agent": "BotRespaldosPremium-Recovery/1.0"},
            )
            with urlopen(solicitud, timeout=20) as respuesta:
                cuerpo = respuesta.read().decode("utf-8-sig")
                if int(getattr(respuesta, "status", 200)) != 200:
                    ultimo_error = f"HTTP {respuesta.status}"
                else:
                    datos = json.loads(cuerpo)
                    if datos.get("ok") is True:
                        return datos
                    ultimo_error = cuerpo[:300]
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
            ultimo_error = str(error)

        time.sleep(max(3, HEALTH_INTERVAL))

    raise RuntimeError(
        "El proyecto no superó la verificación /health. "
        f"Último resultado: {ultimo_error}"
    )


def restaurar_codigo_remoto(
    *,
    ruta_respaldo: str,
    sha256_esperado: str,
    respaldo_id: int,
    bot_nombre: str,
    repositorio_actual: str,
    deploy_git_url: str,
    health_url: str,
) -> dict:
    """Despliega codigo/ desde un respaldo y verifica /health.

    Si la comprobación de salud falla, intenta volver a desplegar el
    repositorio actual de GitHub como rollback preventivo.
    """
    ruta = Path(ruta_respaldo)
    if not ruta.is_file():
        raise RuntimeError(
            "El archivo físico del respaldo no está disponible."
        )

    sha_real = _sha256_archivo(ruta)
    esperado = str(sha256_esperado or "").strip().lower()
    if esperado and sha_real.lower() != esperado:
        raise RuntimeError(
            "La firma SHA-256 del respaldo no coincide."
        )

    carpeta_trabajo = Path(
        tempfile.mkdtemp(prefix=f"recovery_{int(respaldo_id)}_")
    )
    codigo = carpeta_trabajo / "codigo"
    rollback = carpeta_trabajo / "rollback"

    rollback_disponible = False
    try:
        manifest, archivos = _extraer_codigo(ruta, codigo)
        _validar_codigo(codigo)

        manifest_bot_id = manifest.get("bot_id")
        if manifest_bot_id is not None and int(manifest_bot_id) <= 0:
            raise RuntimeError("El manifest contiene un bot_id inválido.")

        rollback_disponible = _clonar_rollback(
            repositorio_actual,
            rollback,
        )

        _preparar_git(
            codigo,
            f"Restaurar respaldo #{int(respaldo_id)} - {bot_nombre}",
        )
        salida_git = _desplegar(codigo, deploy_git_url)

        try:
            health = _consultar_health(health_url)
        except Exception as error_health:
            if rollback_disponible:
                try:
                    _preparar_git(
                        rollback,
                        f"Rollback preventivo tras fallo de respaldo #{int(respaldo_id)}",
                    )
                    _desplegar(rollback, deploy_git_url)
                    _consultar_health(health_url)
                except Exception as error_rollback:
                    raise RuntimeError(
                        f"{error_health} Además, el rollback automático falló: "
                        f"{error_rollback}"
                    ) from error_rollback

                raise RuntimeError(
                    f"{error_health} Se aplicó rollback automático al código actual."
                ) from error_health
            raise

        return {
            "correcto": True,
            "archivos_codigo": len(archivos),
            "sha256": sha_real,
            "manifest": manifest,
            "health": health,
            "salida_git": salida_git[-4000:],
            "rollback_preparado": rollback_disponible,
        }
    finally:
        shutil.rmtree(carpeta_trabajo, ignore_errors=True)
