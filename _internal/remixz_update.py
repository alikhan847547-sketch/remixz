#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RemixZ Updater — comprueba y aplica updates desde GitHub.

Se mantienen DOS repositorios (mirror / respaldo):
  1) https://github.com/alikhan847547-sketch/remixz   (principal)
  2) https://github.com/SMPROJECT115/remixz           (secundario)

Prioridad de detección por cada repo:
  1) Releases (tag / assets)
  2) version.json en la rama principal
  3) Último commit SHA (cuando el repo tenga contenido)

Se elige el update con la versión más nueva entre ambos.
No fuerza update si los repositorios están vacíos.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import ssl
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

# Repos mantenidos en paralelo (orden = prioridad de consulta)
REPOS: tuple[str, ...] = (
    "SMPROJECT115/remixz",
    "SMPROJECT115/newrepo",
    "alikhan847547-sketch/remixz",
)
REPO = REPOS[0]  # principal (compat)
REPO_URL = f"https://github.com/{REPO}"
REPO_URLS: tuple[str, ...] = tuple(f"https://github.com/{r}" for r in REPOS)
DEFAULT_BRANCHES = ("main", "master")
USER_AGENT = "RemixZ-Updater/1.0 (+https://github.com/alikhan847547-sketch/remixz)"

# Archivos que NUNCA se sobrescriben al aplicar update
PROTECTED_NAMES = {
    "config.json",
    "grok_auth.json",
    "genre_config.json",
    "genre_cache.sqlite",
    "tmdb_config.json",
    "logs",
    "genre_temp",
    "genre_cache",
    "tmdb_cache",
    "__pycache__",
    ".git",
    "_pending_update",
    "_finish_update.cmd",
}

# Extensiones que suelen estar bloqueadas si la app está en ejecución (EXE)
_LOCK_PRONE_SUFFIXES = {
    ".exe",
    ".dll",
    ".pyd",
    ".so",
    ".dylib",
}

PENDING_DIR_NAME = "_pending_update"
FINISH_SCRIPT_NAME = "_finish_update.cmd"


@dataclass
class UpdateInfo:
    available: bool = False
    ready: bool = False  # repo con contenido y version detectable
    message: str = ""
    remote_version: str = ""
    local_version: str = ""
    remote_sha: str = ""
    local_sha: str = ""
    source: str = ""  # release | version.json | commit
    download_url: str = ""
    release_notes: str = ""
    repo: str = ""  # owner/name del repo que ofrece el update
    repo_url: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


def _app_dir() -> Path:
    import sys
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _repos_from_local(local: dict[str, Any] | None = None) -> list[str]:
    """Lista de repos a consultar: version.json + defaults (sin duplicados)."""
    ordered: list[str] = []
    seen: set[str] = set()

    def add(name: str) -> None:
        n = (name or "").strip().lstrip("/")
        if not n or n in seen:
            return
        # normalizar URL completa → owner/repo
        if "github.com/" in n:
            n = n.split("github.com/", 1)[1].rstrip("/").removesuffix(".git")
        seen.add(n)
        ordered.append(n)

    if local:
        add(str(local.get("repo") or ""))
        for r in local.get("repos") or []:
            add(str(r))
        add(str(local.get("repo_secondary") or ""))
    for r in REPOS:
        add(r)
    return ordered


