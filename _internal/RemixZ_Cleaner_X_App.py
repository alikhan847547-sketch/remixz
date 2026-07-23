#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RemixZ Cleaner X — 1 sola opción
================================
- Sin CMD → splash → comprueba/instala deps → bienvenida (updates) → Cleaner
- UNA sola acción: seleccionar carpeta y limpiar
- Limpia nombres + metadatos RemixZ / Tio Dealer / WhatsApp

Uso:
  doble clic en ejecutar_Cleaner_X.vbs
  o: pythonw RemixZ_Cleaner_X_App.py
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import subprocess
import sys
import time
import threading
import traceback
from pathlib import Path


def _hide_console() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    except Exception:
        pass


_hide_console()

if getattr(sys, "frozen", False):
    # Carpeta del .exe (escribible: config, logs, updates)
    APP_DIR = Path(sys.executable).resolve().parent
    # Datos empaquetados por PyInstaller (onefile) o misma carpeta (onedir)
    _MEIPASS = Path(getattr(sys, "_MEIPASS", APP_DIR))
else:
    APP_DIR = Path(__file__).resolve().parent
    _MEIPASS = APP_DIR

# ---------------------------------------------------------------------------
# Paths de dependencias (lib local + vendor wheels + bundle EXE)
# ---------------------------------------------------------------------------
LIB_DIR = APP_DIR / "lib"
VENDOR_DIR = APP_DIR / "vendor"

os.chdir(APP_DIR)


def _bootstrap_sys_path() -> None:
    """
    Añade lib/ y bundle del EXE para mutagen/colorama/psutil.
    NO pone vendor/ en sys.path (solo hay .whl).
    NO elimina rutas del intérprete (stdlib: platform, etc.).
    """
    # En EXE, _MEIPASS debe quedar accesible (base_library / platform)
    ordered = []
    if getattr(sys, "frozen", False):
        ordered.append(Path(getattr(sys, "_MEIPASS", _MEIPASS)))
        ordered.append(APP_DIR / "_internal")
    ordered.extend([LIB_DIR, APP_DIR])
    for p in reversed(ordered):
        try:
            if not p or not Path(p).exists():
                continue
            s = str(Path(p).resolve())
            if sys.path and sys.path[0] == s:
                continue
            if s in sys.path:
                try:
                    sys.path.remove(s)
                except ValueError:
                    pass
            sys.path.insert(0, s)
        except Exception:
            pass


_bootstrap_sys_path()


def _ensure_stdlib() -> None:
    """Garantiza que 'platform' y stdlib básica se puedan importar."""
    _bootstrap_sys_path()
    try:
        import platform as _pl  # noqa: F401
        return
    except Exception:
        pass
    # Restaurar MEIPASS / prefix del intérprete
    extras = []
    if getattr(sys, "frozen", False):
        extras.append(str(Path(getattr(sys, "_MEIPASS", APP_DIR))))
        extras.append(str(APP_DIR / "_internal"))
    for attr in ("base_prefix", "prefix", "exec_prefix"):
        root = getattr(sys, attr, None)
        if root:
            extras.append(str(Path(root) / "Lib"))
            extras.append(str(Path(root) / "lib"))
    for s in extras:
        try:
            if Path(s).exists() and s not in sys.path:
                sys.path.append(s)
        except Exception:
            pass
    import platform as _pl  # noqa: F401

# ---------------------------------------------------------------------------
# Dependencias requeridas por Cleaner X (import_name, pip_name, descripción)
# ---------------------------------------------------------------------------
REQUIRED_PACKAGES: list[tuple[str, str, str]] = [
    ("mutagen", "mutagen", "Metadatos audio/video"),
    ("colorama", "colorama", "Colores consola (motor)"),
    ("psutil", "psutil", "Uso de CPU/hilos"),
    # UI: CustomTkinter + deps (se instalan solas si faltan)
    ("customtkinter", "customtkinter", "Widgets modernos (diseño Fluent)"),
    ("darkdetect", "darkdetect", "Detección tema SO (CustomTkinter)"),
    ("packaging", "packaging", "Versionado de paquetes (CustomTkinter)"),
]


def _module_ok(name: str) -> bool:
    try:
        # invalidar caché de fallos previos
        if name in sys.modules and sys.modules[name] is None:
            del sys.modules[name]
        importlib.import_module(name)
        return True
    except Exception:
        return False


def _python_for_pip() -> str | None:
    """python.exe real (no pythonw / no EXE frozen)."""
    if getattr(sys, "frozen", False):
        # Buscar Python del sistema para instalar en lib/
        candidates = []
        local = os.environ.get("LOCALAPPDATA", "")
        if local:
            for ver in ("Python312", "Python311", "Python313", "Python310"):
                candidates.append(
                    Path(local) / "Programs" / "Python" / ver / "python.exe"
                )
        for c in candidates:
            if c.exists():
                return str(c)
        # py launcher
        return "py"
    exe = Path(sys.executable)
    name = exe.name.lower()
    if name == "pythonw.exe":
        py = exe.with_name("python.exe")
        if py.exists():
            return str(py)
    return str(exe)


def _run_pip(args: list[str], status_cb=None) -> tuple[bool, str]:
    py = _python_for_pip()
    if not py:
        return False, "No hay Python para pip"
    cmd = [py]
    if py == "py":
        cmd += ["-3"]
    cmd += ["-m", "pip", *args, "--disable-pip-version-check", "-q"]
    if status_cb:
        status_cb("pip " + " ".join(args[:6]) + "…")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            creationflags=flags,
            timeout=600,
        )
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "error pip").strip()[:400]
            return False, err
        return True, "OK"
    except FileNotFoundError:
        return False, "Python/pip no encontrado"
    except Exception as exc:
        return False, str(exc)


def _extract_wheel(wheel: Path, dest: Path) -> bool:
    """Extrae un .whl (zip) a dest/."""
    import zipfile
    try:
        dest.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(wheel, "r") as zf:
            zf.extractall(dest)
        return True
    except Exception:
        return False


def _install_from_vendor(packages: list[str], status_cb=None) -> list[str]:
    """Instala desde vendor/*.whl a lib/ (sin internet)."""
    installed = []
    if not VENDOR_DIR.exists():
        return installed
    wheels = list(VENDOR_DIR.glob("*.whl"))
    if not wheels:
        return installed
    LIB_DIR.mkdir(parents=True, exist_ok=True)
    for pkg in packages:
        # buscar wheel del paquete
        match = None
        for w in wheels:
            if w.name.lower().startswith(pkg.lower().replace("-", "_") + "-") or \
               w.name.lower().startswith(pkg.lower() + "-"):
                match = w
                break
        if not match:
            continue
        if status_cb:
            status_cb(f"Instalando {pkg} desde vendor…")
        if _extract_wheel(match, LIB_DIR):
            installed.append(pkg)
    _bootstrap_sys_path()
    # invalidar imports fallidos
    for pkg in packages:
        sys.modules.pop(pkg, None)
    return installed


def _install_via_pip_target(packages: list[str], status_cb=None) -> tuple[bool, str]:
    """pip install --target=lib (funciona con pythonw si hay python.exe)."""
    if not packages:
        return True, "nada"
    LIB_DIR.mkdir(parents=True, exist_ok=True)
    # 1) offline desde vendor
    if VENDOR_DIR.exists() and list(VENDOR_DIR.glob("*.whl")):
        ok, msg = _run_pip(
            [
                "install", "--target", str(LIB_DIR),
                "--upgrade", "--no-index",
                "--find-links", str(VENDOR_DIR),
                *packages,
            ],
            status_cb=status_cb,
        )
        if ok:
            _bootstrap_sys_path()
            for p in packages:
                sys.modules.pop(p, None)
            return True, "vendor"
    # 2) online
    ok, msg = _run_pip(
        ["install", "--target", str(LIB_DIR), "--upgrade", *packages],
        status_cb=status_cb,
    )
    if ok:
        _bootstrap_sys_path()
        for p in packages:
            sys.modules.pop(p, None)
    return ok, msg


def _download_wheels_pypi(packages: list[str], status_cb=None) -> list[str]:
    """Descarga wheels desde PyPI con urllib y extrae a lib/ (sin pip)."""
    import json
    import ssl
    import urllib.request
    import zipfile

    installed = []
    LIB_DIR.mkdir(parents=True, exist_ok=True)
    VENDOR_DIR.mkdir(parents=True, exist_ok=True)
    ctx = ssl.create_default_context()
    ua = "RemixZ-CleanerX/3.1 (+deps)"

    for pkg in packages:
        try:
            if status_cb:
                status_cb(f"Descargando {pkg} desde PyPI…")
            url = f"https://pypi.org/pypi/{pkg}/json"
            req = urllib.request.Request(url, headers={"User-Agent": ua})
            with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
            files = data.get("urls") or []
            # preferir wheel py3 / any / win_amd64
            wheel = None
            for f in files:
                if f.get("packagetype") != "bdist_wheel":
                    continue
                name = str(f.get("filename", "")).lower()
                if "win_arm64" in name:
                    continue
                if "win32" in name and "amd64" not in name and "win_amd64" not in name:
                    continue
                if "win_amd64" in name or "py3-none-any" in name or "py2.py3-none-any" in name:
                    wheel = f
                    if "py3-none-any" in name or "py2.py3-none-any" in name:
                        break
            if not wheel:
                for f in files:
                    if f.get("packagetype") == "bdist_wheel":
                        wheel = f
                        break
            if not wheel or not wheel.get("url"):
                continue
            whl_name = wheel["filename"]
            dest = VENDOR_DIR / whl_name
            req2 = urllib.request.Request(wheel["url"], headers={"User-Agent": ua})
            with urllib.request.urlopen(req2, timeout=120, context=ctx) as r2:
                dest.write_bytes(r2.read())
            with zipfile.ZipFile(dest, "r") as zf:
                zf.extractall(LIB_DIR)
            installed.append(pkg)
            sys.modules.pop(pkg, None)
        except Exception:
            continue
    _bootstrap_sys_path()
    return installed


def check_dependencies() -> dict:
    """Revisa mutagen / colorama / psutil (tras bootstrap de paths)."""
    _bootstrap_sys_path()
    present = []
    missing = []
    for imp, pipn, desc in REQUIRED_PACKAGES:
        if _module_ok(imp):
            present.append((imp, desc))
        else:
            missing.append((imp, pipn, desc))

    tk_ok = True
    try:
        importlib.import_module("tkinter")
    except Exception:
        tk_ok = bool(getattr(sys, "frozen", False))  # en EXE ya corremos con tk

    lines = []
    for imp, desc in present:
        lines.append(f"✓ {imp} — {desc}")
    for imp, _pip, desc in missing:
        lines.append(f"✗ {imp} — {desc} (faltante)")
    if not tk_ok:
        lines.append("✗ tkinter — GUI (faltante)")

    return {
        "ok": not missing and tk_ok,
        "missing": missing,
        "present": present,
        "tkinter": tk_ok,
        "detail": "\n".join(lines) if lines else "Sin paquetes.",
    }


