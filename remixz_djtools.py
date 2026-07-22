#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ClubRemix DJ Tools — lógica portada de DJTOOLS.ps1 (mejorada v3.2)
- Renombrar con membresía mensual ClubRemix
- Actualizar metadata title (ffmpeg + mutagen fallback)
- Preview / dry-run
- Tag personalizado (mes/año)
- Barra de progreso vía progress_cb(current, total, message)
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Callable

MEDIA_EXT = {
    ".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".wma",
    ".mp4", ".mov", ".mkv", ".avi", ".wmv",
}

AUDIO_EXT = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".wma"}

# MEMBRESIA CLUBREMIX [ENE 2k26 ]
_OLD_MEMBERSHIP = re.compile(
    r"\s*MEMBRESIA\s+CLUBREMIX\s+\[[A-Z]{3}\s+2k\d{2}\s*\]\s*",
    re.IGNORECASE,
)
# Variantes sueltas que a veces quedan en el nombre
_LOOSE_TAG = re.compile(
    r"\s*(?:MEMBRESIA\s+)?CLUBREMIX\s*(?:\[[^\]]*\])?\s*",
    re.IGNORECASE,
)

ProgressCb = Callable[[int, int, str], None]  # current, total, message
CancelCb = Callable[[], bool]

MESES = ("ENE", "FEB", "MAR", "ABR", "MAY", "JUN",
         "JUL", "AGO", "SEP", "OCT", "NOV", "DIC")


def clubremix_tag(when: datetime | None = None, month: int | None = None, year: int | None = None) -> str:
    """Genera tag: MEMBRESIA CLUBREMIX [MAR 2k26 ]"""
    when = when or datetime.now()
    m_idx = (month or when.month) - 1
    m_idx = max(0, min(11, m_idx))
    m = MESES[m_idx]
    y = year if year is not None else when.year
    year_s = f"{int(y) % 100:02d}"
    return f"MEMBRESIA CLUBREMIX [{m} 2k{year_s} ]"


def remove_old_membership(name: str) -> str:
    clean = _OLD_MEMBERSHIP.sub(" ", name or "")
    clean = _LOOSE_TAG.sub(" ", clean)
    return re.sub(r"\s{2,}", " ", clean).strip(" -_.")


def get_media_files(folder: str | Path, *, recursive: bool = True) -> list[Path]:
    root = Path(folder)
    if not root.is_dir():
        return []
    out: list[Path] = []
    it = root.rglob("*") if recursive else root.iterdir()
    for p in it:
        try:
            if p.is_file() and p.suffix.lower() in MEDIA_EXT:
                out.append(p)
        except OSError:
            continue
    return sorted(out, key=lambda x: str(x).lower())


def count_media(folder: str | Path, *, recursive: bool = True) -> dict:
    files = get_media_files(folder, recursive=recursive)
    audio = sum(1 for f in files if f.suffix.lower() in AUDIO_EXT)
    video = len(files) - audio
    return {
        "total": len(files),
        "audio": audio,
        "video": video,
        "files": files,
    }


def find_ffmpeg() -> Path | None:
    candidates = [
        Path(r"C:\ffmpeg\bin\ffmpeg.exe"),
        Path(shutil.which("ffmpeg") or ""),
    ]
    try:
        here = Path(__file__).resolve().parent
        candidates.extend([
            here / "ffmpeg.exe",
            here / "bin" / "ffmpeg.exe",
            here / "_internal" / "ffmpeg.exe",
            here.parent / "ffmpeg" / "bin" / "ffmpeg.exe",
        ])
    except Exception:
        pass
    # PATH-like common installs
    for base in (
        os.environ.get("LOCALAPPDATA", ""),
        os.environ.get("ProgramFiles", ""),
        r"C:\Program Files",
        r"C:\tools",
    ):
        if base:
            candidates.append(Path(base) / "ffmpeg" / "bin" / "ffmpeg.exe")
    for c in candidates:
        if c and c.is_file():
            return c
    return None


def preview_rename(
    folder: str | Path,
    *,
    tag: str | None = None,
    recursive: bool = True,
    limit: int = 40,
) -> dict:
    """Lista cambios de renombre sin tocar archivos."""
    tag = tag or clubremix_tag()
    files = get_media_files(folder, recursive=recursive)
    changes: list[dict] = []
    same = 0
    for path in files:
        clean = remove_old_membership(path.stem)
        new_name = f"{clean} {tag}{path.suffix}"
        if new_name == path.name:
            same += 1
            continue
        changes.append({
            "from": path.name,
            "to": new_name,
            "dir": str(path.parent),
        })
        if len(changes) >= limit:
            break
    return {
        "ok": True,
        "total": len(files),
        "will_rename": len(files) - same,
        "unchanged": same,
        "tag": tag,
        "sample": changes,
    }