def load_local_version(app_dir: Path | None = None) -> dict[str, Any]:
    base = app_dir or _app_dir()
    path = base / "version.json"
    if not path.exists():
        return {
            "app": "RemixZ Cleaner X",
            "version": "3.2.0",
            "build": "",
            "repo": REPO,
            "repos": list(REPOS),
            "repo_url": REPO_URL,
            "update_branch": "main",
            "commit_sha": "",
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {"version": "0.0.0", "repo": REPO, "repos": list(REPOS)}


def save_local_version(data: dict[str, Any], app_dir: Path | None = None) -> None:
    base = app_dir or _app_dir()
    path = base / "version.json"
    path.write_text(json.dumps(data, indent=4, ensure_ascii=False) + "\n", encoding="utf-8")


def _http_get_json(url: str, timeout: float = 15) -> tuple[int, Any]:
    ctx = ssl.create_default_context()
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.status, json.loads(raw) if raw.strip() else None
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
            data = json.loads(body) if body.strip().startswith(("{", "[")) else {"message": body[:200]}
        except Exception:
            data = {"message": str(exc)}
        return exc.code, data
    except Exception as exc:
        return 0, {"message": str(exc)}


def _http_download(url: str, dest: Path, timeout: float = 120, progress_cb: Callable | None = None) -> None:
    """Descarga con callback de progreso: progress_cb(pct_0_100, mensaje)."""
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as f:
            while True:
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress_cb:
                    if total > 0:
                        pct = int(done / total * 100)
                        mb = done / (1024 * 1024)
                        tot_mb = total / (1024 * 1024)
                        progress_cb(pct, f"Descargando… {mb:.1f}/{tot_mb:.1f} MB")
                    else:
                        # sin Content-Length: avance suave estimado
                        pct = min(95, 5 + (done // (256 * 1024)) * 3)
                        progress_cb(pct, f"Descargando… {done // 1024} KB")
        if progress_cb:
            progress_cb(100, "Descarga completa")


def _parse_version(v: str) -> tuple:
    nums = re.findall(r"\d+", str(v or "0"))
    parts = [int(x) for x in nums[:4]]
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def _is_newer(remote: str, local: str) -> bool:
    if not remote:
        return False
    if not local:
        return True
    try:
        return _parse_version(remote) > _parse_version(local)
    except Exception:
        return remote.strip() != local.strip()


def _check_one_repo(
    repo: str,
    local_ver: str,
    local_sha: str,
    branch: str,
) -> UpdateInfo:
    """
    Consulta un repositorio y elige la fuente con la versión MÁS NUEVA.

    Importante: NO devolver solo el release si version.json en main es más nuevo.
    Caso real: release latest = v3.3.0 pero main/version.json = 3.5.0.
    """
    api = f"https://api.github.com/repos/{repo}"
    base = UpdateInfo(
        local_version=local_ver,
        local_sha=local_sha,
        repo=repo,
        repo_url=f"https://github.com/{repo}",
    )

    code, body = _http_get_json(api)
    if code != 200:
        base.message = f"No se pudo conectar con {repo}."
        base.raw = {"http": code, "body": body, "repo": repo}
        return base

    candidates: list[UpdateInfo] = []

    # 1) Releases
    code, rel = _http_get_json(f"{api}/releases/latest")
    if code == 200 and isinstance(rel, dict) and rel.get("tag_name"):
        tag = str(rel.get("tag_name", "")).lstrip("vV")
        info = UpdateInfo(
            local_version=local_ver,
            local_sha=local_sha,
            repo=repo,
            repo_url=f"https://github.com/{repo}",
            ready=True,
            source="release",
            remote_version=tag,
            release_notes=str(rel.get("body") or rel.get("name") or ""),
            download_url=str(rel.get("zipball_url") or ""),
            raw=rel,
        )
        for asset in rel.get("assets") or []:
            name = str(asset.get("name", "")).lower()
            if name.endswith(".zip"):
                info.download_url = str(asset.get("browser_download_url") or info.download_url)
                break
        info.available = _is_newer(tag, local_ver)
        info.message = (
            f"Nueva versión {tag} en {repo} (release; local {local_ver})."
            if info.available
            else f"Release {repo} v{tag} ≤ local v{local_ver}."
        )
        candidates.append(info)

    # 2) version.json en rama (siempre consultar; puede ser más nuevo que el release)
    for br in (branch, *DEFAULT_BRANCHES):
        code, content = _http_get_json(f"{api}/contents/version.json?ref={br}")
        if code != 200 or not isinstance(content, dict):
            continue
        ver_data = None
        try:
            if content.get("encoding") == "base64" and content.get("content"):
                import base64
                raw = base64.b64decode(content["content"]).decode("utf-8", errors="replace")
                ver_data = json.loads(raw)
        except Exception:
            ver_data = None
        if not isinstance(ver_data, dict) and content.get("download_url"):
            dcode, ver_data = _http_get_json(content["download_url"])
            if dcode != 200 or not isinstance(ver_data, dict):
                ver_data = None
        if isinstance(ver_data, dict):
            remote_ver = str(ver_data.get("version", "")).lstrip("vV")
            info = UpdateInfo(
                local_version=local_ver,
                local_sha=local_sha,
                repo=repo,
                repo_url=f"https://github.com/{repo}",
                ready=True,
                source="version.json",
                remote_version=remote_ver,
                download_url=f"https://codeload.github.com/{repo}/zip/refs/heads/{br}",
                release_notes=str(ver_data.get("notes") or ""),
                available=_is_newer(remote_ver, local_ver),
                raw=ver_data,
            )
            info.message = (
                f"Nueva versión {remote_ver} en {repo}/{br} (local {local_ver})."
                if info.available
                else f"Al día con {repo}/{br} (v{local_ver})."
            )
            candidates.append(info)
            break

    # 3) Último commit (solo si no hay release ni version.json)
    if not candidates:
        for br in (branch, *DEFAULT_BRANCHES):
            code, commits = _http_get_json(f"{api}/commits?sha={br}&per_page=1")
            if code == 200 and isinstance(commits, list) and commits:
                sha = str(commits[0].get("sha", ""))
                msg = ""
                try:
                    msg = str(commits[0].get("commit", {}).get("message", ""))
                except Exception:
                    pass
                info = UpdateInfo(
                    local_version=local_ver,
                    local_sha=local_sha,
                    repo=repo,
                    repo_url=f"https://github.com/{repo}",
                    ready=True,
                    source="commit",
                    remote_sha=sha,
                    remote_version=sha[:7] if sha else "",
                    download_url=f"https://codeload.github.com/{repo}/zip/refs/heads/{br}",
                    release_notes=msg,
                    raw=commits[0] if commits else {},
                )
                if local_sha and sha and local_sha != sha:
                    info.available = True
                    info.message = f"Commits nuevos en {repo}/{br} ({sha[:7]})."
                elif not local_sha and sha:
                    info.available = False
                    info.message = (
                        f"Repo {repo} activo en {br} ({sha[:7]}). "
                        f"Sin release/version.json todavía."
                    )
                else:
                    info.available = False
                    info.message = f"Al día con {repo}/{br}."
                return info
            if code == 409:
                base.ready = False
                base.message = f"El repositorio {repo} existe pero está vacío."
                base.raw = {"http": 409, "branch": br, "repo": repo}
                return base

    if not candidates:
        base.message = f"Sin release/version/commits en {repo}."
        return base

    # Elegir la versión numérica más alta (release vs version.json)
    def _key(c: UpdateInfo):
        return _parse_version(c.remote_version or "0")

    best = max(candidates, key=_key)
    # Si hay un update disponible, preferir el más nuevo entre los available
    avail = [c for c in candidates if c.available and c.download_url]
    if avail:
        best = max(avail, key=_key)
    return best


def check_for_updates(app_dir: Path | None = None) -> UpdateInfo:
    """
    Consulta TODOS los repos configurados y devuelve el mejor update.
    - Si hay versiones disponibles, elige la más nueva.
    - Si ninguno tiene update, devuelve el primer repo "ready".
    """
    base = app_dir or _app_dir()
    local = load_local_version(base)
    local_ver = str(local.get("version", "0.0.0"))
    local_sha = str(local.get("commit_sha", "") or "")
    branch = str(local.get("update_branch") or "main")
    repos = _repos_from_local(local)

    candidates: list[UpdateInfo] = []
    errors: list[str] = []

    for repo in repos:
        try:
            info = _check_one_repo(repo, local_ver, local_sha, branch)
        except Exception as exc:
            errors.append(f"{repo}: {exc}")
            continue
        candidates.append(info)

    if not candidates:
        return UpdateInfo(
            local_version=local_ver,
            local_sha=local_sha,
            message="No se pudo consultar ningún repositorio."
            + ((" " + "; ".join(errors)) if errors else ""),
            repo=repos[0] if repos else REPO,
            repo_url=REPO_URL,
        )

    # Preferir updates disponibles con versión más alta
    available = [c for c in candidates if c.available and c.download_url]
    if available:
        best = max(
            available,
            key=lambda c: _parse_version(c.remote_version or "0"),
        )
        others = [c.repo for c in available if c.repo != best.repo]
        if others:
            best.message = (
                f"{best.message}  ·  (también en: {', '.join(others)})"
                if best.message
                else best.message
            )
        return best

    # Sin update: devolver el primer ready, o el primero con mensaje útil
    ready = next((c for c in candidates if c.ready), None)
    if ready:
        mirrors = ", ".join(c.repo for c in candidates if c.ready)
        ready.message = (
            f"{ready.message}  ·  Repos: {mirrors}"
            if mirrors and ready.message
            else ready.message
        )
        return ready

    first = candidates[0]
    first.message = first.message or "Ningún repositorio respondió con contenido."
    return first


def _is_lock_error(exc: BaseException) -> bool:
    """WinError 32/33/5 u OSError de archivo en uso."""
    if isinstance(exc, PermissionError):
        return True
    if isinstance(exc, OSError):
        win = getattr(exc, "winerror", None)
        if win in (5, 32, 33):
            return True
        if getattr(exc, "errno", None) in (11, 13, 16):
            return True
        msg = str(exc).lower()
        if "being used by another process" in msg or "access is denied" in msg:
            return True
        if "está siendo utilizado" in msg or "proceso no tiene acceso" in msg:
            return True
    return False


def _safe_copy_file(src: Path, dest: Path, retries: int = 6) -> str:
    """
    Copia un archivo tolerando bloqueos (EXE/DLL en uso).

    Returns:
      "ok"       — copiado al destino final
      "deferred" — dejado en sidecar .new / se reintentará al reiniciar
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    last_exc: BaseException | None = None
    pid = os.getpid()

    for attempt in range(retries):
        tmp = dest.with_name(f".{dest.name}.tmp_{pid}")
        bak = dest.with_name(f".{dest.name}.old_{pid}")
        try:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
            shutil.copy2(src, tmp)
            try:
                os.replace(str(tmp), str(dest))
                return "ok"
            except OSError as exc:
                last_exc = exc
                if not _is_lock_error(exc):
                    raise
                # Intentar renombrar el bloqueado y poner el nuevo
                try:
                    if bak.exists():
                        try:
                            bak.unlink()
                        except OSError:
                            pass
                    if dest.exists():
                        os.replace(str(dest), str(bak))
                    os.replace(str(tmp), str(dest))
                    try:
                        bak.unlink()
                    except OSError:
                        pass  # se limpia en el siguiente arranque
                    return "ok"
                except OSError as exc2:
                    last_exc = exc2
        except OSError as exc:
            last_exc = exc
            if not _is_lock_error(exc) and not isinstance(exc, PermissionError):
                # errores no-lock: reintentar un poco y si no, propagar al final
                pass
        finally:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
        time.sleep(0.12 * (attempt + 1))

    # Diferir: copiar a destino.new (el script de cierre lo aplicará)
    try:
        pending_sidecar = dest.with_name(dest.name + ".new")
        shutil.copy2(src, pending_sidecar)
        return "deferred"
    except OSError:
        pass

    if last_exc:
        raise last_exc
    raise OSError(f"No se pudo copiar {src.name}")


def _stage_pending(src: Path, pending_root: Path, rel: Path) -> None:
    target = pending_root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, target)


def _write_finish_script(base: Path, pending_dir: Path, restart_cmd: list[str]) -> Path:
    """
    CMD que espera a que muera este proceso, aplica _pending_update + *.new,
    limpia basura .old_*, y relanza la app.
    """
    script = base / FINISH_SCRIPT_NAME
    pid = os.getpid()
    # Escapar para cmd
    base_s = str(base).replace('"', "")
    pending_s = str(pending_dir).replace('"', "")
    if restart_cmd:
        # join simple: cada arg entre comillas
        parts = []
        for a in restart_cmd:
            a = str(a).replace('"', "")
            parts.append(f'"{a}"' if " " in a or "\\" in a else a)
        # Prefer quoted full path form
        launch = subprocess_list2cmdline(restart_cmd)
    else:
        launch = f'"{base_s}\\RemixZ_Cleaner_X.exe"'

    content = f"""@echo off
setlocal EnableExtensions
cd /d "{base_s}"
set PID={pid}
set PENDING={pending_s}
echo [RemixZ] Esperando cierre del proceso %PID%…
:wait
tasklist /FI "PID eq %PID%" 2>nul | find "%PID%" >nul
if not errorlevel 1 (
  ping -n 2 127.0.0.1 >nul
  goto wait
)
ping -n 2 127.0.0.1 >nul
echo [RemixZ] Aplicando archivos pendientes…
if exist "%PENDING%" (
  robocopy "%PENDING%" "{base_s}" /E /IS /IT /R:3 /W:1 /NFL /NDL /NJH /NJS /nc /ns /np >nul
  rmdir /S /Q "%PENDING%" 2>nul
)
REM aplicar sidecars *.new
for /r "{base_s}" %%F in (*.new) do (
  set "F=%%~fF"
  setlocal enabledelayedexpansion
  set "DEST=!F:.new=!"
  move /Y "%%~fF" "!DEST!" >nul 2>&1
  endlocal
)
REM limpiar renombres temporales
for /r "{base_s}" %%F in (.*.old_*) do del /f /q "%%~fF" 2>nul
for /r "{base_s}" %%F in (.*.tmp_*) do del /f /q "%%~fF" 2>nul
echo [RemixZ] Reiniciando…
start "" {launch}
ping -n 2 127.0.0.1 >nul
del /f /q "%~f0" 2>nul
exit /b 0
"""
    script.write_text(content, encoding="utf-8", errors="replace")
    return script


def subprocess_list2cmdline(seq: list[str]) -> str:
    """Compatible con Windows list2cmdline sin importar subprocess arriba del todo."""
    import subprocess

    return subprocess.list2cmdline(seq)


def has_pending_update(app_dir: Path | None = None) -> bool:
    base = app_dir or _app_dir()
    pending = base / PENDING_DIR_NAME
    if pending.is_dir():
        # solo cuenta si hay archivos reales
        try:
            if any(pending.rglob("*")):
                return True
        except Exception:
            return True
    # cualquier *.new en la raíz o _internal
    for p in base.glob("*.new"):
        if p.is_file():
            return True
    internal = base / "_internal"
    if internal.is_dir():
        for p in internal.rglob("*.new"):
            if p.is_file():
                return True
    # leftovers de renombre (.old_pid / .tmp_pid) no bloquean el arranque
    return False


def apply_pending_on_boot(
    app_dir: Path | None = None,
    progress_cb: Callable | None = None,
    status_cb: Callable | None = None,
) -> tuple[bool, str]:
    """
    Aplica en el LOADING / arranque lo que quedó pendiente por WinError 32:
      - carpeta _pending_update/
      - archivos *.new junto al destino final
      - limpia .old_* / .tmp_* residuales
      - elimina _finish_update.cmd si ya no hace falta

    Se llama desde el splash antes de deps/motor. No cierra el proceso.
    Returns: (hubo_trabajo_o_ok, mensaje)
    """
    base = Path(app_dir) if app_dir is not None else _app_dir()

    def report(msg: str, pct: int | None = None):
        if status_cb:
            try:
                status_cb(msg)
            except Exception:
                pass
        if progress_cb and pct is not None:
            try:
                progress_cb(max(0, min(100, int(pct))), msg)
            except Exception:
                pass

    pending = base / PENDING_DIR_NAME
    applied = 0
    deferred = 0
    cleaned = 0

    if not has_pending_update(base) and not (base / FINISH_SCRIPT_NAME).exists():
        # limpiar basura menor aunque no haya pending real
        for pattern in (".*.old_*", ".*.tmp_*"):
            for p in base.rglob(pattern):
                try:
                    if p.is_file():
                        p.unlink()
                        cleaned += 1
                except OSError:
                    pass
        if cleaned:
            return True, f"Limpieza de residuos de update ({cleaned})."
        return True, "Sin update pendiente."

    report("Aplicando update pendiente al arranque…", 5)

    # 1) _pending_update → base
    if pending.is_dir():
        files = [p for p in pending.rglob("*") if p.is_file()]
        total = max(len(files), 1)
        for i, src in enumerate(files, 1):
            rel = src.relative_to(pending)
            # no pisar config/logs protegidos
            if any(part in PROTECTED_NAMES for part in rel.parts):
                continue
            dest = base / rel
            try:
                result = _safe_copy_file(src, dest, retries=4)
                if result == "ok":
                    applied += 1
                    try:
                        src.unlink()
                    except OSError:
                        pass
                else:
                    deferred += 1
            except Exception:
                deferred += 1
            if i == 1 or i == total or i % max(1, total // 10) == 0:
                report(f"Pending… {i}/{total}  ({rel.name})", 5 + int(i / total * 70))

        # borrar pending si quedó vacío
        try:
            leftover = [p for p in pending.rglob("*") if p.is_file()]
            if not leftover:
                shutil.rmtree(pending, ignore_errors=True)
        except Exception:
            pass

    # 2) sidecars *.new
    report("Aplicando archivos .new…", 80)
    new_files = list(base.glob("*.new"))
    internal = base / "_internal"
    if internal.is_dir():
        new_files.extend(internal.rglob("*.new"))
    for nf in new_files:
        if not nf.is_file():
            continue
        dest = nf.with_name(nf.name[:-4]) if nf.name.endswith(".new") else nf
        # name "foo.exe.new" → with_name might be wrong; handle .new suffix
        if nf.name.endswith(".new"):
            dest = nf.with_name(nf.name[: -len(".new")])
        try:
            result = _safe_copy_file(nf, dest, retries=4)
            if result == "ok":
                applied += 1
                try:
                    nf.unlink()
                except OSError:
                    pass
            else:
                deferred += 1
        except Exception:
            deferred += 1

    # 3) basura temporal
    report("Limpiando residuos…", 92)
    for p in base.rglob("*"):
        try:
            name = p.name
            if not p.is_file():
                continue
            if name.startswith(".") and (".old_" in name or ".tmp_" in name):
                p.unlink()
                cleaned += 1
        except OSError:
            pass

    # 4) si ya no hay pending real, quitar script de cierre
    if not has_pending_update(base):
        fin = base / FINISH_SCRIPT_NAME
        if fin.exists():
            try:
                fin.unlink()
            except OSError:
                pass

    msg = f"Arranque: aplicados {applied}"
    if deferred:
        msg += f", aún bloqueados {deferred} (se reintentan)"
    if cleaned:
        msg += f", limpios {cleaned}"
    report(msg, 100)
    return True, msg


def launch_finish_update_and_exit(
    app_dir: Path | None = None,
    restart_cmd: list[str] | None = None,
) -> bool:
    """
    Lanza _finish_update.cmd (si hay pendiente) y debe ir seguido de os._exit.
    """
    import subprocess

    base = app_dir or _app_dir()
    script = base / FINISH_SCRIPT_NAME
    pending = base / PENDING_DIR_NAME
    if not script.exists():
        if not pending.exists() and not has_pending_update(base):
            return False
        # generar script si solo hay pending
        if restart_cmd is None:
            if getattr(__import__("sys"), "frozen", False):
                restart_cmd = [__import__("sys").executable]
            else:
                exe = base / "RemixZ_Cleaner_X.exe"
                vbs = base / "ejecutar_Cleaner_X.vbs"
                py = base / "RemixZ_Cleaner_X_App.py"
                if exe.exists():
                    restart_cmd = [str(exe)]
                elif vbs.exists():
                    restart_cmd = ["wscript.exe", str(vbs)]
                else:
                    restart_cmd = [__import__("sys").executable, str(py)]
        _write_finish_script(base, pending if pending.exists() else base / PENDING_DIR_NAME, restart_cmd)

    flags = 0
    if os.name == "nt":
        flags = (
            getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        )
    subprocess.Popen(
        ["cmd.exe", "/c", str(script)],
        cwd=str(base),
        close_fds=True,
        creationflags=flags,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
    )
    return True


def apply_update(
    info: UpdateInfo,
    app_dir: Path | None = None,
    progress_cb: Callable | None = None,
    status_cb: Callable | None = None,
) -> tuple[bool, str]:
    """
    Descarga el zip del repo/release y actualiza archivos locales.
    Conserva config y logs.

    Si un archivo está bloqueado (EXE/DLL en uso → WinError 32), se deja en
    _pending_update/ y se escribe _finish_update.cmd para aplicarlo al reiniciar.
    Así el update desde 3.1.5/EXE no falla por archivo en uso.

    progress_cb(pct: int 0-100, message: str)
    status_cb(message: str)
    """
    base = app_dir or _app_dir()
    if not info.download_url:
        return False, "No hay URL de descarga."

    def report(msg: str, pct: int | None = None):
        if status_cb:
            try:
                status_cb(msg)
            except Exception:
                pass
        if progress_cb and pct is not None:
            try:
                progress_cb(max(0, min(100, int(pct))), msg)
            except Exception:
                pass

    tmp = Path(tempfile.mkdtemp(prefix="remixz_update_"))
    zip_path = tmp / "update.zip"
    extract_dir = tmp / "extract"
    pending_dir = base / PENDING_DIR_NAME

    try:
        # ── Fase 1: descarga (0–50 %) ──────────────────────────────────────
        report("Conectando con GitHub…", 2)

        def on_dl(p: int, m: str):
            # mapear 0-100 descarga → 2-50 global
            report(m, 2 + int(p * 0.48))

        _http_download(info.download_url, zip_path, progress_cb=on_dl)
        report("Descarga completa", 50)

        # ── Fase 2: extracción (50–65 %) ───────────────────────────────────
        report("Extrayendo archivos…", 52)
        extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zf:
            members = zf.namelist()
            total_m = max(len(members), 1)
            for i, name in enumerate(members, 1):
                zf.extract(name, extract_dir)
                if i == 1 or i == total_m or i % max(1, total_m // 20) == 0:
                    pct = 52 + int(i / total_m * 13)
                    report(f"Extrayendo… {i}/{total_m}", pct)
        report("Extracción completa", 65)

        # GitHub zip suele tener una carpeta raíz repo-branch/
        roots = [p for p in extract_dir.iterdir() if p.is_dir()]
        src_root = roots[0] if len(roots) == 1 else extract_dir

        # ── Fase 3: copiar archivos (65–95 %) ──────────────────────────────
        report("Preparando archivos a copiar…", 66)
        # limpiar pending anterior
        if pending_dir.exists():
            try:
                shutil.rmtree(pending_dir, ignore_errors=True)
            except Exception:
                pass

        files = [
            p for p in src_root.rglob("*")
            if p.is_file()
            and not any(part in PROTECTED_NAMES for part in p.relative_to(src_root).parts)
            and p.suffix != ".pyc"
            and "__pycache__" not in p.relative_to(src_root).parts
            and not p.name.endswith(".new")
            and not p.name.startswith("._")
        ]
        # Copiar primero archivos "suaves" (.py, .json, …) y al final EXE/DLL
        def _copy_order(p: Path) -> tuple:
            suf = p.suffix.lower()
            hard = 1 if suf in _LOCK_PRONE_SUFFIXES else 0
            return (hard, str(p).lower())

        files.sort(key=_copy_order)

        total_f = max(len(files), 1)
        copied = 0
        deferred = 0
        errors: list[str] = []

        for i, path in enumerate(files, 1):
            rel = path.relative_to(src_root)
            dest = base / rel
            try:
                # Si es propenso a lock y el destino existe, ir directo a pending
                # cuando estamos frozen (EXE) o ya falló antes.
                prefer_defer = (
                    dest.exists()
                    and dest.suffix.lower() in _LOCK_PRONE_SUFFIXES
                    and (
                        getattr(__import__("sys"), "frozen", False)
                        or dest.name.lower() == "remixz_cleaner_x.exe"
                    )
                )
                if prefer_defer:
                    _stage_pending(path, pending_dir, rel)
                    deferred += 1
                else:
                    result = _safe_copy_file(path, dest)
                    if result == "ok":
                        copied += 1
                    else:
                        _stage_pending(path, pending_dir, rel)
                        deferred += 1
            except Exception as exc:
                if _is_lock_error(exc):
                    try:
                        _stage_pending(path, pending_dir, rel)
                        deferred += 1
                    except Exception as exc2:
                        errors.append(f"{rel}: {exc2}")
                else:
                    errors.append(f"{rel}: {exc}")

            if i == 1 or i == total_f or i % max(1, total_f // 25) == 0:
                pct = 66 + int(i / total_f * 29)
                report(
                    f"Aplicando… {i}/{total_f}  ({rel.name})"
                    + (f"  · diferidos:{deferred}" if deferred else ""),
                    pct,
                )

        if errors and copied == 0 and deferred == 0:
            report(f"Error: {errors[0]}", 100)
            return False, f"Error al aplicar update: {errors[0]}"

        # ── Fase 4: version.json local (95–100 %) ──────────────────────────
        report("Actualizando version.json…", 96)
        local = load_local_version(base)
        if info.remote_version and info.source in ("release", "version.json"):
            local["version"] = info.remote_version.lstrip("vV")
        if info.remote_sha:
            local["commit_sha"] = info.remote_sha
        local["last_update"] = time.strftime("%Y-%m-%d %H:%M:%S")
        # Mantener ambos repos siempre
        used_repo = (info.repo or REPO).strip() or REPO
        local["repo"] = used_repo
        local["repo_url"] = info.repo_url or f"https://github.com/{used_repo}"
        local["repos"] = list(dict.fromkeys([used_repo, *REPOS, *list(local.get("repos") or [])]))
        local["repo_secondary"] = next((r for r in REPOS if r != used_repo), REPOS[-1])
        try:
            save_local_version(local, base)
        except Exception:
            # version también bloqueada → pending
            try:
                ver_src = tmp / "version_out.json"
                ver_src.write_text(
                    __import__("json").dumps(local, indent=4, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                _stage_pending(ver_src, pending_dir, Path("version.json"))
                deferred += 1
            except Exception:
                pass

        # Script post-cierre si hubo diferidos o hay EXE nuevo pendiente
        if deferred > 0 or pending_dir.exists():
            import sys as _sys

            if getattr(_sys, "frozen", False):
                restart_cmd = [_sys.executable]
            else:
                exe = base / "RemixZ_Cleaner_X.exe"
                vbs = base / "ejecutar_Cleaner_X.vbs"
                py = base / "RemixZ_Cleaner_X_App.py"
                if exe.exists() or (pending_dir / "RemixZ_Cleaner_X.exe").exists():
                    restart_cmd = [str(exe if exe.exists() else pending_dir / "RemixZ_Cleaner_X.exe")]
                    if not exe.exists():
                        restart_cmd = [str(base / "RemixZ_Cleaner_X.exe")]
                elif vbs.exists():
                    restart_cmd = ["wscript.exe", str(vbs)]
                else:
                    restart_cmd = [_sys.executable, str(py)]
            _write_finish_script(base, pending_dir, restart_cmd)
            report("Update listo (parte al reiniciar).", 100)
            return True, (
                f"Update aplicado ({copied} ahora, {deferred} al reiniciar). "
                f"Reinicio automático…"
            )

        report("Update aplicado.", 100)
        return True, f"Update aplicado ({copied} archivos). Reinicio automático…"
    except Exception as exc:
        report(f"Error: {exc}", 100)
        return False, f"Error al aplicar update: {exc}"
    finally:
        try:
            shutil.rmtree(tmp, ignore_errors=True)
        except Exception:
            pass


def check_async(callback: Callable[[UpdateInfo], None], app_dir: Path | None = None) -> None:
    """Comprueba updates en background y llama callback(info)."""

    def worker():
        try:
            info = check_for_updates(app_dir)
        except Exception as exc:
            info = UpdateInfo(message=f"Error al comprobar updates: {exc}")
        try:
            callback(info)
        except Exception:
            pass

    threading.Thread(target=worker, daemon=True).start()