def ensure_packages(status_cb=None, progress_cb=None) -> dict:
    """
    Garantiza mutagen, colorama y psutil:
      1) paths lib/ + _internal + vendor
      2) wheels locales en vendor/
      3) pip install --target=lib
      4) descarga directa PyPI → lib/
    """
    def status(msg: str):
        if status_cb:
            try:
                status_cb(msg)
            except Exception:
                pass

    def progress(p: int):
        if progress_cb:
            try:
                progress_cb(max(0, min(100, int(p))))
            except Exception:
                pass

    progress(5)
    status("Revisando dependencias…")
    _bootstrap_sys_path()
    report = check_dependencies()

    if not report["missing"]:
        status("Dependencias listas")
        progress(100)
        return report

    names = [m[0] for m in report["missing"]]
    installed: list[str] = []
    failed: list[str] = []

    # 1) vendor wheels
    progress(15)
    status(f"Instalando desde vendor: {', '.join(names)}…")
    got = _install_from_vendor(names, status_cb=status)
    installed.extend(got)
    report = check_dependencies()
    names = [m[0] for m in report["missing"]]

    # 2) pip --target=lib
    if names:
        progress(40)
        status(f"Instalando con pip → lib/: {', '.join(names)}…")
        ok, msg = _install_via_pip_target(names, status_cb=status)
        report = check_dependencies()
        still = [m[0] for m in report["missing"]]
        for n in names:
            if n not in still and n not in installed:
                installed.append(n)
        names = still
        if not ok and names:
            failed.append(msg[:120])

    # 3) PyPI directo (sin pip) — clave cuando pythonw / EXE no tienen pip
    if names:
        progress(70)
        status(f"Descarga directa PyPI: {', '.join(names)}…")
        got = _download_wheels_pypi(names, status_cb=status)
        installed.extend(got)
        report = check_dependencies()
        names = [m[0] for m in report["missing"]]

    progress(95)
    final = check_dependencies()
    final["installed"] = installed
    final["failed"] = names  # lo que siga faltando
    final["ok"] = len(final["missing"]) == 0

    # Paquetes de motor (bloqueantes) vs UI opcional
    optional_ui = {"customtkinter", "darkdetect", "packaging"}
    hard_missing = [m for m in final["missing"] if m[0] not in optional_ui]
    soft_missing = [m for m in final["missing"] if m[0] in optional_ui]

    if not hard_missing and not soft_missing:
        final["ok"] = True
        status("Dependencias listas: mutagen · colorama · psutil · customtkinter")
    elif not hard_missing:
        # Solo faltan opcionales de UI → arrancar igual
        final["ok"] = True
        left = ", ".join(m[0] for m in soft_missing)
        status(f"UI opcional pendiente: {left} (Fluent tk puro)")
    else:
        final["ok"] = False
        left = ", ".join(m[0] for m in hard_missing)
        status(f"Aún faltan: {left}")
    progress(100)
    return final


# ---------------------------------------------------------------------------
# UI imports (tkinter must exist; fluent_ui is local)
# ---------------------------------------------------------------------------
import tkinter as tk
from tkinter import filedialog, ttk, scrolledtext

from fluent_ui import (
    FLUENT,
    FONTS,
    FluentUI,
    LoadingSplash,
    RoundedGradientProgress,
    apply_ctk_theme,
    apply_fluent_style,
    ctk_available,
    ensure_ctk_loaded,
    fade_in_window,
    font_or_fallback,
)

# CustomTkinter con la misma paleta (si está instalado); si no, tk puro
try:
    apply_ctk_theme(dict(FLUENT))
except Exception:
    pass
import remixz_update
import remixz_djtools

_local_ver = remixz_update.load_local_version(APP_DIR)
VERSION = str(_local_ver.get("version", "3.2.0"))
APP_TITLE = f"RemixZ Cleaner X v{VERSION}"
REPO_URL = str(_local_ver.get("repo_url") or "https://github.com/alikhan847547-sketch/remixz")

BG = FLUENT["bg"]
BG_INPUT = FLUENT["input"]
FG = FLUENT["fg"]
FG_MUTED = FLUENT["muted"]
ACCENT = FLUENT["accent"]
ACCENT_CYAN = FLUENT["accent_light"]
ACCENT_GREEN = FLUENT["success"]
ACCENT_ORANGE = FLUENT["orange"]

# Motor Cleaner (se carga tras deps)
cleaner = None


def _seed_stdlib_stubs() -> None:
    """
    Inyecta módulos stdlib en sys.modules si el import falla en EXE.
    Evita: ModuleNotFoundError: No module named 'platform'
    al cargar el motor con importlib.
    """
    import types

    # platform
    if "platform" not in sys.modules:
        try:
            import platform as _platform  # noqa: F401
        except Exception:
            stub = types.ModuleType("platform")
            stub.system = lambda: "Windows" if os.name == "nt" else "Unknown"  # type: ignore
            stub.release = lambda: ""  # type: ignore
            stub.version = lambda: ""  # type: ignore
            stub.machine = lambda: "AMD64"  # type: ignore
            stub.processor = lambda: ""  # type: ignore
            stub.node = lambda: ""  # type: ignore
            stub.architecture = lambda: ("64bit", "WindowsPE")  # type: ignore
            stub.python_version = lambda: ".".join(map(str, sys.version_info[:3]))  # type: ignore
            stub.uname = lambda: types.SimpleNamespace(  # type: ignore
                system=stub.system(),
                node="",
                release="",
                version="",
                machine="AMD64",
                processor="",
            )
            sys.modules["platform"] = stub

    # otros stdlib usados por el motor
    for name in (
        "socket", "json", "re", "threading", "subprocess", "shutil",
        "traceback", "datetime", "getpass", "time", "concurrent",
        "concurrent.futures",
    ):
        if name in sys.modules:
            continue
        try:
            importlib.import_module(name)
        except Exception:
            pass


def _log_boot(msg: str) -> None:
    try:
        p = APP_DIR / "boot_error.log"
        with open(p, "a", encoding="utf-8") as f:
            f.write(msg.rstrip() + "\n")
    except Exception:
        pass


def load_cleaner_module():
    """
    Carga el motor Cleaner.
    Orden:
      1) import remixz_cleaner_engine  (embebido en el EXE — preferido)
      2) RemixZ_Cleaner_X_v3.2.py / remixz_cleaner_engine.py en disco
    """
    global cleaner
    if cleaner is not None:
        return cleaner

    _bootstrap_sys_path()
    _seed_stdlib_stubs()
    try:
        _ensure_stdlib()
    except Exception as exc:
        _log_boot(f"ensure_stdlib: {exc}")
        _seed_stdlib_stubs()

    errors: list[str] = []

    # ── 1) Módulo embebido en el EXE (PyInstaller lo analiza al compilar) ──
    try:
        import remixz_cleaner_engine as mod  # type: ignore
        cleaner = mod
        _log_boot("motor: remixz_cleaner_engine (import OK)")
        return cleaner
    except Exception as exc:
        errors.append(f"import remixz_cleaner_engine: {exc}")
        _log_boot(errors[-1])

    # ── 2) Archivo en disco (updates / desarrollo) ─────────────────────────
    candidates = [
        APP_DIR / "remixz_cleaner_engine.py",
        APP_DIR / "RemixZ_Cleaner_X_v3.2.py",
        _MEIPASS / "remixz_cleaner_engine.py",
        _MEIPASS / "RemixZ_Cleaner_X_v3.2.py",
        APP_DIR / "_internal" / "remixz_cleaner_engine.py",
        APP_DIR / "_internal" / "RemixZ_Cleaner_X_v3.2.py",
    ]
    path = next((p for p in candidates if p.exists()), None)
    if path is None:
        msg = "No se encontró el motor (remixz_cleaner_engine / RemixZ_Cleaner_X_v3.2.py)\n" + "\n".join(errors)
        _log_boot(msg)
        raise FileNotFoundError(msg)

    _seed_stdlib_stubs()
    try:
        import types as _types
        # Leer y exec con builtins completos + platform ya en sys.modules
        code = path.read_text(encoding="utf-8", errors="replace")
        if code.startswith("\ufeff"):
            code = code.lstrip("\ufeff")
        module_name = "remixz_cleaner_engine"
        mod = _types.ModuleType(module_name)
        mod.__file__ = str(path)
        mod.__dict__["__builtins__"] = __builtins__
        sys.modules[module_name] = mod
        # Ejecutar en el namespace del módulo (imports resuelven via sys.modules)
        exec(compile(code, str(path), "exec"), mod.__dict__)
        cleaner = mod
        _log_boot(f"motor: exec OK desde {path.name}")
        return cleaner
    except Exception as exc:
        errors.append(f"exec {path.name}: {exc}")
        _log_boot(errors[-1] + "\n" + traceback.format_exc())
        # último intento: importlib clásico
        try:
            _seed_stdlib_stubs()
            spec2 = importlib.util.spec_from_file_location("remixz_cleaner_x", path)
            mod2 = importlib.util.module_from_spec(spec2)
            assert spec2 and spec2.loader
            sys.modules["remixz_cleaner_x"] = mod2
            spec2.loader.exec_module(mod2)
            cleaner = mod2
            _log_boot("motor: importlib OK")
            return cleaner
        except Exception as exc2:
            errors.append(f"importlib: {exc2}")
            _log_boot(errors[-1] + "\n" + traceback.format_exc())
            raise RuntimeError(
                "No se pudo cargar el motor Cleaner.\n" + "\n".join(errors)
            ) from exc2


# ---------------------------------------------------------------------------
# Bridge UI → motor
# ---------------------------------------------------------------------------
class TkCleanerUI:
    def __init__(self, app, log_fn, progress_fn, status_fn):
        self.app = app
        self.log_fn = log_fn
        self.progress_fn = progress_fn
        self.status_fn = status_fn

    def progress_start(self, total, hilos):
        self.app.call_ui(self.log_fn, f"Iniciando: {total} archivos ({hilos} hilos)")
        self.app.call_ui(
            self.progress_fn, 0,
            current=0, total=total, phase="Iniciando limpieza…", detail_pct=0,
        )
        self.app.call_ui(self.status_fn, f"Limpiando con {hilos} hilos…")

    def progress_update(self, actual, total, nombre, tiempo_inicio):
        pct = int(actual / total * 100) if total else 0
        self.app.call_ui(
            self.progress_fn, pct,
            current=actual, total=total,
            phase="Limpiando archivos",
            detail_pct=pct,
        )
        short = (nombre or "")[:56]
        self.app.call_ui(self.status_fn, f"{actual}/{total}  ·  {short}")

    def log_file(self, nombre, acciones):
        txt = ", ".join(acciones) if acciones else "OK"
        self.app.call_ui(self.log_fn, f"OK: {nombre} → {txt}")

    def log_error(self, nombre):
        self.app.call_ui(self.log_fn, f"Error: {nombre}")

    def report_final(self, total, corregidos, errores, tiempo_total):
        self.app.call_ui(
            self.progress_fn, 100,
            current=total, total=total,
            phase="Completado", detail_pct=100,
        )
        self.app.call_ui(
            self.log_fn,
            f"Listo: {corregidos}/{total} corregidos | Errores: {errores} | {tiempo_total:.1f}s",
        )
        self.app.call_ui(self.status_fn, "Limpieza completada.")
        self.app.call_ui(
            self.app.notify,
            "Limpieza completada",
            f"Corregidos: {corregidos}\nTotal: {total}\nErrores: {errores}",
            kind="success",
            buttons=[("OK", "ok")],
        )


def restart_application() -> None:
    """
    Cierra la app actual y la vuelve a lanzar (script, VBS o EXE).
    Tras un update SIEMPRE se usa esto — no dejar la UI vieja abierta.
    """
    cwd = str(APP_DIR)
    cmd: list[str] = []
    try:
        if getattr(sys, "frozen", False):
            cmd = [sys.executable]
        else:
            # Preferir launcher VBS (sin consola) → pythonw script
            vbs = APP_DIR / "ejecutar_Cleaner_X.vbs"
            bat = APP_DIR / "ejecutar_Cleaner_X.bat"
            script = APP_DIR / "RemixZ_Cleaner_X_App.py"
            if os.name == "nt" and vbs.exists():
                cmd = ["wscript.exe", str(vbs)]
            elif os.name == "nt" and bat.exists():
                cmd = ["cmd.exe", "/c", str(bat)]
            else:
                exe = sys.executable
                if os.name == "nt" and exe.lower().endswith("python.exe"):
                    pyw = exe[:-10] + "pythonw.exe"
                    if Path(pyw).exists():
                        exe = pyw
                cmd = [exe, str(script)]

        flags = 0
        if os.name == "nt":
            flags = (
                getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
                | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            )
        # Pequeña espera en proceso hijo: dar tiempo a liberar .py/.pyd
        if os.name == "nt":
            # cmd /c timeout then start — más fiable tras overwrite de update
            inner = subprocess.list2cmdline(cmd)
            wrapper = f'ping -n 2 127.0.0.1 >nul & {inner}'
            subprocess.Popen(
                ["cmd.exe", "/c", wrapper],
                cwd=cwd,
                close_fds=True,
                creationflags=flags,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )
        else:
            subprocess.Popen(
                cmd,
                cwd=cwd,
                close_fds=True,
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )
        _log_boot(f"restart_application: launched {cmd!r}")
    except Exception as exc:
        try:
            _log_boot(f"restart_application FAIL: {exc}")
        except Exception:
            pass
    try:
        os._exit(0)
    except Exception:
        sys.exit(0)