def rename_with_membership(
    folder: str | Path,
    progress_cb: ProgressCb | None = None,
    *,
    tag: str | None = None,
    recursive: bool = True,
    dry_run: bool = False,
    cancel_cb: CancelCb | None = None,
) -> dict:
    """
    Renombra archivos: limpia membresía vieja + agrega tag del mes actual.
    """
    files = get_media_files(folder, recursive=recursive)
    total = len(files)
    tag = tag or clubremix_tag()
    renamed = 0
    skipped = 0
    errors = 0
    cancelled = False
    log: list[str] = []

    for i, path in enumerate(files, 1):
        if cancel_cb and cancel_cb():
            cancelled = True
            break
        if progress_cb:
            try:
                progress_cb(i, total, f"Renombrando {i}/{total}: {path.name[:48]}")
            except Exception:
                pass
        try:
            clean = remove_old_membership(path.stem)
            new_name = f"{clean} {tag}{path.suffix}"
            dest = path.with_name(new_name)
            if dest == path:
                skipped += 1
                continue
            # evitar colisión
            if dest.exists() and dest.resolve() != path.resolve():
                stem = dest.stem
                n = 1
                while dest.exists():
                    dest = path.with_name(f"{stem}_{n}{path.suffix}")
                    n += 1
            if dry_run:
                log.append(f"{path.name} → {dest.name}")
                renamed += 1
            else:
                path.rename(dest)
                renamed += 1
                if len(log) < 30:
                    log.append(f"{path.name} → {dest.name}")
        except Exception as exc:
            errors += 1
            if len(log) < 40:
                log.append(f"ERROR {path.name}: {exc}")

    return {
        "ok": not cancelled,
        "cancelled": cancelled,
        "total": total,
        "renamed": renamed,
        "skipped": skipped,
        "errors": errors,
        "tag": tag,
        "dry_run": dry_run,
        "log": log,
    }


def _update_title_mutagen(path: Path, new_title: str) -> bool:
    """Fallback sin ffmpeg: mutagen (mp3/mp4/flac/ogg)."""
    try:
        from mutagen import File as MFile  # type: ignore
    except Exception:
        return False
    try:
        audio = MFile(path, easy=True)
        if audio is None:
            return False
        audio["title"] = new_title
        audio.save()
        return True
    except Exception:
        return False


def update_titles_with_ffmpeg(
    folder: str | Path,
    ffmpeg: Path | None = None,
    progress_cb: ProgressCb | None = None,
    *,
    tag: str | None = None,
    recursive: bool = True,
    allow_mutagen: bool = True,
    cancel_cb: CancelCb | None = None,
) -> dict:
    """
    Actualiza metadata title con membresía (ffmpeg -c copy, o mutagen).
    """
    ff = ffmpeg or find_ffmpeg()
    files = get_media_files(folder, recursive=recursive)
    total = len(files)
    tag = tag or clubremix_tag()
    updated = 0
    errors = 0
    via_ffmpeg = 0
    via_mutagen = 0
    cancelled = False
    method = "ffmpeg" if ff else ("mutagen" if allow_mutagen else "none")

    if not ff and not allow_mutagen:
        return {
            "ok": False,
            "error": "ffmpeg no encontrado (esperado en C:\\ffmpeg\\bin\\ffmpeg.exe)",
            "total": total,
            "updated": 0,
            "errors": 0,
            "method": method,
        }

    for i, path in enumerate(files, 1):
        if cancel_cb and cancel_cb():
            cancelled = True
            break
        if progress_cb:
            try:
                progress_cb(i, total, f"TITLE {i}/{total}: {path.name[:48]}")
            except Exception:
                pass
        try:
            clean = remove_old_membership(path.stem)
            new_title = f"{clean} {tag}"
            ok = False

            if ff:
                fd, tmp_name = tempfile.mkstemp(
                    suffix=path.suffix, prefix="._dj_", dir=str(path.parent),
                )
                os.close(fd)
                tmp = Path(tmp_name)
                try:
                    cmd = [
                        str(ff), "-y", "-i", str(path),
                        "-map", "0", "-c", "copy",
                        "-metadata", f"title={new_title}",
                        "-metadata", f"TITLE={new_title}",
                        str(tmp),
                    ]
                    r = subprocess.run(
                        cmd,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                    if r.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
                        tmp.replace(path)
                        ok = True
                        via_ffmpeg += 1
                finally:
                    if tmp.exists():
                        try:
                            tmp.unlink()
                        except Exception:
                            pass

            if not ok and allow_mutagen:
                if _update_title_mutagen(path, new_title):
                    ok = True
                    via_mutagen += 1

            if ok:
                updated += 1
            else:
                errors += 1
        except Exception:
            errors += 1

    return {
        "ok": not cancelled,
        "cancelled": cancelled,
        "total": total,
        "updated": updated,
        "errors": errors,
        "tag": tag,
        "ffmpeg": str(ff) if ff else "",
        "method": method,
        "via_ffmpeg": via_ffmpeg,
        "via_mutagen": via_mutagen,
    }


def default_ps1_path() -> Path:
    """Ruta del script original DJTOOLS.ps1 (si existe)."""
    candidates = [
        Path(r"H:\_Desktop\BPM RENAME\DJTOOLS.ps1"),
        Path(__file__).resolve().parent / "DJTOOLS.ps1",
        Path(__file__).resolve().parent.parent / "DJTOOLS.ps1",
    ]
    for p in candidates:
        if p.is_file():
            return p
    return candidates[0]
