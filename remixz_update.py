#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RemixZ Updater — comprueba y aplica updates desde GitHub.
Repo: https://github.com/alikhan847547-sketch/remixz

Prioridad de detección:
  1) Releases (tag / assets)
  2) version.json en la rama principal
  3) Último commit SHA (cuando el repo tenga contenido)

No fuerza update si el repositorio está vacío.
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

REPO = "alikhan847547-sketch/remixz"
REPO_URL = f"https://github.com/{REPO}"
API_BASE = f"https://api.github.com/repos/{REPO}"
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
}


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
    raw: dict[str, Any] = field(default_factory=dict)


def _app_dir() -> Path:
    import sys
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def load_local_version(app_dir: Path | None = None) -> dict[str, Any]:
    base = app_dir or _app_dir()
    path = base / "version.json"
    if not path.exists():
        return {
            "app": "RemixZ Cleaner X",
            "version": "3.2.0",
            "build": "",
            "repo": REPO,
            "update_branch": "main",
            "commit_sha": "",
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {"version": "0.0.0", "repo": REPO}


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


def check_for_updates(app_dir: Path | None = None) -> UpdateInfo:
    """Consulta GitHub y devuelve si hay update disponible."""
    base = app_dir or _app_dir()
    local = load_local_version(base)
    local_ver = str(local.get("version", "0.0.0"))
    local_sha = str(local.get("commit_sha", "") or "")
    branch = str(local.get("update_branch") or "main")

    info = UpdateInfo(local_version=local_ver, local_sha=local_sha)

    # Repo existe?
    code, repo = _http_get_json(API_BASE)
    if code != 200:
        info.message = "No se pudo conectar con GitHub o el repo no es público."
        info.raw = {"http": code, "body": repo}
        return info

    # 1) Releases
    code, rel = _http_get_json(f"{API_BASE}/releases/latest")
    if code == 200 and isinstance(rel, dict) and rel.get("tag_name"):
        tag = str(rel.get("tag_name", "")).lstrip("vV")
        info.ready = True
        info.source = "release"
        info.remote_version = tag
        info.release_notes = str(rel.get("body") or rel.get("name") or "")
        info.download_url = str(rel.get("zipball_url") or "")
        # prefer asset .zip if present
        for asset in rel.get("assets") or []:
            name = str(asset.get("name", "")).lower()
            if name.endswith(".zip"):
                info.download_url = str(asset.get("browser_download_url") or info.download_url)
                break
        info.available = _is_newer(tag, local_ver)
        info.message = (
            f"Nueva versión {tag} disponible (local {local_ver})."
            if info.available
            else f"Estás al día (v{local_ver})."
        )
        info.raw = rel
        return info

    # 2) version.json en rama
    for br in (branch, *DEFAULT_BRANCHES):
        code, content = _http_get_json(
            f"{API_BASE}/contents/version.json?ref={br}"
        )
        if code == 200 and isinstance(content, dict) and content.get("download_url"):
            dcode, ver_data = _http_get_json(content["download_url"])
            if dcode == 200 and isinstance(ver_data, dict):
                remote_ver = str(ver_data.get("version", "")).lstrip("vV")
                info.ready = True
                info.source = "version.json"
                info.remote_version = remote_ver
                info.download_url = f"https://codeload.github.com/{REPO}/zip/refs/heads/{br}"
                info.release_notes = str(ver_data.get("notes") or "")
                info.available = _is_newer(remote_ver, local_ver)
                info.message = (
                    f"Nueva versión {remote_ver} en rama {br} (local {local_ver})."
                    if info.available
                    else f"Estás al día (v{local_ver})."
                )
                info.raw = ver_data
                return info

    # 3) Último commit
    for br in (branch, *DEFAULT_BRANCHES):
        code, commits = _http_get_json(f"{API_BASE}/commits?sha={br}&per_page=1")
        if code == 200 and isinstance(commits, list) and commits:
            sha = str(commits[0].get("sha", ""))
            msg = ""
            try:
                msg = str(commits[0].get("commit", {}).get("message", ""))
            except Exception:
                pass
            info.ready = True
            info.source = "commit"
            info.remote_sha = sha
            info.remote_version = sha[:7] if sha else ""
            info.download_url = f"https://codeload.github.com/{REPO}/zip/refs/heads/{br}"
            info.release_notes = msg
            if local_sha and sha and local_sha != sha:
                info.available = True
                info.message = f"Hay commits nuevos en {br} ({sha[:7]})."
            elif not local_sha and sha:
                # primera sync: avisar pero no forzar si no hay version remota semver
                info.available = False
                info.message = (
                    f"Repo activo en {br} ({sha[:7]}). "
                    f"Aún no hay release/version.json — se avisará al publicar update."
                )
            else:
                info.available = False
                info.message = f"Estás al día con {br}."
            info.raw = commits[0] if commits else {}
            return info
        if code == 409:
            # empty repo
            info.ready = False
            info.message = (
                "El repositorio existe pero aún está vacío. "
                "Cuando suban archivos/releases, el update se activará solo."
            )
            info.raw = {"http": 409, "branch": br}
            return info

    info.message = "No se encontró release ni version.json ni commits en el repo."
    return info


def apply_update(
    info: UpdateInfo,
    app_dir: Path | None = None,
    progress_cb: Callable | None = None,
    status_cb: Callable | None = None,
) -> tuple[bool, str]:
    """
    Descarga el zip del repo/release y actualiza archivos locales.
    Conserva config y logs.

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
        files = [
            p for p in src_root.rglob("*")
            if p.is_file()
            and not any(part in PROTECTED_NAMES for part in p.relative_to(src_root).parts)
            and p.suffix != ".pyc"
            and "__pycache__" not in p.relative_to(src_root).parts
        ]
        total_f = max(len(files), 1)
        copied = 0
        for i, path in enumerate(files, 1):
            rel = path.relative_to(src_root)
            dest = base / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
            copied += 1
            if i == 1 or i == total_f or i % max(1, total_f // 25) == 0:
                pct = 66 + int(i / total_f * 29)
                report(f"Aplicando… {i}/{total_f}  ({rel.name})", pct)

        # ── Fase 4: version.json local (95–100 %) ──────────────────────────
        report("Actualizando version.json…", 96)
        local = load_local_version(base)
        if info.remote_version and info.source in ("release", "version.json"):
            local["version"] = info.remote_version.lstrip("vV")
        if info.remote_sha:
            local["commit_sha"] = info.remote_sha
        local["last_update"] = time.strftime("%Y-%m-%d %H:%M:%S")
        local["repo"] = REPO
        local["repo_url"] = REPO_URL
        save_local_version(local, base)

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
