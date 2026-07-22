#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ClubRemix DJ Tools — lógica portada de DJTOOLS.ps1
- Renombrar con membresía mensual ClubRemix
- Actualizar metadata title con ffmpeg
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

# MEMBRESIA CLUBREMIX [ENE 2k26 ]
_OLD_MEMBERSHIP = re.compile(
    r"\s*MEMBRESIA\s+CLUBREMIX\s+\[[A-Z]{3}\s+2k\d{2}\s*\]\s*",
    re.IGNORECASE,
)

ProgressCb = Callable[[int, int, str], None]  # current, total, message


def clubremix_tag(when: datetime | None = None) -> str:
    """Genera tag: MEMBRESIA CLUBREMIX [MAR 2k26 ]"""
    when = when or datetime.now()
    meses = ("ENE", "FEB", "MAR", "ABR", "MAY", "JUN",
             "JUL", "AGO", "SEP", "OCT", "NOV", "DIC")
    m = meses[when.month - 1]
    year = f"{when.year % 100:02d}"
    return f"MEMBRESIA CLUBREMIX [{m} 2k{year} ]"


def remove_old_membership(name: str) -> str:
    clean = _OLD_MEMBERSHIP.sub(" ", name or "")
    return re.sub(r"\s{2,}", " ", clean).strip()


def get_media_files(folder: str | Path) -> list[Path]:
    root = Path(folder)
    if not root.is_dir():
        return []
    out: list[Path] = []
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in MEDIA_EXT:
            out.append(p)
    return sorted(out, key=lambda x: str(x).lower())


def find_ffmpeg() -> Path | None:
    candidates = [
        Path(r"C:\ffmpeg\bin\ffmpeg.exe"),
        Path(shutil.which("ffmpeg") or ""),
    ]
    # también junto a la app
    try:
        here = Path(__file__).resolve().parent
        candidates.extend([
            here / "ffmpeg.exe",
            here / "bin" / "ffmpeg.exe",
            here / "_internal" / "ffmpeg.exe",
        ])
    except Exception:
        pass
    for c in candidates:
        if c and c.is_file():
            return c
    return None


def rename_with_membership(
    folder: str | Path,
    progress_cb: ProgressCb | None = None,
) -> dict:
    """
    Renombra archivos: limpia membresía vieja + agrega tag del mes actual.
    """
    files = get_media_files(folder)
    total = len(files)
    tag = clubremix_tag()
    renamed = 0
    skipped = 0
    errors = 0

    for i, path in enumerate(files, 1):
        if progress_cb:
            progress_cb(i, total, f"Renombrando {i}/{total}: {path.name[:48]}")
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
            path.rename(dest)
            renamed += 1
        except Exception:
            errors += 1

    return {
        "ok": True,
        "total": total,
        "renamed": renamed,
        "skipped": skipped,
        "errors": errors,
        "tag": tag,
    }


def update_titles_with_ffmpeg(
    folder: str | Path,
    ffmpeg: Path | None = None,
    progress_cb: ProgressCb | None = None,
) -> dict:
    """
    Actualiza metadata title con membresía (ffmpeg -c copy).
    """
    ff = ffmpeg or find_ffmpeg()
    if not ff:
        return {
            "ok": False,
            "error": "ffmpeg no encontrado (esperado en C:\\ffmpeg\\bin\\ffmpeg.exe)",
            "total": 0,
            "updated": 0,
            "errors": 0,
        }

    files = get_media_files(folder)
    total = len(files)
    tag = clubremix_tag()
    updated = 0
    errors = 0

    for i, path in enumerate(files, 1):
        if progress_cb:
            progress_cb(i, total, f"TITLE {i}/{total}: {path.name[:48]}")
        try:
            clean = remove_old_membership(path.stem)
            new_title = f"{clean} {tag}"
            # temp en misma carpeta
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
                    str(tmp),
                ]
                r = subprocess.run(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                if r.returncode != 0 or not tmp.exists() or tmp.stat().st_size < 1:
                    raise RuntimeError("ffmpeg falló")
                tmp.replace(path)
                updated += 1
            finally:
                if tmp.exists():
                    try:
                        tmp.unlink()
                    except Exception:
                        pass
        except Exception:
            errors += 1

    return {
        "ok": True,
        "total": total,
        "updated": updated,
        "errors": errors,
        "tag": tag,
        "ffmpeg": str(ff),
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