# ---------------------------------------------------------------------------
# Ventana de progreso de UPDATE (Fluent) — se ve al pulsar Aplicar
# ---------------------------------------------------------------------------
class UpdateProgressWindow(tk.Toplevel):
    """Ventana modal con barra + log de lo que hace el update."""

    PHASES = (
        (0, 49, "Descargando"),
        (50, 64, "Extrayendo"),
        (65, 95, "Aplicando archivos"),
        (96, 100, "Finalizando"),
    )

    def __init__(self, parent: tk.Misc, remote_label: str = ""):
        super().__init__(parent)
        self.parent_app = parent
        self.result = None
        self._closed = False
        self.transient(parent)
        self.resizable(False, False)
        self.configure(bg=BG)
        self.title("RemixZ — Aplicando update")
        self.protocol("WM_DELETE_WINDOW", lambda: None)  # no cerrar a medias
        try:
            self.attributes("-topmost", True)
        except tk.TclError:
            pass

        c = FLUENT
        outer = tk.Frame(self, bg=c["border"])
        outer.pack(fill="both", expand=True)
        root = tk.Frame(outer, bg=c["surface"])
        root.pack(fill="both", expand=True, padx=1, pady=1)

        # Header
        header = tk.Frame(root, bg=c["header"], height=58)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Frame(header, bg=ACCENT_GREEN, width=4).pack(side="left", fill="y")
        hl = tk.Frame(header, bg=c["header"])
        hl.pack(side="left", fill="y", padx=(14, 0), pady=10)
        tk.Label(
            hl, text="REMIXZ", font=("Segoe UI Black", 14),
            fg=ACCENT_CYAN, bg=c["header"],
        ).pack(anchor="w")
        tk.Label(
            hl, text="Aplicando actualización", font=("Segoe UI", 9),
            fg=c["muted"], bg=c["header"],
        ).pack(anchor="w")
        tk.Frame(root, bg=ACCENT_GREEN, height=2).pack(fill="x")

        body = tk.Frame(root, bg=c["surface"])
        body.pack(fill="both", expand=True, padx=20, pady=16)

        self.phase_lbl = tk.Label(
            body, text="Preparando…", font=("Segoe UI Semibold", 13),
            fg=ACCENT_CYAN, bg=c["surface"], anchor="w",
        )
        self.phase_lbl.pack(fill="x")
        sub = f"Remoto: {remote_label}" if remote_label else "Descarga desde GitHub"
        self.sub_lbl = tk.Label(
            body, text=sub, font=("Segoe UI", 9),
            fg=FG_MUTED, bg=c["surface"], anchor="w",
        )
        self.sub_lbl.pack(fill="x", pady=(2, 12))

        # Barra redondeada + degradado
        prow = tk.Frame(body, bg=c["surface"])
        prow.pack(fill="x")
        self.prog = RoundedGradientProgress(
            prow,
            height=12,
            maximum=100,
            mode="determinate",
            colors=c,
            gradient=(c["accent"], c["cyan"]),
            bg=c["surface"],
        )
        self.prog.pack(side="left", fill="x", expand=True)
        self.pct_lbl = tk.Label(
            prow, text="0%", font=("Segoe UI Semibold", 11),
            fg=ACCENT_CYAN, bg=c["surface"], width=5,
        )
        self.pct_lbl.pack(side="right", padx=(10, 0))

        self.detail_lbl = tk.Label(
            body, text="Iniciando…", font=("Segoe UI", 9),
            fg=FG_MUTED, bg=c["surface"], anchor="w", wraplength=440, justify="left",
        )
        self.detail_lbl.pack(fill="x", pady=(8, 10))

        # Log de pasos
        log_shell = tk.Frame(
            body, bg=c["card"],
            highlightthickness=1, highlightbackground=c["border"],
        )
        log_shell.pack(fill="both", expand=True)
        tk.Label(
            log_shell, text="  Actividad", font=("Segoe UI Semibold", 9),
            fg=ACCENT_CYAN, bg=c["card"], anchor="w",
        ).pack(fill="x", padx=8, pady=(8, 2))
        self.log = scrolledtext.ScrolledText(
            log_shell, height=8, font=("Consolas", 9),
            bg=BG_INPUT, fg=FG, insertbackground=FG,
            relief="flat", highlightthickness=0, state="disabled",
        )
        self.log.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        # Botones (aparecen al terminar)
        self.btn_row = tk.Frame(body, bg=c["surface"])
        self.btn_row.pack(fill="x", pady=(12, 0))
        self.fluent = FluentUI(dict(FLUENT), root=self)
        self.btn_restart = None
        self.btn_later = None

        foot = tk.Frame(root, bg=c["header"], height=26)
        foot.pack(fill="x", side="bottom")
        foot.pack_propagate(False)
        tk.Label(
            foot, text=f"Cleaner X  ·  v{VERSION}",
            font=("Segoe UI", 8), fg=FG_MUTED, bg=c["header"],
        ).pack(side="left", padx=12, pady=4)

        self.update_idletasks()
        w, h = 520, 420
        try:
            px = parent.winfo_rootx() + max(0, (parent.winfo_width() - w) // 2)
            py = parent.winfo_rooty() + max(0, (parent.winfo_height() - h) // 2)
        except Exception:
            px = (self.winfo_screenwidth() - w) // 2
            py = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{max(0, px)}+{max(0, py)}")
        try:
            self.grab_set()
        except tk.TclError:
            pass
        try:
            fade_in_window(self, steps=8, delay_ms=14)
        except Exception:
            pass
        self._log_line("Ventana de update abierta")
        self._log_line("Esperando inicio de descarga…")
        self.focus_force()

    def _log_line(self, text: str):
        try:
            self.log.configure(state="normal")
            self.log.insert("end", f"• {text}\n")
            self.log.see("end")
            self.log.configure(state="disabled")
        except Exception:
            pass

    def set_progress(self, pct: int, message: str = ""):
        if self._closed:
            return
        pct = max(0, min(100, int(pct)))
        try:
            self.prog.set(pct)
            self.pct_lbl.configure(text=f"{pct}%")
            phase = "Procesando"
            color = ACCENT_CYAN
            for a, b, name in self.PHASES:
                if a <= pct <= b:
                    phase = name
                    color = ACCENT_GREEN if pct >= 96 else (
                        ACCENT_ORANGE if pct >= 50 else ACCENT_CYAN
                    )
                    break
            self.phase_lbl.configure(text=phase, fg=color)
            if message:
                self.detail_lbl.configure(text=message)
                # Evitar spam: solo loguear cambios relevantes
                short = message[:90]
                last = getattr(self, "_last_log", "")
                if short != last and (
                    pct in (0, 2, 50, 65, 96, 100)
                    or "completa" in short.lower()
                    or "error" in short.lower()
                    or "aplicado" in short.lower()
                    or pct % 20 == 0
                ):
                    self._last_log = short
                    self._log_line(f"[{pct}%] {short}")
        except Exception:
            pass

    def finish_ok(
        self,
        message: str,
        on_restart=None,
        on_later=None,
        *,
        auto_restart: bool = True,
        auto_delay_ms: int = 2000,
    ):
        self._log_line("✓ Update completado")
        self._log_line(message)
        self.phase_lbl.configure(text="Update aplicado", fg=ACCENT_GREEN)
        self.prog.set(100)
        self.pct_lbl.configure(text="100%")

        for w in self.btn_row.winfo_children():
            w.destroy()

        if auto_restart:
            # Reinicio automático: no pedir confirmación
            self.detail_lbl.configure(
                text=f"{message}\n\nReiniciando automáticamente…"
            )
            self.protocol("WM_DELETE_WINDOW", lambda: None)  # bloquear cierre manual
            self.btn_restart = self.fluent.button(
                self.btn_row, "  Reiniciando…  ",
                lambda: None,
                kind="success", width=16,
            )
            self.btn_restart.pack(side="right")
            try:
                self.btn_restart.configure(state="disabled")
            except Exception:
                pass
            self._log_line("Reinicio automático en marcha…")
            delay = max(400, int(auto_delay_ms))
            self.after(delay, lambda: self._done("restart", on_restart))
            return

        self.detail_lbl.configure(text=message)
        self.protocol("WM_DELETE_WINDOW", lambda: self._done("later", on_later))
        self.btn_later = self.fluent.button(
            self.btn_row, "  Continuar sin reiniciar  ",
            lambda: self._done("later", on_later),
            kind="standard", width=20,
        )
        self.btn_later.pack(side="right", padx=(8, 0))
        self.btn_restart = self.fluent.button(
            self.btn_row, "  Reiniciar ahora  ",
            lambda: self._done("restart", on_restart),
            kind="success", width=16,
        )
        self.btn_restart.pack(side="right")
        self._log_line("Pulsa «Reiniciar ahora» para recargar la app.")

    def finish_error(self, message: str, on_close=None):
        self._log_line(f"✗ Error: {message}")
        self.phase_lbl.configure(text="Error al actualizar", fg="#ff6666")
        self.detail_lbl.configure(text=message)
        self.protocol("WM_DELETE_WINDOW", lambda: self._done("close", on_close))
        for w in self.btn_row.winfo_children():
            w.destroy()
        self.fluent.button(
            self.btn_row, "  Cerrar  ",
            lambda: self._done("close", on_close),
            kind="standard", width=12,
        ).pack(side="right")

    def _done(self, key: str, cb=None):
        if self._closed:
            return
        self._closed = True
        self.result = key
        try:
            self.grab_release()
        except Exception:
            pass
        try:
            self.destroy()
        except Exception:
            pass
        if cb:
            try:
                cb()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Notificación Fluent (mismo diseño GUI)
# ---------------------------------------------------------------------------
class FluentNotify(tk.Toplevel):
    KIND = {
        "info":    {"color": FLUENT["accent_light"], "tag": "INFO",   "icon": "i"},
        "success": {"color": FLUENT["success"],      "tag": "OK",     "icon": "✓"},
        "warning": {"color": FLUENT["orange"],       "tag": "AVISO",  "icon": "!"},
        "error":   {"color": FLUENT["error"],        "tag": "ERROR",  "icon": "×"},
        "update":  {"color": FLUENT["success"],      "tag": "UPDATE", "icon": "↑"},
    }

    def __init__(
        self,
        parent: tk.Misc,
        title: str,
        message: str,
        *,
        kind: str = "info",
        buttons: list[tuple[str, str]] | None = None,
        on_result=None,
    ):
        super().__init__(parent)
        self.result = None
        self.on_result = on_result
        self.transient(parent)
        self.resizable(False, False)
        self.configure(bg=BG)
        self.title(title)
        self.protocol("WM_DELETE_WINDOW", lambda: self._close("ok"))
        try:
            self.attributes("-topmost", True)
        except tk.TclError:
            pass

        meta = self.KIND.get(kind, self.KIND["info"])
        accent = meta["color"]
        c = FLUENT

        outer = tk.Frame(self, bg=c["border"])
        outer.pack(fill="both", expand=True)
        root = tk.Frame(outer, bg=c["surface"])
        root.pack(fill="both", expand=True, padx=1, pady=1)

        header = tk.Frame(root, bg=c["header"], height=58)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Frame(header, bg=accent, width=4).pack(side="left", fill="y")

        head_left = tk.Frame(header, bg=c["header"])
        head_left.pack(side="left", fill="y", padx=(14, 0), pady=10)
        tk.Label(
            head_left, text="REMIXZ", font=("Segoe UI Black", 14),
            fg=c["accent_light"], bg=c["header"], anchor="w",
        ).pack(anchor="w")
        tk.Label(
            head_left, text=title, font=("Segoe UI", 9),
            fg=c["muted"], bg=c["header"], anchor="w",
        ).pack(anchor="w")

        head_right = tk.Frame(header, bg=c["header"])
        head_right.pack(side="right", padx=14, pady=12)
        badge = tk.Frame(
            head_right, bg=c["input"],
            highlightthickness=1, highlightbackground=accent,
        )
        badge.pack()
        tk.Label(
            badge, text=f"  {meta['icon']}  {meta['tag']}  ",
            font=("Segoe UI Semibold", 8), fg=accent, bg=c["input"],
        ).pack(padx=2, pady=4)

        tk.Frame(root, bg=accent, height=2).pack(fill="x")

        body = tk.Frame(root, bg=c["surface"])
        body.pack(fill="both", expand=True, padx=20, pady=16)

        card = tk.Frame(
            body, bg=c["card"],
            highlightthickness=1, highlightbackground=c["border"],
        )
        card.pack(fill="both", expand=True)
        card_inner = tk.Frame(card, bg=c["card"])
        card_inner.pack(fill="both", expand=True, padx=14, pady=14)
        tk.Frame(card_inner, bg=accent, width=3).pack(side="left", fill="y", padx=(0, 12))
        msg_col = tk.Frame(card_inner, bg=c["card"])
        msg_col.pack(side="left", fill="both", expand=True)
        tk.Label(
            msg_col, text=title, font=("Segoe UI Semibold", 12),
            fg=FG, bg=c["card"], anchor="w",
        ).pack(fill="x")
        tk.Label(
            msg_col, text=message, font=("Segoe UI", 10),
            fg=FG_MUTED, bg=c["card"], justify="left", anchor="nw", wraplength=400,
        ).pack(fill="both", expand=True, pady=(8, 0))

        btn_row = tk.Frame(body, bg=c["surface"])
        btn_row.pack(fill="x", pady=(14, 0))
        fluent = FluentUI(dict(FLUENT), root=self)
        buttons = buttons or [("OK", "ok")]
        for i, (label, key) in enumerate(reversed(buttons)):
            if key in ("ok", "yes", "apply"):
                kind_btn = "success"
            elif key in ("no", "cancel"):
                kind_btn = "standard"
            else:
                kind_btn = "subtle"
            b = fluent.button(
                btn_row, f"  {label}  ",
                lambda k=key: self._close(k),
                kind=kind_btn, width=12,
            )
            b.pack(side="right", padx=(8, 0) if i else 0)

        foot = tk.Frame(root, bg=c["header"], height=26)
        foot.pack(fill="x", side="bottom")
        foot.pack_propagate(False)
        tk.Label(
            foot, text=f"Cleaner X  ·  v{VERSION}",
            font=("Segoe UI", 8), fg=FG_MUTED, bg=c["header"],
        ).pack(side="left", padx=12, pady=4)

        self.update_idletasks()
        w = 500
        need_h = max(280, root.winfo_reqheight() + 4)
        h = min(need_h, 440)
        try:
            px = parent.winfo_rootx() + max(0, (parent.winfo_width() - w) // 2)
            py = parent.winfo_rooty() + max(0, (parent.winfo_height() - h) // 2)
        except Exception:
            px = (self.winfo_screenwidth() - w) // 2
            py = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{max(0, px)}+{max(0, py)}")
        try:
            self.grab_set()
        except tk.TclError:
            pass
        try:
            fade_in_window(self, steps=8, delay_ms=14)
        except Exception:
            pass
        self.focus_force()
        try:
            self.bind("<Return>", lambda _e: self._close(buttons[-1][1]))
            self.bind("<Escape>", lambda _e: self._close(buttons[0][1]))
        except Exception:
            pass

    def _close(self, key: str):
        self.result = key
        try:
            self.attributes("-topmost", False)
        except tk.TclError:
            pass
        try:
            self.grab_release()
        except Exception:
            pass
        cb = self.on_result
        self.destroy()
        if cb:
            try:
                cb(key)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Password maestro (pruebas ClubRemix)
# ---------------------------------------------------------------------------
class MasterPasswordDialog(tk.Toplevel):
    """Pide password maestro antes de abrir DJ Tools."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        title: str,
        message: str,
        expected: str,
        on_result=None,
    ):
        super().__init__(parent)
        self.on_result = on_result
        self.expected = str(expected)
        self.result_ok = False
        self.title(title)
        self.configure(bg=BG)
        self.resizable(False, False)
        self.transient(parent)
        try:
            self.grab_set()
        except Exception:
            pass
        try:
            self.attributes("-topmost", True)
        except tk.TclError:
            pass

        outer = tk.Frame(self, bg=FLUENT["border"])
        outer.pack(fill="both", expand=True)
        root = tk.Frame(outer, bg=FLUENT["card"])
        root.pack(fill="both", expand=True, padx=1, pady=1)

        head = tk.Frame(root, bg=FLUENT["header"], height=52)
        head.pack(fill="x")
        head.pack_propagate(False)
        tk.Frame(head, bg=ACCENT, width=3).pack(side="left", fill="y")
        tk.Label(
            head, text="  🔒  ClubRemix · Bloqueado",
            font=("Segoe UI Semibold", 12), fg=FG, bg=FLUENT["header"],
        ).pack(side="left", padx=10)

        body = tk.Frame(root, bg=FLUENT["card"])
        body.pack(fill="both", expand=True, padx=20, pady=16)
        tk.Label(
            body, text=message,
            font=("Segoe UI", 10), fg=FG_MUTED, bg=FLUENT["card"],
            justify="left", wraplength=360,
        ).pack(anchor="w", pady=(0, 12))

        tk.Label(
            body, text="CÓDIGO DE ACCESO (si aplica)",
            font=("Segoe UI", 8), fg=FLUENT.get("text_dim", FG_MUTED), bg=FLUENT["card"],
        ).pack(anchor="w")
        self.entry = tk.Entry(
            body,
            font=("Segoe UI", 12),
            show="●",
            bg=FLUENT["input"], fg=FG,
            insertbackground=FG,
            relief="flat",
            highlightthickness=1,
            highlightbackground=FLUENT["border"],
            highlightcolor=ACCENT,
        )
        self.entry.pack(fill="x", ipady=8, pady=(4, 6))
        self.err_lbl = tk.Label(
            body, text="", font=("Segoe UI", 9),
            fg="#ff6b7a", bg=FLUENT["card"],
        )
        self.err_lbl.pack(anchor="w")

        btns = tk.Frame(body, bg=FLUENT["card"])
        btns.pack(fill="x", pady=(14, 0))
        fluent = FluentUI(dict(FLUENT), root=self)
        fluent.button(btns, "  Cerrar  ", self._cancel, kind="standard", width=12).pack(
            side="right", padx=(8, 0)
        )
        fluent.button(btns, "  Continuar  ", self._ok, kind="accent", width=12).pack(side="right")

        self.entry.bind("<Return>", lambda _e: self._ok())
        self.entry.bind("<Escape>", lambda _e: self._cancel())
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        self.update_idletasks()
        w, h = 420, 260
        try:
            px = parent.winfo_rootx() + max(0, (parent.winfo_width() - w) // 2)
            py = parent.winfo_rooty() + max(0, (parent.winfo_height() - h) // 2)
            self.geometry(f"{w}x{h}+{max(0, px)}+{max(0, py)}")
        except Exception:
            self.geometry(f"{w}x{h}")
        self.after(80, self.entry.focus_force)

    def _finish(self, ok: bool):
        self.result_ok = ok
        cb = self.on_result
        try:
            self.grab_release()
        except Exception:
            pass
        try:
            self.destroy()
        except Exception:
            pass
        if cb:
            try:
                cb(ok)
            except Exception:
                pass

    def _ok(self):
        val = (self.entry.get() or "").strip()
        if val == self.expected:
            self._finish(True)
        else:
            self.err_lbl.configure(text="Password incorrecto. Intenta de nuevo.")
            self.entry.delete(0, "end")
            self.entry.focus_force()

    def _cancel(self):
        self._finish(False)


# ---------------------------------------------------------------------------
# ClubRemix DJ Tools (port de DJTOOLS.ps1) — misma UI
# ---------------------------------------------------------------------------
class DJToolsWindow(tk.Toplevel):
    """Panel independiente: renombrar membresía + actualizar TITLE."""

    def __init__(self, parent: "CleanerXApp"):
        super().__init__(parent)
        self.parent_app = parent
        self.title(f"ClubRemix DJ Tools  ·  v{VERSION}")
        self.geometry("640x520")
        self.minsize(560, 460)
        self.configure(bg=BG)
        self._busy = False
        self._folder = ""
        self.fluent = FluentUI(dict(FLUENT), root=self)

        ico = APP_DIR / "icono.ico"
        if ico.exists():
            try:
                self.iconbitmap(str(ico))
            except Exception:
                pass

        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        try:
            self.transient(parent)
        except Exception:
            pass
        self.update_idletasks()
        try:
            px = parent.winfo_rootx() + max(0, (parent.winfo_width() - 640) // 2)
            py = parent.winfo_rooty() + max(0, (parent.winfo_height() - 520) // 2)
            self.geometry(f"+{max(0, px)}+{max(0, py)}")
        except Exception:
            pass
        try:
            fade_in_window(self, steps=8, delay_ms=14)
        except Exception:
            pass
        self.focus_force()

    def _on_close(self):
        if self._busy:
            return
        try:
            self.parent_app._dj_win = None
        except Exception:
            pass
        self.destroy()

    def _build(self):
        # Header
        head = tk.Frame(self, bg=FLUENT["header"], height=64)
        head.pack(fill="x")
        head.pack_propagate(False)
        tk.Frame(head, bg=ACCENT, width=3).pack(side="left", fill="y")
        if getattr(self.parent_app, "_img_logo_header", None) is not None:
            img = self.parent_app._img_logo_header
            lbl = tk.Label(head, image=img, bg=FLUENT["header"], bd=0)
            lbl.image = img
            lbl.pack(side="left", padx=(12, 8), pady=12)
        left = tk.Frame(head, bg=FLUENT["header"])
        left.pack(side="left", pady=12)
        tk.Label(
            left, text="ClubRemix DJ Tools",
            font=("Segoe UI Black", 14), fg=FG, bg=FLUENT["header"],
        ).pack(anchor="w")
        tk.Label(
            left, text="Membresía automática · renombrar · TITLE (ffmpeg)",
            font=("Segoe UI", 8), fg=FG_MUTED, bg=FLUENT["header"],
        ).pack(anchor="w")
        tag = remixz_djtools.clubremix_tag()
        tk.Label(
            head, text=tag,
            font=("Segoe UI Semibold", 8), fg=ACCENT_CYAN, bg=FLUENT["header"],
        ).pack(side="right", padx=14)
        tk.Frame(self, bg=ACCENT, height=1).pack(fill="x")

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=20, pady=16)

        # Carpeta
        tk.Label(
            body, text="CARPETA DE ARCHIVOS",
            font=("Segoe UI Semibold", 8), fg=FLUENT.get("text_dim", FG_MUTED), bg=BG,
        ).pack(anchor="w")
        folder_row = tk.Frame(body, bg=BG)
        folder_row.pack(fill="x", pady=(6, 12))
        self.folder_lbl = tk.Label(
            folder_row,
            text="Ninguna seleccionada",
            font=("Segoe UI", 9), fg=FG_MUTED, bg=FLUENT["input"],
            anchor="w", padx=12, pady=10,
            highlightthickness=1, highlightbackground=FLUENT["border"],
        )
        self.folder_lbl.pack(side="left", fill="x", expand=True)
        self.fluent.button(
            folder_row, "  Examinar  ", self._browse, kind="standard", width=12,
        ).pack(side="right", padx=(10, 0))

        # Estado DJ
        status_card = tk.Frame(
            body, bg=FLUENT["card"],
            highlightthickness=1, highlightbackground=FLUENT["border"],
        )
        status_card.pack(fill="x", pady=(0, 12))
        tk.Frame(status_card, bg=ACCENT, height=2).pack(fill="x")
        sc = tk.Frame(status_card, bg=FLUENT["card"])
        sc.pack(fill="x", padx=14, pady=12)
        tk.Label(
            sc, text="ESTADO DJ", font=("Segoe UI Semibold", 8),
            fg=FLUENT.get("text_dim", FG_MUTED), bg=FLUENT["card"],
        ).pack(anchor="w")
        self.dj_status = tk.Label(
            sc, text="DJ READY 🎧",
            font=("Segoe UI Semibold", 12), fg=ACCENT_CYAN, bg=FLUENT["card"],
        )
        self.dj_status.pack(anchor="w", pady=(4, 0))
        self.detail = tk.Label(
            sc, text="Elige carpeta y una acción.",
            font=("Segoe UI", 9), fg=FG_MUTED, bg=FLUENT["card"],
        )
        self.detail.pack(anchor="w", pady=(2, 0))

        # Acciones
        btn_row = tk.Frame(body, bg=BG)
        btn_row.pack(fill="x", pady=(0, 12))
        self.btn_rename = self.fluent.button(
            btn_row, "  Renombrar archivos  ", self._do_rename, kind="accent", width=20,
        )
        self.btn_rename.pack(side="left")
        self.btn_title = self.fluent.button(
            btn_row, "  Actualizar TITLE  ", self._do_title, kind="success", width=20,
        )
        self.btn_title.pack(side="left", padx=(10, 0))
        self.fluent.button(
            btn_row, "  Cerrar  ", self._on_close, kind="standard", width=10,
        ).pack(side="right")

        # Progreso
        tk.Label(
            body, text="PROGRESO",
            font=("Segoe UI Semibold", 8), fg=FLUENT.get("text_dim", FG_MUTED), bg=BG,
        ).pack(anchor="w")
        self.prog = RoundedGradientProgress(
            body, height=12, maximum=100, mode="determinate",
            colors=dict(FLUENT),
            gradient=(FLUENT["accent"], FLUENT["cyan"]),
            bg=BG,
        )
        self.prog.pack(fill="x", pady=(6, 4))
        self.pct_lbl = tk.Label(
            body, text="0%", font=("Segoe UI Semibold", 9),
            fg=ACCENT_CYAN, bg=BG, anchor="e",
        )
        self.pct_lbl.pack(fill="x")

        # ffmpeg hint
        ff = remixz_djtools.find_ffmpeg()
        ff_txt = f"ffmpeg: {ff}" if ff else "ffmpeg: no encontrado (C:\\ffmpeg\\bin\\ffmpeg.exe)"
        tk.Label(
            body, text=ff_txt,
            font=("Consolas", 8),
            fg=ACCENT_GREEN if ff else ACCENT_ORANGE,
            bg=BG, anchor="w",
        ).pack(fill="x", pady=(8, 0))

        foot = tk.Frame(self, bg=FLUENT["header"], height=28)
        foot.pack(side="bottom", fill="x")
        foot.pack_propagate(False)
        tk.Label(
            foot, text="Fuente: DJTOOLS.ps1  ·  ClubRemix DJ Edition",
            font=("Segoe UI", 8), fg=FG_MUTED, bg=FLUENT["header"],
        ).pack(side="left", padx=12, pady=5)

    def _browse(self):
        folder = filedialog.askdirectory(
            title="Carpeta para ClubRemix DJ Tools",
            initialdir=self._folder or str(APP_DIR),
            parent=self,
        )
        if not folder:
            return
        self._folder = folder
        self.folder_lbl.configure(text=folder, fg=FG)
        n = len(remixz_djtools.get_media_files(folder))
        self.detail.configure(text=f"{n} archivos multimedia detectados.")

    def _set_busy(self, busy: bool):
        self._busy = busy
        state = "disabled" if busy else "normal"
        for b in (self.btn_rename, self.btn_title):
            try:
                b.configure(state=state)
            except Exception:
                pass

    def _progress(self, cur: int, total: int, msg: str):
        pct = int(cur / total * 100) if total else 0

        def ui():
            try:
                self.prog.set(pct)
                self.pct_lbl.configure(text=f"{pct}%")
                self.detail.configure(text=msg)
                self.dj_status.configure(text="DJ MIXING…  ▂ ▄ ▆ █ ▆ ▄ ▂", fg=ACCENT)
            except Exception:
                pass

        self.after(0, ui)

    def _do_rename(self):
        if self._busy:
            return
        if not self._folder:
            self.detail.configure(text="Selecciona una carpeta primero.")
            return
        self._set_busy(True)
        self.dj_status.configure(text="DJ MIXING…", fg=ACCENT)
        self.prog.set(0)

        def worker():
            try:
                result = remixz_djtools.rename_with_membership(
                    self._folder, progress_cb=self._progress,
                )
            except Exception as exc:
                result = {"ok": False, "error": str(exc)}

            def done():
                self._set_busy(False)
                self.dj_status.configure(text="DJ READY 🎧", fg=ACCENT_CYAN)
                if not result.get("ok", True) and result.get("error"):
                    self.detail.configure(text=result["error"])
                    return
                self.prog.set(100)
                self.pct_lbl.configure(text="100%")
                self.detail.configure(
                    text=(
                        f"Renombrado ✔  {result.get('renamed', 0)}/{result.get('total', 0)}  "
                        f"| skip {result.get('skipped', 0)}  | err {result.get('errors', 0)}\n"
                        f"Tag: {result.get('tag', '')}"
                    )
                )
                try:
                    self.parent_app._append_log(
                        f"DJ Tools rename: {result.get('renamed')}/{result.get('total')} · {result.get('tag')}"
                    )
                except Exception:
                    pass

            self.after(0, done)

        threading.Thread(target=worker, daemon=True).start()

    def _do_title(self):
        if self._busy:
            return
        if not self._folder:
            self.detail.configure(text="Selecciona una carpeta primero.")
            return
        if not remixz_djtools.find_ffmpeg():
            self.detail.configure(
                text="ffmpeg no encontrado en C:\\ffmpeg\\bin\\ffmpeg.exe"
            )
            self.dj_status.configure(text="DJ ERROR", fg="#ff6b7a")
            return
        self._set_busy(True)
        self.dj_status.configure(text="DJ MIXING…", fg=ACCENT)
        self.prog.set(0)

        def worker():
            try:
                result = remixz_djtools.update_titles_with_ffmpeg(
                    self._folder, progress_cb=self._progress,
                )
            except Exception as exc:
                result = {"ok": False, "error": str(exc)}

            def done():
                self._set_busy(False)
                self.dj_status.configure(text="DJ READY 🎧", fg=ACCENT_CYAN)
                if not result.get("ok"):
                    self.detail.configure(text=result.get("error") or "Error al actualizar TITLE")
                    return
                self.prog.set(100)
                self.pct_lbl.configure(text="100%")
                self.detail.configure(
                    text=(
                        f"TITLE actualizado ✔  {result.get('updated', 0)}/{result.get('total', 0)}  "
                        f"| err {result.get('errors', 0)}\n"
                        f"Tag: {result.get('tag', '')}"
                    )
                )
                try:
                    self.parent_app._append_log(
                        f"DJ Tools TITLE: {result.get('updated')}/{result.get('total')} · {result.get('tag')}"
                    )
                except Exception:
                    pass

            self.after(0, done)

        threading.Thread(target=worker, daemon=True).start()


# ---------------------------------------------------------------------------
# App principal
# ---------------------------------------------------------------------------
class CleanerXApp(tk.Tk):
    """Bienvenida (updates) → notificación Fluent → Cleaner (1 opción)."""

    def __init__(self, *, start_hidden: bool = False, dep_report: dict | None = None):
        super().__init__()
        if start_hidden:
            self.withdraw()

        self.title(APP_TITLE)
        self.geometry("920x720")
        self.minsize(840, 640)
        self.configure(bg=BG)

        # Icono si existe
        ico = APP_DIR / "icono.ico"
        if ico.exists():
            try:
                self.iconbitmap(str(ico))
            except Exception:
                pass

        # Logos X (diseño de marca) — mantener refs para no perder PhotoImage
        self._img_logo_header = None
        self._img_logo_hero = None
        self._img_logo_main = None
        self._load_brand_images()

        self.config_data = {}
        try:
            if cleaner is not None:
                self.config_data = cleaner.cargar_config()
        except Exception:
            self.config_data = {}

        self._busy = False
        self._update_info = None
        self._welcome_ready = False
        self._dep_report = dep_report or {}
        self.fluent = FluentUI(dict(FLUENT), root=self)

        apply_fluent_style(self)
        self._build()

    def _load_brand_images(self) -> None:
        """Carga variantes del logo X (diseño de marca)."""
        candidates = {
            "header": ["logo_x_header.png", "logo_x_64.png", "logo_x.png"],
            "hero": ["logo_x_128.png", "logo_x_96.png", "logo_x.png"],
            "main": ["logo_x_64.png", "logo_x_96.png", "logo_x.png"],
        }
        for key, names in candidates.items():
            img = None
            for name in names:
                path = APP_DIR / name
                if not path.exists():
                    continue
                try:
                    img = tk.PhotoImage(file=str(path))
                    break
                except Exception:
                    img = None
            if key == "header":
                self._img_logo_header = img
            elif key == "hero":
                self._img_logo_hero = img
            else:
                self._img_logo_main = img

    def call_ui(self, func, *args, **kwargs):
        self.after(0, lambda: func(*args, **kwargs))

    def notify(
        self,
        title: str,
        message: str,
        *,
        kind: str = "info",
        buttons: list[tuple[str, str]] | None = None,
        on_result=None,
    ):
        return FluentNotify(
            self, title, message, kind=kind, buttons=buttons, on_result=on_result,
        )

    def reveal(self):
        """Muestra la ventana de forma fiable (evita quedar invisible por alpha/off-screen)."""
        try:
            self.deiconify()
        except Exception:
            pass
        try:
            self.state("normal")
        except Exception:
            pass
        # Centrar en pantalla principal
        try:
            self.update_idletasks()
            w = max(self.winfo_width(), 900)
            h = max(self.winfo_height(), 700)
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
            x = max(0, (sw - w) // 2)
            y = max(0, (sh - h) // 2)
            self.geometry(f"{w}x{h}+{x}+{y}")
        except Exception:
            pass
        # Opacidad siempre al 100% (fade opcional; si falla no deja la app invisible)
        try:
            self.attributes("-alpha", 1.0)
        except tk.TclError:
            pass
        try:
            self.attributes("-topmost", True)
            self.lift()
            self.focus_force()
            self.after(400, lambda: self.attributes("-topmost", False))
        except Exception:
            try:
                self.lift()
            except Exception:
                pass
        try:
            self.update()
        except Exception:
            pass
        self.after(350, self._welcome_check_updates)

    def _build(self):
        self.fluent.app_header(
            self,
            "Cleaner X",
            version=f"v{VERSION}",
            subtitle="Identidad X · limpieza profesional de media",
            logo_image=self._img_logo_header,
        )

        self.stack = tk.Frame(self, bg=BG)
        self.stack.pack(fill="both", expand=True)

        self.welcome_frame = tk.Frame(self.stack, bg=BG)
        self.main_frame = tk.Frame(self.stack, bg=BG)

        self._build_welcome()
        self._build_main()

        bar = tk.Frame(self, bg=FLUENT["header"], height=34)
        bar.pack(side="bottom", fill="x")
        bar.pack_propagate(False)
        tk.Frame(bar, bg=FLUENT.get("divider", ACCENT), height=1).pack(fill="x", side="top")
        status_dot = tk.Frame(bar, bg=ACCENT_GREEN, width=7, height=7)
        status_dot.pack(side="left", padx=(14, 6), pady=12)
        self.footer_lbl = tk.Label(
            bar, text=f"v{VERSION}  ·  bienvenida",
            font=("Segoe UI", 8), fg=FG_MUTED, bg=FLUENT["header"],
        )
        self.footer_lbl.pack(side="left", pady=8)
        self.footer_right = tk.Label(
            bar, text="Cleaner X  ·  REMIXZ",
            font=("Segoe UI", 8), fg=FLUENT.get("text_dim", FG_MUTED), bg=FLUENT["header"],
        )
        self.footer_right.pack(side="right", padx=14, pady=8)

        self._show_welcome()

    def _show_welcome(self):
        self.main_frame.pack_forget()
        self.welcome_frame.pack(fill="both", expand=True, padx=36, pady=20)

    def _show_main(self):
        self.welcome_frame.pack_forget()
        self.main_frame.pack(fill="both", expand=True, padx=28, pady=18)
        self.footer_lbl.configure(text=f"v{VERSION}  ·  listo")

    def _card(self, parent, title: str = "", accent: str | None = None, subtitle: str = ""):
        """Card profesional con borde sutil y cabecera."""
        ac = accent or ACCENT_CYAN
        shell = tk.Frame(
            parent, bg=FLUENT["card"],
            highlightthickness=1, highlightbackground=FLUENT["border"],
        )
        shell.pack(fill="x", pady=(0, 14))
        # top accent line
        tk.Frame(shell, bg=ac, height=2).pack(fill="x")
        inner = tk.Frame(shell, bg=FLUENT["card"])
        inner.pack(fill="x", padx=18, pady=16)
        if title:
            head = tk.Frame(inner, bg=FLUENT["card"])
            head.pack(fill="x", pady=(0, 10 if not subtitle else 4))
            tk.Label(
                head, text=title, font=("Segoe UI Semibold", 11),
                fg=FG, bg=FLUENT["card"], anchor="w",
            ).pack(side="left", fill="x")
            if subtitle:
                tk.Label(
                    inner, text=subtitle, font=("Segoe UI", 8),
                    fg=FG_MUTED, bg=FLUENT["card"], anchor="w",
                ).pack(fill="x", pady=(0, 10))
        return shell, inner

    def _chip(self, parent, label: str, value: str, color: str | None = None):
        chip = tk.Frame(
            parent, bg=FLUENT["input"],
            highlightthickness=1, highlightbackground=FLUENT["border"],
        )
        chip.pack(side="left", padx=(0, 12), pady=2)
        tk.Label(
            chip, text=label.upper(), font=("Segoe UI", 7),
            fg=FLUENT.get("text_dim", FG_MUTED), bg=FLUENT["input"],
        ).pack(padx=14, pady=(8, 0))
        val = tk.Label(
            chip, text=value, font=("Segoe UI Semibold", 13),
            fg=color or FG, bg=FLUENT["input"],
        )
        val.pack(padx=14, pady=(0, 10))
        return chip, val

    def refresh_dep_ui(self, report: dict | None = None):
        """Actualiza chips y texto de dependencias tras el boot."""
        if report is not None:
            self._dep_report = report
        r = self._dep_report or {}
        ok = bool(r.get("ok"))
        n_miss = len(r.get("missing") or [])
        dep_txt = "OK" if ok else (f"{n_miss} faltan" if n_miss else "…")
        dep_col = ACCENT_GREEN if ok else ACCENT_ORANGE
        try:
            self.dep_chip_val.configure(text=dep_txt, fg=dep_col)
        except Exception:
            pass
        try:
            self.dep_status.configure(text=r.get("detail") or "Comprobadas al iniciar.")
        except Exception:
            pass

    def _build_welcome(self):
        f = self.welcome_frame

        # ── Hero centrado estilo producto (logo X) ─────────────────────────
        hero_shell = tk.Frame(
            f, bg=FLUENT.get("panel", FLUENT["surface"]),
            highlightthickness=1, highlightbackground=FLUENT["border"],
        )
        hero_shell.pack(fill="x", pady=(0, 16))
        # degradado simulado: franja azul superior
        tk.Frame(hero_shell, bg=ACCENT, height=2).pack(fill="x")
        tk.Frame(hero_shell, bg=ACCENT_CYAN, height=1).pack(fill="x")

        hero = tk.Frame(hero_shell, bg=FLUENT.get("panel", FLUENT["surface"]))
        hero.pack(fill="x", padx=28, pady=26)

        center = tk.Frame(hero, bg=FLUENT.get("panel", FLUENT["surface"]))
        center.pack(fill="x")

        # Logo X grande
        logo_row = tk.Frame(center, bg=FLUENT.get("panel", FLUENT["surface"]))
        logo_row.pack(anchor="center")
        if self._img_logo_hero is not None:
            logo_lbl = tk.Label(
                logo_row,
                image=self._img_logo_hero,
                bg=FLUENT.get("panel", FLUENT["surface"]),
                bd=0,
            )
            logo_lbl.image = self._img_logo_hero
            logo_lbl.pack()
        else:
            # Fallback tipográfico
            tk.Label(
                logo_row, text="X",
                font=("Segoe UI Black", 48),
                fg=ACCENT_CYAN,
                bg=FLUENT.get("panel", FLUENT["surface"]),
            ).pack()

        tk.Label(
            center, text="CLEANER X",
            font=("Segoe UI Black", 26),
            fg=FG, bg=FLUENT.get("panel", FLUENT["surface"]),
        ).pack(pady=(10, 0))
        tk.Label(
            center,
            text="Limpieza profesional de nombres y metadatos\n"
                 "RemixZ  ·  Tio Dealer  ·  WhatsApp",
            font=("Segoe UI", 10),
            fg=FG_MUTED, bg=FLUENT.get("panel", FLUENT["surface"]),
            justify="center",
        ).pack(pady=(6, 0))

        # barra acento corta centrada
        accent_line = tk.Frame(center, bg=FLUENT.get("panel", FLUENT["surface"]))
        accent_line.pack(pady=(14, 0))
        tk.Frame(accent_line, bg=ACCENT, height=3, width=72).pack()

        # ── Chips de estado ────────────────────────────────────────────────
        chips = tk.Frame(f, bg=BG)
        chips.pack(fill="x", pady=(4, 8))
        chips_inner = tk.Frame(chips, bg=BG)
        chips_inner.pack(anchor="center")
        self._chip(chips_inner, "Versión", f"v{VERSION}", ACCENT_CYAN)
        _, self.dep_chip_val = self._chip(chips_inner, "Dependencias", "…", ACCENT_ORANGE)
        self._chip(chips_inner, "Flujo", "1 acción", ACCENT_GREEN)

        # ── Dos cards en fila (deps | updates) ─────────────────────────────
        row = tk.Frame(f, bg=BG)
        row.pack(fill="x", pady=(4, 0))
        row.columnconfigure(0, weight=1)
        row.columnconfigure(1, weight=1)

        left_wrap = tk.Frame(row, bg=BG)
        left_wrap.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        right_wrap = tk.Frame(row, bg=BG)
        right_wrap.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

        _, dep_body = self._card(
            left_wrap, "Dependencias", ACCENT,
            subtitle="Verificación automática al iniciar",
        )
        self.dep_status = tk.Label(
            dep_body,
            text=self._dep_report.get("detail") or "Comprobadas al iniciar.",
            font=("Consolas", 9),
            fg=FG_MUTED, bg=FLUENT["card"],
            anchor="w", justify="left", wraplength=340,
        )
        self.dep_status.pack(fill="x")

        _, up_body = self._card(
            right_wrap, "Actualizaciones", ACCENT_CYAN,
            subtitle="Validación en vivo desde GitHub",
        )
        self.welcome_status = tk.Label(
            up_body,
            text="Validando updates desde el repositorio…",
            font=("Segoe UI", 10),
            fg=FG_MUTED, bg=FLUENT["card"],
            anchor="w", wraplength=340, justify="left",
        )
        self.welcome_status.pack(fill="x")

        # Progreso rounded + degradado
        prog_wrap = tk.Frame(f, bg=BG)
        prog_wrap.pack(fill="x", pady=(8, 0))
        tk.Label(
            prog_wrap, text="Estado del sistema",
            font=("Segoe UI Semibold", 8),
            fg=FLUENT.get("text_dim", FG_MUTED), bg=BG, anchor="w",
        ).pack(fill="x", pady=(0, 6))
        self.welcome_prog = RoundedGradientProgress(
            prog_wrap,
            height=12,
            maximum=100,
            mode="indeterminate",
            colors=dict(FLUENT),
            gradient=(FLUENT["accent"], FLUENT["cyan"]),
            bg=BG,
        )
        self.welcome_prog.pack(fill="x")

        tk.Label(
            f,
            text="Al completar la validación se mostrará una notificación. "
                 "Pulsa OK para entrar al panel de limpieza.",
            font=("Segoe UI", 9),
            fg=FLUENT.get("text_dim", FG_MUTED), bg=BG, anchor="center",
            justify="center",
        ).pack(fill="x", pady=(14, 0))

    def _build_main(self):
        body = self.main_frame
        f_title = font_or_fallback(FONTS["title"])
        f_body = font_or_fallback(FONTS["body_lg"])
        f_sub = font_or_fallback(FONTS["subhead"])
        f_cap = font_or_fallback(FONTS["caption"])
        f_micro = font_or_fallback(FONTS["micro"])
        f_mono = font_or_fallback(FONTS["mono"])
        f_pct = font_or_fallback(FONTS["pct"])
        f_btn = font_or_fallback(FONTS["btn"])

        # Cabecera con logo X
        top = tk.Frame(body, bg=BG)
        top.pack(fill="x", pady=(0, 16))
        if self._img_logo_main is not None:
            logo_lbl = tk.Label(
                top, image=self._img_logo_main, bg=BG, bd=0,
            )
            logo_lbl.image = self._img_logo_main
            logo_lbl.pack(side="left", padx=(0, 14))
        left_t = tk.Frame(top, bg=BG)
        left_t.pack(side="left", fill="x", expand=True)
        tk.Label(
            left_t, text="Panel de limpieza",
            font=f_title, fg=FG, bg=BG, anchor="w",
        ).pack(fill="x")
        tk.Label(
            left_t,
            text="Selecciona una carpeta y limpia nombres / metadatos en un clic.",
            font=f_body, fg=FG_MUTED, bg=BG, anchor="w",
        ).pack(fill="x", pady=(6, 0))

        # Card acción principal — Cleaner
        _, action = self._card(
            body, "Acción principal", ACCENT_GREEN,
            subtitle="Procesa audio, video e imagen en la carpeta elegida.",
        )
        row = tk.Frame(action, bg=FLUENT["card"])
        row.pack(fill="x")
        self.main_btn = self.fluent.button(
            row, "  Limpiar carpeta  ", self._run_once, kind="success", width=18,
        )
        self.main_btn.pack(side="left")
        try:
            self.main_btn.configure(font=f_btn, pady=12, padx=18)
        except Exception:
            try:
                self.main_btn.configure(font=f_btn)
            except Exception:
                pass

        path_box = tk.Frame(
            row, bg=FLUENT["input"],
            highlightthickness=1, highlightbackground=FLUENT["border"],
        )
        path_box.pack(side="left", fill="x", expand=True, padx=(16, 0), ipady=4)
        tk.Label(
            path_box, text="CARPETA", font=f_micro,
            fg=FLUENT.get("text_dim", FG_MUTED), bg=FLUENT["input"],
        ).pack(anchor="w", padx=12, pady=(6, 0))
        self.path_lbl = tk.Label(
            path_box,
            text="Ninguna seleccionada",
            font=f_cap, fg=FG_MUTED, bg=FLUENT["input"],
            anchor="w", wraplength=420, justify="left",
        )
        self.path_lbl.pack(fill="x", padx=12, pady=(0, 8))

        # Card DJ Tools — apariencia BLOQUEADA para el usuario (próximamente)
        # Acceso de prueba solo con password maestro (5312), no se publicita en UI.
        _, dj_action = self._card(
            body, "ClubRemix DJ Tools", ACCENT,
            subtitle="Función ClubRemix · bloqueada para usuarios (próximamente).",
        )
        dj_row = tk.Frame(dj_action, bg=FLUENT["card"])
        dj_row.pack(fill="x")
        self.dj_btn = self.fluent.button(
            dj_row, "  Abrir DJ Tools  ", self._open_djtools, kind="accent", width=18,
        )
        self.dj_btn.pack(side="left")
        try:
            self.dj_btn.configure(font=f_btn, pady=12, padx=18)
        except Exception:
            try:
                self.dj_btn.configure(font=f_btn)
            except Exception:
                pass
        soon = tk.Frame(
            dj_row, bg=FLUENT["input"],
            highlightthickness=1, highlightbackground=FLUENT["border"],
        )
        soon.pack(side="left", padx=(14, 0))
        tk.Label(
            soon, text="  🔒 PRÓXIMAMENTE  ",
            font=font_or_fallback(FONTS["subhead"]),
            fg=ACCENT_ORANGE, bg=FLUENT["input"],
        ).pack(padx=4, pady=8)
        tk.Label(
            dj_row,
            text="Uso ClubRemix bloqueado en esta versión",
            font=f_cap, fg=FG_MUTED, bg=FLUENT["card"],
            anchor="w",
        ).pack(side="left", fill="x", expand=True, padx=(12, 0))

        # Log profesional
        log_shell = tk.Frame(
            body, bg=FLUENT["card"],
            highlightthickness=1, highlightbackground=FLUENT["border"],
        )
        log_shell.pack(fill="both", expand=True, pady=(0, 12))
        tk.Frame(log_shell, bg=ACCENT_CYAN, height=2).pack(fill="x")
        log_head = tk.Frame(log_shell, bg=FLUENT["card"])
        log_head.pack(fill="x", padx=16, pady=(12, 8))
        tk.Label(
            log_head, text="Registro de actividad",
            font=f_sub, fg=FG, bg=FLUENT["card"],
        ).pack(side="left")
        tk.Label(
            log_head, text="EN VIVO",
            font=f_micro, fg=ACCENT_GREEN, bg=FLUENT["card"],
        ).pack(side="right")
        self.log = scrolledtext.ScrolledText(
            log_shell,
            height=11,
            font=f_mono,
            bg=FLUENT["input"], fg=FG, insertbackground=FG,
            relief="flat",
            highlightthickness=0,
            state="disabled",
            padx=10,
            pady=10,
        )
        self.log.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        # ── Progreso premium (barra grande + contadores + fase) ───────────
        prog_card = tk.Frame(
            body, bg=FLUENT["card"],
            highlightthickness=1, highlightbackground=FLUENT["border"],
        )
        prog_card.pack(fill="x")
        tk.Frame(prog_card, bg=ACCENT, height=2).pack(fill="x")
        prog_inner = tk.Frame(prog_card, bg=FLUENT["card"])
        prog_inner.pack(fill="x", padx=18, pady=14)

        prog_top = tk.Frame(prog_inner, bg=FLUENT["card"])
        prog_top.pack(fill="x", pady=(0, 6))
        left_meta = tk.Frame(prog_top, bg=FLUENT["card"])
        left_meta.pack(side="left", fill="x", expand=True)
        tk.Label(
            left_meta, text="PROGRESO DE LIMPIEZA",
            font=f_micro, fg=FLUENT.get("text_dim", FG_MUTED), bg=FLUENT["card"],
        ).pack(anchor="w")
        self.phase_lbl = tk.Label(
            left_meta, text="En espera",
            font=f_sub, fg=FG, bg=FLUENT["card"],
        )
        self.phase_lbl.pack(anchor="w", pady=(2, 0))

        right_meta = tk.Frame(prog_top, bg=FLUENT["card"])
        right_meta.pack(side="right")
        self.pct_lbl = tk.Label(
            right_meta, text="0%", font=f_pct,
            fg=ACCENT_CYAN, bg=FLUENT["card"],
        )
        self.pct_lbl.pack(anchor="e")
        self.files_lbl = tk.Label(
            right_meta, text="0 / 0 archivos",
            font=f_cap, fg=FG_MUTED, bg=FLUENT["card"],
        )
        self.files_lbl.pack(anchor="e")

        self.prog = RoundedGradientProgress(
            prog_inner,
            height=18,
            maximum=100,
            mode="determinate",
            colors=dict(FLUENT),
            gradient=(FLUENT["accent"], FLUENT["cyan"]),
            bg=FLUENT["card"],
            show_glow=True,
        )
        self.prog.pack(fill="x", pady=(4, 0))

        # Segunda pista fina (detalle / sub-progreso visual)
        self.prog_detail = RoundedGradientProgress(
            prog_inner,
            height=6,
            maximum=100,
            mode="determinate",
            colors=dict(FLUENT),
            gradient=(FLUENT["green"], FLUENT["cyan"]),
            bg=FLUENT["card"],
            show_glow=False,
        )
        self.prog_detail.pack(fill="x", pady=(6, 0))

        self.status = tk.Label(
            prog_inner,
            text="Listo. Pulsa «Limpiar carpeta» para comenzar.",
            font=f_cap, fg=FG_MUTED, bg=FLUENT["card"], anchor="w",
            wraplength=780, justify="left",
        )
        self.status.pack(fill="x", pady=(10, 0))
        self._clean_total = 0
        self._clean_current = 0

    # ── Updates en bienvenida ──────────────────────────────────────────────
    def _welcome_check_updates(self):
        try:
            self.welcome_prog.start(14)
        except Exception:
            pass
        self.welcome_status.configure(
            text="Validando actualizaciones en el repositorio…", fg=FG_MUTED,
        )
        self.footer_lbl.configure(text=f"v{VERSION} · validando updates…")

        def on_result(info: remixz_update.UpdateInfo):
            self.call_ui(self._on_welcome_update_result, info)

        remixz_update.check_async(on_result, APP_DIR)

    def _on_welcome_update_result(self, info: remixz_update.UpdateInfo):
        self._update_info = info
        msg = info.message or "Sin información de update."

        try:
            self.welcome_prog.stop()
            self.welcome_prog.pack_forget()
        except Exception:
            pass

        if info.available and info.download_url:
            remote = info.remote_version or (info.remote_sha[:7] if info.remote_sha else "?")
            self.welcome_status.configure(
                text=f"Update disponible: {remote}", fg=ACCENT_GREEN,
            )
            self.footer_lbl.configure(text=f"v{VERSION} · update {remote}")
            detail = (
                f"{msg}\n\n"
                f"Local:  v{info.local_version}\n"
                f"Remoto: {remote}\n\n"
                "¿Aplicar el update ahora?\n"
                "(Se conservan config.json y logs)\n\n"
                "Si eliges No, se abrirá Cleaner X igual."
            )

            def after_update_choice(key: str):
                if key in ("yes", "apply"):
                    self._apply_update_then_start()
                else:
                    self._start_after_ok()

            self.notify(
                "Update disponible", detail, kind="update",
                buttons=[("No", "no"), ("Aplicar", "yes")],
                on_result=after_update_choice,
            )
            return

        if not info.ready:
            body = msg or "No se pudo validar el repositorio de updates."
            self.welcome_status.configure(text=body, fg=FG_MUTED)
            self.footer_lbl.configure(text=f"v{VERSION} · sin updates en repo")
            kind = "info"
            title = "Sin update disponible"
        else:
            body = msg if msg else "No hay actualizaciones nuevas. Estás al día."
            self.welcome_status.configure(text=body, fg=ACCENT_GREEN)
            self.footer_lbl.configure(text=f"v{VERSION} · al día")
            kind = "success"
            title = "Sin update — al día"

        self.notify(
            title,
            f"{body}\n\n"
            f"Versión local: v{VERSION}\n\n"
            "No hay nada que aplicar ahora.\n"
            "Pulsa OK para iniciar Cleaner X.",
            kind=kind,
            buttons=[("OK", "ok")],
            on_result=lambda _k: self._start_after_ok(),
        )

    def _start_after_ok(self):
        if self._welcome_ready:
            return
        self._welcome_ready = True
        self._show_main()

    def _restart_after_update(self):
        """Relanza el aplicativo sin pedir confirmación y SIN abrir el panel principal."""
        try:
            # No mostrar interfaz de trabajo — solo mensaje de reinicio
            self._welcome_ready = False
            try:
                self.main_frame.pack_forget()
            except Exception:
                pass
            try:
                self.welcome_frame.pack(fill="both", expand=True, padx=36, pady=20)
            except Exception:
                pass
            self.footer_lbl.configure(text=f"v{VERSION} · reiniciando…")
            self.welcome_status.configure(
                text="Update aplicado. Reiniciando automáticamente…\n"
                     "No cierres esta ventana.",
                fg=ACCENT_GREEN,
            )
        except Exception:
            pass
        # Esperar a que se cierren handles del update y relanzar
        self.after(900, restart_application)

    def _apply_update_then_start(self):
        """Al pulsar Aplicar: progreso → reinicio automático (sin UI principal)."""
        info = self._update_info
        if not info or not info.download_url:
            self._start_after_ok()
            return

        self._busy = True
        # Asegurar que solo se ve bienvenida / progreso, no el panel Cleaner
        try:
            self.main_frame.pack_forget()
            self._welcome_ready = False
        except Exception:
            pass
        remote = info.remote_version or (info.remote_sha[:7] if info.remote_sha else "?")
        try:
            self.welcome_status.configure(
                text=f"Aplicando update {remote}… (ver ventana)",
                fg=ACCENT_ORANGE,
            )
            self.footer_lbl.configure(text=f"v{VERSION} · aplicando update…")
        except Exception:
            pass

        # Ventana modal dedicada — aquí se ve TODO lo que hace
        win = UpdateProgressWindow(self, remote_label=str(remote))
        self._update_win = win
        win.set_progress(1, "Conectando con el repositorio…")
        win._log_line(f"Origen: {info.source or 'GitHub'}")
        win._log_line(f"Repo: {getattr(info, 'repo', '') or 'GitHub'}")
        win._log_line(f"URL: {(info.download_url or '')[:70]}…")
        win._log_line("Al terminar: reinicio automático (sin abrir panel).")

        def on_progress(pct: int, msg: str):
            def _ui():
                try:
                    if win.winfo_exists():
                        win.set_progress(pct, msg)
                except Exception:
                    pass
                try:
                    self.footer_lbl.configure(text=f"v{VERSION} · update {pct}%")
                except Exception:
                    pass
            self.call_ui(_ui)

        def on_status(msg: str):
            def _ui():
                try:
                    if win.winfo_exists() and msg:
                        win.detail_lbl.configure(text=msg)
                except Exception:
                    pass
            self.call_ui(_ui)

        def worker():
            ok, message = remixz_update.apply_update(
                info,
                APP_DIR,
                progress_cb=on_progress,
                status_cb=on_status,
            )
            self._busy = False

            def done():
                if ok:
                    try:
                        self.welcome_status.configure(
                            text="Update aplicado — reiniciando automáticamente…",
                            fg=ACCENT_GREEN,
                        )
                        self.footer_lbl.configure(text=f"v{VERSION} · reiniciando…")
                    except Exception:
                        pass

                    def after_auto_restart():
                        # Forzar reinicio; no pasar por _start_after_ok / panel principal
                        self._restart_after_update()

                    try:
                        win.finish_ok(
                            message + "\nReinicio automático…",
                            on_restart=after_auto_restart,
                            auto_restart=True,
                            auto_delay_ms=1200,
                        )
                    except Exception:
                        self.after(400, restart_application)
                    # Failsafe: si finish_ok no dispara, reiniciar igual
                    def _failsafe_restart():
                        try:
                            if self.winfo_exists():
                                restart_application()
                        except Exception:
                            try:
                                restart_application()
                            except Exception:
                                pass

                    self.after(4500, _failsafe_restart)
                else:
                    try:
                        self.welcome_status.configure(text=message, fg="#ff6666")
                    except Exception:
                        pass

                    def after_err():
                        self._start_after_ok()

                    try:
                        win.finish_error(message, on_close=after_err)
                    except Exception:
                        self.notify(
                            "Update",
                            f"{message}\n\nPulsa OK para continuar.",
                            kind="error",
                            buttons=[("OK", "ok")],
                            on_result=lambda _k: self._start_after_ok(),
                        )

            self.call_ui(done)

        threading.Thread(target=worker, daemon=True).start()

    # ── ClubRemix DJ Tools ─────────────────────────────────────────────────
    MASTER_PASSWORD = "5312"  # solo pruebas internas (no mostrar al usuario)

    def _open_djtools(self):
        """
        Para el usuario final: aparece BLOQUEADO / PRÓXIMAMENTE.
        Acceso de prueba: password maestro 5312 (diálogo sin publicitar la clave).
        """
        def after_pw(ok: bool):
            if not ok:
                try:
                    self._append_log("DJ Tools: bloqueado (próximamente) / sin acceso.")
                except Exception:
                    pass
                # Mensaje de usuario final — no mencionar password ni modo prueba
                self.notify(
                    "ClubRemix · Próximamente",
                    "ClubRemix DJ Tools aún no está disponible en esta versión.\n\n"
                    "• Renombrar con membresía\n"
                    "• Actualizar TITLE (ffmpeg)\n\n"
                    "Esta función se habilitará en una próxima actualización.\n"
                    "Por ahora usa «Limpiar carpeta» con normalidad.",
                    kind="info",
                    buttons=[("Entendido", "ok")],
                )
                return
            try:
                self._append_log("DJ Tools: acceso de prueba autorizado.")
            except Exception:
                pass
            if getattr(self, "_dj_win", None) is not None:
                try:
                    if self._dj_win.winfo_exists():
                        self._dj_win.lift()
                        self._dj_win.focus_force()
                        return
                except Exception:
                    pass
            self._dj_win = DJToolsWindow(self)

        # Diálogo interno: si cancelan o fallan, ven el mensaje de bloqueado
        MasterPasswordDialog(
            self,
            title="ClubRemix · Próximamente",
            message=(
                "Esta función está bloqueada para usuarios.\n\n"
                "Si tienes autorización de prueba, ingresa el código de acceso:"
            ),
            expected=self.MASTER_PASSWORD,
            on_result=after_pw,
        )

    # ── Limpieza ───────────────────────────────────────────────────────────
    def _append_log(self, line: str):
        self.log.configure(state="normal")
        self.log.insert("end", line + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _set_progress(
        self,
        value: int,
        *,
        current: int | None = None,
        total: int | None = None,
        phase: str | None = None,
        detail_pct: int | None = None,
    ):
        value = max(0, min(100, int(value)))
        try:
            self.prog.set(value)
        except Exception:
            try:
                self.prog.configure(value=value)
            except Exception:
                pass
        try:
            self.pct_lbl.configure(text=f"{value}%")
            # color según avance
            if value >= 100:
                self.pct_lbl.configure(fg=ACCENT_GREEN)
            elif value >= 50:
                self.pct_lbl.configure(fg=ACCENT_CYAN)
            else:
                self.pct_lbl.configure(fg=ACCENT_ORANGE if value > 0 else ACCENT_CYAN)
        except Exception:
            pass
        if total is not None:
            self._clean_total = max(0, int(total))
        if current is not None:
            self._clean_current = max(0, int(current))
        try:
            self.files_lbl.configure(
                text=f"{self._clean_current} / {self._clean_total} archivos"
            )
        except Exception:
            pass
        if phase:
            try:
                self.phase_lbl.configure(text=phase)
            except Exception:
                pass
        if detail_pct is not None:
            try:
                self.prog_detail.set(max(0, min(100, int(detail_pct))))
            except Exception:
                pass
        elif total and current is not None and total > 0:
            # sub-barra = progreso dentro del lote actual
            try:
                self.prog_detail.set(int(current / total * 100))
            except Exception:
                pass

    def _run_once(self):
        if self._busy:
            self.notify(
                "RemixZ Cleaner X", "Ya hay una limpieza en curso.",
                kind="info", buttons=[("OK", "ok")],
            )
            return
        if cleaner is None:
            self.notify(
                "Error", "El motor Cleaner no está cargado.",
                kind="error", buttons=[("OK", "ok")],
            )
            return

        folder = filedialog.askdirectory(
            title="Selecciona la carpeta a limpiar",
            initialdir=str(APP_DIR),
        )
        if not folder:
            return

        def after_confirm(key: str):
            if key != "yes":
                return
            self._start_clean(folder)

        self.notify(
            "Confirmar limpieza",
            f"Se limpiarán nombres y metadatos en:\n\n{folder}\n\n¿Continuar?",
            kind="warning",
            buttons=[("Cancelar", "no"), ("Continuar", "yes")],
            on_result=after_confirm,
        )

    def _start_clean(self, folder: str):
        self._busy = True
        try:
            self.main_btn.configure(state="disabled")
        except Exception:
            pass
        self.path_lbl.configure(text=f"  Carpeta: {folder}", fg=ACCENT_CYAN)
        self._clear_log()
        self._set_progress(0, current=0, total=0, phase="Escaneando…", detail_pct=0)
        self.status.configure(text="Escaneando archivos…", fg=ACCENT_ORANGE)
        self._append_log(f"Carpeta: {folder}")
        self._append_log("Modo: 1 opción — escanear + limpiar")
        self._append_log("─" * 44)

        def worker():
            try:
                self.call_ui(
                    self._set_progress, 2,
                    current=0, total=0, phase="Escaneando carpeta…", detail_pct=10,
                )
                self.call_ui(self.status.configure, text="Escaneando…", fg=ACCENT_ORANGE)
                archivos = cleaner.recolectar_archivos([folder])
                audio = sum(1 for f in archivos if f.suffix.lower() in cleaner.EXT_AUDIO)
                video = sum(1 for f in archivos if f.suffix.lower() in cleaner.EXT_VIDEO)
                img = sum(1 for f in archivos if f.suffix.lower() in cleaner.EXT_IMG)

                self.call_ui(self._append_log, f"Encontrados: {len(archivos)}")
                self.call_ui(
                    self._append_log,
                    f"   Audio: {audio}  |  Video: {video}  |  Imagen: {img}",
                )

                if not archivos:
                    self.call_ui(
                        self.notify,
                        "RemixZ Cleaner X",
                        "No se encontraron archivos multimedia en esa carpeta.",
                        kind="warning",
                        buttons=[("OK", "ok")],
                    )
                    self.call_ui(
                        self._set_progress, 0,
                        current=0, total=0, phase="Sin archivos", detail_pct=0,
                    )
                    self.call_ui(self.status.configure, text="Sin archivos.", fg=FG_MUTED)
                    return

                self.call_ui(self._append_log, "─" * 44)
                self.call_ui(self._append_log, "Limpiando…")
                self.call_ui(
                    self._set_progress, 5,
                    current=0, total=len(archivos),
                    phase="Limpiando archivos", detail_pct=0,
                )
                self.call_ui(self.status.configure, text="Limpiando…", fg=ACCENT_ORANGE)

                ui = TkCleanerUI(
                    self,
                    self._append_log,
                    self._set_progress,
                    lambda t: self.status.configure(text=t, fg=ACCENT_CYAN),
                )
                cleaner.ejecutar_limpieza(archivos, self.config_data, ui)
            except Exception as exc:
                self.call_ui(
                    self._append_log,
                    f"Error: {exc}\n{traceback.format_exc()}",
                )
                self.call_ui(
                    self._set_progress, 0,
                    phase="Error", detail_pct=0,
                )
                self.call_ui(self.status.configure, text="Error.", fg="#ff6666")
            finally:
                self._busy = False
                self.call_ui(self.main_btn.configure, state="normal")

        threading.Thread(target=worker, daemon=True).start()


# ---------------------------------------------------------------------------
# Main / boot
# ---------------------------------------------------------------------------
def main():
    _hide_console()
    os.chdir(APP_DIR)

    # App OCULTA hasta terminar splash/boot — no mostrar panel del programa aún
    app = CleanerXApp(start_hidden=True, dep_report={})
    try:
        app.withdraw()
    except Exception:
        pass

    # Solo splash visible al abrir
    splash = None
    try:
        splash = LoadingSplash(
            APP_TITLE,
            version=f"v{VERSION}",
            colors=dict(FLUENT),
            master=app,
        )
        splash.set_status("Preparando Cleaner X…", 8, step=0)
        try:
            app.update_idletasks()
        except Exception:
            pass
    except Exception as exc:
        _log_boot(f"splash: {exc}")
        splash = None
        # Sin splash: mostrar solo bienvenida (no panel principal aún)
        try:
            app.deiconify()
        except Exception:
            pass

    dep_report: dict = {}
    boot_error: str | None = None
    _shown = {"done": False}

    def _close_splash():
        nonlocal splash
        if splash is None:
            return
        try:
            splash.destroy()
        except Exception:
            pass
        splash = None

    def set_status(text: str):
        if splash is not None:
            try:
                splash.set_status(text)
            except Exception:
                pass
        try:
            app.update_idletasks()
        except Exception:
            pass

    def set_progress(percent: int):
        if splash is not None:
            try:
                splash.set_status(splash.status.cget("text"), percent)
            except Exception:
                pass

    def finish_boot():
        """Cierra splash y muestra solo bienvenida (NO el panel Cleaner aún)."""
        if _shown["done"]:
            return
        _shown["done"] = True
        _close_splash()
        try:
            # Asegurar que el panel principal no se vea hasta OK de bienvenida
            app._welcome_ready = False
            try:
                app.main_frame.pack_forget()
            except Exception:
                pass
            app.reveal()  # deiconify + check updates (sigue en welcome)
        except Exception:
            try:
                app.deiconify()
                app.state("normal")
                app.attributes("-alpha", 1.0)
                app.lift()
                app.focus_force()
            except Exception:
                pass
        try:
            app.refresh_dep_ui(dep_report)
        except Exception:
            pass
        if boot_error:
            detail = f"{boot_error}\n\n{dep_report.get('detail', '')}".strip()
            app.after(
                400,
                lambda: app.notify(
                    "Aviso de inicio",
                    detail,
                    kind="warning",
                    buttons=[("OK", "ok")],
                ),
            )

    def boot_worker():
        """Deps + motor en background (no congelar la UI)."""
        nonlocal dep_report, boot_error
        try:
            def ui_status(text: str):
                try:
                    app.after(0, lambda t=text: set_status(t))
                except Exception:
                    pass

            def ui_progress(percent: int):
                try:
                    app.after(0, lambda p=percent: set_progress(p))
                except Exception:
                    pass

            ui_status("Comprobando dependencias…")
            try:
                if splash is not None:
                    app.after(0, lambda: splash.set_status("Comprobando dependencias…", 15, step=1))
            except Exception:
                pass

            dep_report = ensure_packages(status_cb=ui_status, progress_cb=ui_progress)
            # Activar CustomTkinter si se instaló en este boot (misma paleta Fluent)
            try:
                if ensure_ctk_loaded(dict(FLUENT)):
                    def _enable_ctk_on_app():
                        try:
                            if getattr(app, "fluent", None) is not None:
                                app.fluent.use_ctk = True
                        except Exception:
                            pass
                    app.after(0, _enable_ctk_on_app)
            except Exception:
                pass
            try:
                app.after(0, lambda: setattr(app, "_dep_report", dep_report) or app.refresh_dep_ui(dep_report))
            except Exception:
                app._dep_report = dep_report

            ui_status("Cargando motor Cleaner…")
            try:
                if splash is not None:
                    app.after(0, lambda: splash.set_status("Cargando motor Cleaner…", 75, step=2))
            except Exception:
                pass

            try:
                load_cleaner_module()
                try:
                    app.config_data = cleaner.cargar_config()
                except Exception:
                    app.config_data = {}
            except Exception as exc:
                boot_error = f"No se pudo cargar el motor: {exc}"
                _log_boot(boot_error)

            ui_status("Listo")
            try:
                if splash is not None:
                    app.after(0, lambda: splash.set_status("Listo", 100, step=3))
            except Exception:
                pass
        except Exception as exc:
            boot_error = str(exc)
            _log_boot(f"boot: {exc}")
        finally:
            try:
                app.after(100, finish_boot)
            except Exception:
                pass

    # Failsafe: si el boot se cuelga, mostrar la app a los 6s
    app.after(6000, finish_boot)
    # Arrancar worker sin bloquear mainloop
    app.after(50, lambda: threading.Thread(target=boot_worker, daemon=True).start())
    app.mainloop()


if __name__ == "__main__":
    main()
