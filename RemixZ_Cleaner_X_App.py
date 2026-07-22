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
from datetime import datetime
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

    if final["ok"]:
        status("Dependencias listas: mutagen · colorama · psutil")
    elif final["missing"]:
        left = ", ".join(m[0] for m in final["missing"])
        status(f"Aún faltan: {left}")
        # no bloquear: el motor tiene fallbacks, pero reportamos mal
        final["ok"] = False
    progress(100)
    return final


# ---------------------------------------------------------------------------
# UI imports (tkinter must exist; fluent_ui is local)
# ---------------------------------------------------------------------------
import tkinter as tk
from tkinter import filedialog, ttk, scrolledtext

from fluent_ui import (
    FLUENT, FluentUI, LoadingSplash, RoundedGradientProgress,
    apply_fluent_style, fade_in_window,
)
import remixz_update
import remixz_djtools

# Offline builds: no auto-update check (set False to re-enable)
DISABLE_UPDATES = False

_local_ver = remixz_update.load_local_version(APP_DIR)
VERSION = str(_local_ver.get("version", "3.2.0"))
APP_TITLE = f"RemixZ Cleaner X v{VERSION}"
REPO_URL = str(_local_ver.get("repo_url") or "https://github.com/SMPROJECT115/remixz")
# Acceso maestro DJ Tools (legacy); en v3.2 el panel abre libre
MASTER_PASSWORD = "5312"

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
        self.app.call_ui(self.progress_fn, 0)
        self.app.call_ui(self.status_fn, "Limpiando…")

    def progress_update(self, actual, total, nombre, tiempo_inicio):
        pct = int(actual / total * 100) if total else 0
        self.app.call_ui(self.progress_fn, pct)
        self.app.call_ui(self.status_fn, f"{actual}/{total}: {nombre[:48]}")

    def log_file(self, nombre, acciones):
        txt = ", ".join(acciones) if acciones else "OK"
        self.app.call_ui(self.log_fn, f"OK: {nombre} → {txt}")

    def log_error(self, nombre):
        self.app.call_ui(self.log_fn, f"Error: {nombre}")

    def report_final(self, total, corregidos, errores, tiempo_total):
        self.app.call_ui(self.progress_fn, 100)
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
    """Cierra la app actual y la vuelve a lanzar (script o EXE)."""
    try:
        if getattr(sys, "frozen", False):
            # Onedir EXE: relanzar el mismo ejecutable
            cmd = [sys.executable]
            cwd = str(APP_DIR)
        else:
            script = APP_DIR / "RemixZ_Cleaner_X_App.py"
            # Preferir pythonw en Windows
            exe = sys.executable
            if os.name == "nt" and exe.lower().endswith("python.exe"):
                pyw = exe[:-10] + "pythonw.exe"
                if Path(pyw).exists():
                    exe = pyw
            cmd = [exe, str(script)]
            cwd = str(APP_DIR)
        flags = 0
        if os.name == "nt":
            flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0
            )
        subprocess.Popen(
            cmd,
            cwd=cwd,
            close_fds=True,
            creationflags=flags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
    except Exception:
        pass
    try:
        os._exit(0)
    except Exception:
        sys.exit(0)


# ---------------------------------------------------------------------------
# ClubRemix DJ Tools (panel independiente)
# ---------------------------------------------------------------------------
class DJToolsWindow(tk.Toplevel):
    """Panel: renombrar membresía + actualizar TITLE con barra de progreso."""

    def __init__(self, parent):
        super().__init__(parent)
        self.parent_app = parent
        self.title(f"ClubRemix DJ Tools  ·  v{VERSION}")
        self.geometry("720x620")
        self.minsize(640, 560)
        self.configure(bg=BG)
        self._busy = False
        self._folder = ""
        self._cancel = False
        self.fluent = FluentUI(dict(FLUENT), root=self)
        ico = APP_DIR / "icono.ico"
        if ico.exists():
            try:
                self.iconbitmap(str(ico))
            except Exception:
                pass
        apply_fluent_style(self)
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        try:
            self.transient(parent)
        except Exception:
            pass
        self.update_idletasks()
        try:
            px = parent.winfo_rootx() + 40
            py = parent.winfo_rooty() + 40
            self.geometry(f"+{px}+{py}")
        except Exception:
            pass

    def _on_close(self):
        if self._busy:
            self._cancel = True
            return
        try:
            self.parent_app._dj_win = None
        except Exception:
            pass
        self.destroy()

    def _build(self):
        head = tk.Frame(self, bg=FLUENT["header"], height=56)
        head.pack(fill="x")
        head.pack_propagate(False)
        tk.Frame(head, bg=ACCENT, height=2).pack(fill="x", side="bottom")
        left = tk.Frame(head, bg=FLUENT["header"])
        left.pack(side="left", fill="y", padx=16, pady=8)
        tk.Label(
            left, text="ClubRemix DJ Tools",
            font=("Segoe UI Semibold", 14), fg=FG, bg=FLUENT["header"],
        ).pack(anchor="w")
        tk.Label(
            left, text="Membresía automática · renombrar · TITLE · preview",
            font=("Segoe UI", 9), fg=FG_MUTED, bg=FLUENT["header"],
        ).pack(anchor="w")
        tag = remixz_djtools.clubremix_tag()
        tk.Label(
            head, text=tag,
            font=("Consolas", 9), fg=ACCENT_CYAN, bg=FLUENT["header"],
        ).pack(side="right", padx=16)

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=18, pady=14)

        # Carpeta
        tk.Label(
            body, text="CARPETA DE ARCHIVOS",
            font=("Segoe UI Semibold", 9), fg=FLUENT.get("text_dim", FG_MUTED), bg=BG,
        ).pack(anchor="w")
        folder_row = tk.Frame(body, bg=BG)
        folder_row.pack(fill="x", pady=(4, 10))
        self.folder_lbl = tk.Label(
            folder_row, text="Ninguna seleccionada",
            font=("Segoe UI", 9), fg=FG_MUTED, bg=FLUENT["input"],
            anchor="w", padx=10, pady=8,
            highlightthickness=1, highlightbackground=FLUENT["border"],
        )
        self.folder_lbl.pack(side="left", fill="x", expand=True)
        self.fluent.button(
            folder_row, "  Examinar…  ", self._browse, kind="secondary",
        ).pack(side="right", padx=(10, 0))

        # Opciones
        opt = tk.Frame(body, bg=FLUENT["card"], highlightthickness=1,
                       highlightbackground=FLUENT["border"])
        opt.pack(fill="x", pady=(0, 10))
        opt_in = tk.Frame(opt, bg=FLUENT["card"])
        opt_in.pack(fill="x", padx=12, pady=10)
        tk.Label(
            opt_in, text="Opciones de membresía",
            font=("Segoe UI Semibold", 10), fg=ACCENT_CYAN, bg=FLUENT["card"],
        ).pack(anchor="w", pady=(0, 6))
        row_o = tk.Frame(opt_in, bg=FLUENT["card"])
        row_o.pack(fill="x")
        tk.Label(row_o, text="Mes:", font=("Segoe UI", 9), fg=FG_MUTED, bg=FLUENT["card"]).pack(side="left")
        self.month_var = tk.StringVar(value=remixz_djtools.MESES[datetime.now().month - 1])
        self.month_cb = ttk.Combobox(
            row_o, textvariable=self.month_var, values=list(remixz_djtools.MESES),
            width=6, state="readonly",
        )
        self.month_cb.pack(side="left", padx=(6, 14))
        tk.Label(row_o, text="Año:", font=("Segoe UI", 9), fg=FG_MUTED, bg=FLUENT["card"]).pack(side="left")
        self.year_var = tk.StringVar(value=str(datetime.now().year))
        self.year_entry = ttk.Entry(row_o, textvariable=self.year_var, width=6)
        self.year_entry.pack(side="left", padx=(6, 14))
        self.recursive_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            row_o, text="Subcarpetas", variable=self.recursive_var,
            font=("Segoe UI", 9), fg=FG, bg=FLUENT["card"],
            activebackground=FLUENT["card"], selectcolor=FLUENT["input"],
            highlightthickness=0,
        ).pack(side="left", padx=(4, 10))
        self.preview_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            row_o, text="Solo preview (dry-run)", variable=self.preview_var,
            font=("Segoe UI", 9), fg=FG, bg=FLUENT["card"],
            activebackground=FLUENT["card"], selectcolor=FLUENT["input"],
            highlightthickness=0,
        ).pack(side="left")

        # Estado
        status_card = tk.Frame(
            body, bg=FLUENT["card"],
            highlightthickness=1, highlightbackground=FLUENT["border"],
        )
        status_card.pack(fill="x", pady=(0, 10))
        sc = tk.Frame(status_card, bg=FLUENT["card"])
        sc.pack(fill="x", padx=12, pady=10)
        tk.Label(
            sc, text="ESTADO DJ", font=("Segoe UI Semibold", 9),
            fg=FLUENT.get("text_dim", FG_MUTED), bg=FLUENT["card"],
        ).pack(anchor="w")
        self.dj_status = tk.Label(
            sc, text="DJ READY 🎧", font=("Segoe UI Semibold", 14),
            fg=ACCENT_GREEN, bg=FLUENT["card"],
        )
        self.dj_status.pack(anchor="w", pady=(2, 0))
        self.detail = tk.Label(
            sc, text="Elige carpeta y una acción.",
            font=("Segoe UI", 9), fg=FG_MUTED, bg=FLUENT["card"],
            anchor="w", justify="left", wraplength=640,
        )
        self.detail.pack(fill="x", pady=(4, 0))
        ff = remixz_djtools.find_ffmpeg()
        ff_txt = f"ffmpeg: {ff}" if ff else "ffmpeg: no encontrado → TITLE usará mutagen si está disponible"
        tk.Label(
            sc, text=ff_txt, font=("Consolas", 8),
            fg=ACCENT_CYAN if ff else ACCENT_ORANGE, bg=FLUENT["card"],
            anchor="w", wraplength=640, justify="left",
        ).pack(fill="x", pady=(6, 0))

        # Botones
        btn_row = tk.Frame(body, bg=BG)
        btn_row.pack(fill="x", pady=(0, 10))
        self.btn_rename = self.fluent.button(
            btn_row, "  Renombrar membresía  ", self._do_rename, kind="primary",
        )
        self.btn_rename.pack(side="left")
        self.btn_title = self.fluent.button(
            btn_row, "  Actualizar TITLE  ", self._do_title, kind="success",
        )
        self.btn_title.pack(side="left", padx=(10, 0))
        self.btn_preview = self.fluent.button(
            btn_row, "  Preview  ", self._do_preview, kind="secondary",
        )
        self.btn_preview.pack(side="left", padx=(10, 0))

        # Progreso (barra gradient)
        tk.Label(
            body, text="PROGRESO",
            font=("Segoe UI Semibold", 9), fg=FLUENT.get("text_dim", FG_MUTED), bg=BG,
        ).pack(anchor="w")
        prog_row = tk.Frame(body, bg=BG)
        prog_row.pack(fill="x", pady=(4, 4))
        self.prog = RoundedGradientProgress(
            prog_row, height=14, maximum=100, mode="determinate",
            colors=dict(FLUENT), gradient=(ACCENT, ACCENT_CYAN), bg=BG,
        )
        self.prog.pack(side="left", fill="x", expand=True)
        self.pct_lbl = tk.Label(
            prog_row, text="0%", font=("Segoe UI Semibold", 10),
            fg=ACCENT_CYAN, bg=BG, width=5,
        )
        self.pct_lbl.pack(side="right", padx=(10, 0))
        self.prog_msg = tk.Label(
            body, text="", font=("Segoe UI", 8), fg=FG_MUTED, bg=BG, anchor="w",
        )
        self.prog_msg.pack(fill="x")

        # Log
        log_shell = tk.Frame(
            body, bg=FLUENT["card"],
            highlightthickness=1, highlightbackground=FLUENT["border"],
        )
        log_shell.pack(fill="both", expand=True, pady=(8, 0))
        self.log = scrolledtext.ScrolledText(
            log_shell, height=8, font=("Consolas", 8),
            bg=BG_INPUT, fg=FG, insertbackground=FG, relief="flat",
            highlightthickness=0, state="disabled",
        )
        self.log.pack(fill="both", expand=True, padx=8, pady=8)

        tk.Label(
            body,
            text="Fuente: ClubRemix DJ Edition  ·  tag automático por mes",
            font=("Segoe UI", 8), fg=FLUENT.get("text_dim", FG_MUTED), bg=BG,
        ).pack(anchor="w", pady=(8, 0))

    def _current_tag(self) -> str:
        mes = (self.month_var.get() or "ENE").upper()
        try:
            m_idx = remixz_djtools.MESES.index(mes) + 1
        except ValueError:
            m_idx = datetime.now().month
        try:
            year = int(str(self.year_var.get()).strip() or datetime.now().year)
        except ValueError:
            year = datetime.now().year
        return remixz_djtools.clubremix_tag(month=m_idx, year=year)

    def _log(self, line: str):
        self.log.configure(state="normal")
        self.log.insert("end", line + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _browse(self):
        folder = filedialog.askdirectory(
            title="Carpeta para ClubRemix DJ Tools",
            initialdir=str(APP_DIR),
        )
        if not folder:
            return
        self._folder = folder
        n = len(remixz_djtools.get_media_files(folder, recursive=self.recursive_var.get()))
        self.folder_lbl.configure(text=folder, fg=FG)
        self.detail.configure(text=f"{n} archivos multimedia detectados.")
        self._log(f"Carpeta: {folder} ({n} media)")

    def _set_busy(self, busy: bool):
        self._busy = busy
        state = "disabled" if busy else "normal"
        for b in (self.btn_rename, self.btn_title, self.btn_preview):
            try:
                b.configure(state=state)
            except Exception:
                pass

    def _progress(self, cur: int, total: int, msg: str):
        def ui():
            pct = int(cur / total * 100) if total else 0
            try:
                self.prog.set(pct)
            except Exception:
                try:
                    self.prog.configure(value=pct)
                except Exception:
                    pass
            self.pct_lbl.configure(text=f"{pct}%")
            self.prog_msg.configure(text=msg)
        self.after(0, ui)

    def _do_preview(self):
        if self._busy:
            return
        if not self._folder:
            self.detail.configure(text="Selecciona una carpeta primero.")
            return
        tag = self._current_tag()
        info = remixz_djtools.preview_rename(
            self._folder, tag=tag, recursive=self.recursive_var.get(),
        )
        self._log(f"── Preview · tag: {tag}")
        self._log(f"Total: {info['total']} · renombrarían: {info['will_rename']} · iguales: {info['unchanged']}")
        for c in info.get("sample") or []:
            self._log(f"  {c['from']}")
            self._log(f"  → {c['to']}")
        self.detail.configure(
            text=f"Preview: {info['will_rename']}/{info['total']} se renombrarían · {tag}",
        )
        self.dj_status.configure(text="PREVIEW ✔", fg=ACCENT_CYAN)

    def _do_rename(self):
        if self._busy:
            return
        if not self._folder:
            self.detail.configure(text="Selecciona una carpeta primero.")
            return
        tag = self._current_tag()
        dry = bool(self.preview_var.get())
        self._cancel = False
        self._set_busy(True)
        self.dj_status.configure(text="DJ MIXING…  ▂ ▄ ▆ █ ▆ ▄ ▂", fg=ACCENT)
        try:
            self.prog.set(0)
        except Exception:
            pass
        self._log(f"── Renombrar · tag: {tag} · dry_run={dry}")

        def worker():
            result = remixz_djtools.rename_with_membership(
                self._folder,
                progress_cb=self._progress,
                tag=tag,
                recursive=self.recursive_var.get(),
                dry_run=dry,
                cancel_cb=lambda: self._cancel,
            )

            def done():
                self._set_busy(False)
                if result.get("cancelled"):
                    self.dj_status.configure(text="CANCELADO", fg=ACCENT_ORANGE)
                    self.detail.configure(text="Operación cancelada.")
                    return
                self.dj_status.configure(text="DJ READY 🎧", fg=ACCENT_GREEN)
                mode = " (preview)" if dry else ""
                self.detail.configure(
                    text=(
                        f"Renombrados{mode}: {result.get('renamed', 0)}  ·  "
                        f"omitidos: {result.get('skipped', 0)}  ·  "
                        f"errores: {result.get('errors', 0)}\nTag: {result.get('tag', tag)}"
                    ),
                )
                for line in (result.get("log") or [])[:25]:
                    self._log(line)
                self._log(
                    f"OK rename: {result.get('renamed')}/{result.get('total')} · err {result.get('errors')}"
                )
                try:
                    self.prog.set(100)
                    self.pct_lbl.configure(text="100%")
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
        tag = self._current_tag()
        self._cancel = False
        self._set_busy(True)
        self.dj_status.configure(text="DJ MIXING…", fg=ACCENT)
        try:
            self.prog.set(0)
        except Exception:
            pass
        self._log(f"── TITLE · tag: {tag}")

        def worker():
            result = remixz_djtools.update_titles_with_ffmpeg(
                self._folder,
                progress_cb=self._progress,
                tag=tag,
                recursive=self.recursive_var.get(),
                allow_mutagen=True,
                cancel_cb=lambda: self._cancel,
            )

            def done():
                self._set_busy(False)
                if not result.get("ok") and result.get("error"):
                    self.dj_status.configure(text="DJ ERROR", fg="#ff6b7a")
                    self.detail.configure(text=result["error"])
                    self._log(result["error"])
                    return
                self.dj_status.configure(text="DJ READY 🎧", fg=ACCENT_GREEN)
                via = []
                if result.get("via_ffmpeg"):
                    via.append(f"ffmpeg×{result['via_ffmpeg']}")
                if result.get("via_mutagen"):
                    via.append(f"mutagen×{result['via_mutagen']}")
                via_s = " · ".join(via) if via else result.get("method", "")
                self.detail.configure(
                    text=(
                        f"TITLE actualizado ✔  {result.get('updated', 0)}/{result.get('total', 0)}"
                        f"  ·  errores: {result.get('errors', 0)}\n"
                        f"Tag: {result.get('tag', tag)}  ·  {via_s}"
                    ),
                )
                self._log(
                    f"TITLE: {result.get('updated')}/{result.get('total')} · {via_s}"
                )
                try:
                    self.prog.set(100)
                    self.pct_lbl.configure(text="100%")
                except Exception:
                    pass

            self.after(0, done)

        threading.Thread(target=worker, daemon=True).start()


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

        # Barra gradient
        prow = tk.Frame(body, bg=c["surface"])
        prow.pack(fill="x")
        self.prog = RoundedGradientProgress(
            prow, height=14, maximum=100, mode="determinate",
            colors=dict(FLUENT), gradient=(ACCENT, ACCENT_CYAN), bg=c["surface"],
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
            self.prog["value"] = pct
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

    def finish_ok(self, message: str, on_restart=None, on_later=None):
        self._log_line("✓ Update completado")
        self._log_line(message)
        self.phase_lbl.configure(text="Update aplicado", fg=ACCENT_GREEN)
        self.detail_lbl.configure(text=message)
        self.prog["value"] = 100
        self.pct_lbl.configure(text="100%")
        self.protocol("WM_DELETE_WINDOW", lambda: self._done("later", on_later))

        for w in self.btn_row.winfo_children():
            w.destroy()
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
# App principal
# ---------------------------------------------------------------------------
class CleanerXApp(tk.Tk):
    """Bienvenida (updates) → notificación Fluent → Cleaner (1 opción)."""

    def __init__(self, *, start_hidden: bool = False, dep_report: dict | None = None):
        super().__init__()
        if start_hidden:
            self.withdraw()

        self.title(APP_TITLE)
        self.geometry("900x720")
        self.minsize(780, 640)
        self.configure(bg=BG)
        self._dj_win = None

        # Icono si existe
        ico = APP_DIR / "icono.ico"
        if ico.exists():
            try:
                self.iconbitmap(str(ico))
            except Exception:
                pass

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
        try:
            self.attributes("-alpha", 0.0)
        except tk.TclError:
            pass
        self.deiconify()
        self.lift()
        try:
            fade_in_window(self, steps=12, delay_ms=16)
        except Exception:
            try:
                self.attributes("-alpha", 1.0)
            except tk.TclError:
                pass
        self.after(350, self._welcome_check_updates)

    def _build(self):
        self.fluent.app_header(
            self,
            "Cleaner X",
            version=f"v{VERSION}",
            subtitle="Deps · updates · 1 opción",
        )

        self.stack = tk.Frame(self, bg=BG)
        self.stack.pack(fill="both", expand=True)

        self.welcome_frame = tk.Frame(self.stack, bg=BG)
        self.main_frame = tk.Frame(self.stack, bg=BG)

        self._build_welcome()
        self._build_main()

        bar = tk.Frame(self, bg=FLUENT["header"], height=30)
        bar.pack(side="bottom", fill="x")
        bar.pack_propagate(False)
        tk.Frame(bar, bg=ACCENT, height=2).pack(fill="x", side="top")
        self.footer_lbl = tk.Label(
            bar, text=f"v{VERSION} · bienvenida",
            font=("Segoe UI", 8), fg=FG_MUTED, bg=FLUENT["header"],
        )
        self.footer_lbl.pack(side="left", padx=12, pady=5)
        self.footer_right = tk.Label(
            bar, text="github.com/SMPROJECT115/remixz",
            font=("Segoe UI", 8), fg=FG_MUTED, bg=FLUENT["header"],
        )
        self.footer_right.pack(side="right", padx=12, pady=5)

        self._show_welcome()

    def _show_welcome(self):
        self.main_frame.pack_forget()
        self.welcome_frame.pack(fill="both", expand=True, padx=32, pady=24)

    def _show_main(self):
        self.welcome_frame.pack_forget()
        self.main_frame.pack(fill="both", expand=True, padx=24, pady=16)
        self.footer_lbl.configure(text=f"v{VERSION} · listo · 1 opción")

    def _card(self, parent, title: str = "", accent: str | None = None):
        """Card Fluent reutilizable."""
        ac = accent or ACCENT_CYAN
        shell = tk.Frame(
            parent, bg=FLUENT["card"],
            highlightthickness=1, highlightbackground=FLUENT["border"],
        )
        shell.pack(fill="x", pady=(0, 12))
        inner = tk.Frame(shell, bg=FLUENT["card"])
        inner.pack(fill="x", padx=16, pady=14)
        if title:
            head = tk.Frame(inner, bg=FLUENT["card"])
            head.pack(fill="x", pady=(0, 10))
            tk.Frame(head, bg=ac, width=3, height=16).pack(side="left", padx=(0, 8))
            tk.Label(
                head, text=title, font=("Segoe UI Semibold", 11),
                fg=ac, bg=FLUENT["card"], anchor="w",
            ).pack(side="left", fill="x")
        return shell, inner

    def _chip(self, parent, label: str, value: str, color: str | None = None):
        chip = tk.Frame(
            parent, bg=FLUENT["input"],
            highlightthickness=1, highlightbackground=FLUENT["border"],
        )
        chip.pack(side="left", padx=(0, 10), pady=2)
        tk.Label(
            chip, text=label, font=("Segoe UI", 8),
            fg=FG_MUTED, bg=FLUENT["input"],
        ).pack(padx=12, pady=(6, 0))
        val = tk.Label(
            chip, text=value, font=("Segoe UI Semibold", 12),
            fg=color or FG, bg=FLUENT["input"],
        )
        val.pack(padx=12, pady=(0, 8))
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

        # Hero
        hero = tk.Frame(f, bg=BG)
        hero.pack(fill="x", pady=(0, 8))
        tk.Label(
            hero, text="REMIXZ", font=("Segoe UI Black", 36),
            fg=ACCENT_CYAN, bg=BG,
        ).pack(anchor="w")
        tk.Label(
            hero, text="Bienvenido a Cleaner X",
            font=("Segoe UI Semibold", 18), fg=FG, bg=BG,
        ).pack(anchor="w", pady=(2, 4))
        tk.Frame(hero, bg=ACCENT, height=2, width=140).pack(anchor="w", pady=(0, 10))
        tk.Label(
            hero,
            text="Limpia nombres y metadatos RemixZ / Tio Dealer / WhatsApp en un solo paso.",
            font=("Segoe UI", 10), fg=FG_MUTED, bg=BG, anchor="w",
        ).pack(fill="x")

        # Chips de estado
        chips = tk.Frame(f, bg=BG)
        chips.pack(fill="x", pady=(12, 8))
        self._chip(chips, "VERSIÓN", f"v{VERSION}", ACCENT_CYAN)
        _, self.dep_chip_val = self._chip(chips, "DEPS", "…", ACCENT_ORANGE)
        self._chip(chips, "MODO", "1 opción", FG)

        # Card dependencias
        _, dep_body = self._card(f, "Dependencias", ACCENT)
        self.dep_status = tk.Label(
            dep_body,
            text=self._dep_report.get("detail") or "Comprobadas al iniciar.",
            font=("Consolas", 9),
            fg=FG_MUTED, bg=FLUENT["card"],
            anchor="w", justify="left", wraplength=680,
        )
        self.dep_status.pack(fill="x")

        # Card updates
        _, up_body = self._card(f, "Estado de actualizaciones", ACCENT_CYAN)
        self.welcome_status = tk.Label(
            up_body,
            text="Validando updates desde el repositorio…",
            font=("Segoe UI", 9),
            fg=FG_MUTED, bg=FLUENT["card"],
            anchor="w", wraplength=680, justify="left",
        )
        self.welcome_status.pack(fill="x")

        self.welcome_prog = ttk.Progressbar(
            f, mode="indeterminate", style="Fluent.Horizontal.TProgressbar",
        )
        self.welcome_prog.pack(fill="x", pady=(4, 0))

        tk.Label(
            f,
            text="Al terminar se mostrará una notificación. Pulsa OK para iniciar Cleaner X.",
            font=("Segoe UI", 9), fg=FG_MUTED, bg=BG, anchor="w",
        ).pack(fill="x", pady=(14, 0))

    def _build_main(self):
        body = self.main_frame

        # Título + descripción
        top = tk.Frame(body, bg=BG)
        top.pack(fill="x", pady=(0, 12))
        tk.Label(
            top, text="RemixZ Cleaner X",
            font=("Segoe UI Semibold", 20), fg=ACCENT_CYAN, bg=BG, anchor="w",
        ).pack(fill="x")
        tk.Label(
            top,
            text="Una sola opción: elige carpeta y limpia nombres / metadatos.",
            font=("Segoe UI", 10), fg=FG_MUTED, bg=BG, anchor="w",
        ).pack(fill="x", pady=(4, 0))
        tk.Frame(top, bg=ACCENT, height=2, width=100).pack(anchor="w", pady=(8, 0))

        # Acción principal en card
        _, action = self._card(body, "Acción principal", ACCENT_GREEN)
        row = tk.Frame(action, bg=FLUENT["card"])
        row.pack(fill="x")
        self.main_btn = self.fluent.button(
            row, "  Limpiar carpeta  ", self._run_once, kind="success", width=22,
        )
        self.main_btn.pack(side="left")
        self.main_btn.configure(font=("Segoe UI Semibold", 12), pady=12)

        self.path_lbl = tk.Label(
            row,
            text="  Carpeta: (ninguna seleccionada)",
            font=("Segoe UI", 9), fg=FG_MUTED, bg=FLUENT["card"],
            anchor="w", wraplength=420, justify="left",
        )
        self.path_lbl.pack(side="left", fill="x", expand=True, padx=(14, 0))

        # ClubRemix DJ Tools (desbloqueado en v3.2)
        _, dj_action = self._card(body, "ClubRemix DJ Tools", ACCENT)
        dj_row = tk.Frame(dj_action, bg=FLUENT["card"])
        dj_row.pack(fill="x")
        self.dj_btn = self.fluent.button(
            dj_row, "  Abrir DJ Tools  ", self._open_djtools, kind="primary", width=20,
        )
        self.dj_btn.pack(side="left")
        tk.Label(
            dj_row,
            text="Renombrar membresía · TITLE · preview · barra de progreso",
            font=("Segoe UI", 9), fg=FG_MUTED, bg=FLUENT["card"],
            anchor="w",
        ).pack(side="left", fill="x", expand=True, padx=(12, 0))

        # Log en card
        log_shell = tk.Frame(
            body, bg=FLUENT["card"],
            highlightthickness=1, highlightbackground=FLUENT["border"],
        )
        log_shell.pack(fill="both", expand=True, pady=(0, 10))
        log_head = tk.Frame(log_shell, bg=FLUENT["card"])
        log_head.pack(fill="x", padx=14, pady=(12, 6))
        tk.Frame(log_head, bg=ACCENT_CYAN, width=3, height=14).pack(side="left", padx=(0, 8))
        tk.Label(
            log_head, text="Registro", font=("Segoe UI Semibold", 11),
            fg=ACCENT_CYAN, bg=FLUENT["card"],
        ).pack(side="left")
        self.log = scrolledtext.ScrolledText(
            log_shell,
            height=9,
            font=("Consolas", 9),
            bg=BG_INPUT, fg=FG, insertbackground=FG,
            relief="flat",
            highlightthickness=0,
            state="disabled",
        )
        self.log.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        # Progreso — barra gradient (Fluent)
        tk.Label(
            body, text="Progreso",
            font=("Segoe UI Semibold", 9), fg=FLUENT.get("text_dim", FG_MUTED), bg=BG,
            anchor="w",
        ).pack(fill="x")
        prog_row = tk.Frame(body, bg=BG)
        prog_row.pack(fill="x", pady=(4, 0))
        self.prog = RoundedGradientProgress(
            prog_row,
            height=14,
            maximum=100,
            mode="determinate",
            colors=dict(FLUENT),
            gradient=(ACCENT, ACCENT_CYAN),
            bg=BG,
        )
        self.prog.pack(fill="x", side="left", expand=True)
        self.pct_lbl = tk.Label(
            prog_row, text="0%", font=("Segoe UI Semibold", 10),
            fg=ACCENT_CYAN, bg=BG, width=5,
        )
        self.pct_lbl.pack(side="right", padx=(10, 0))

        self.status = tk.Label(
            body,
            text="Listo. Pulsa «Limpiar carpeta» o abre ClubRemix DJ Tools.",
            font=("Segoe UI", 9), fg=FG_MUTED, bg=BG, anchor="w",
        )
        self.status.pack(fill="x", pady=(6, 0))

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
        """Muestra ventana de reinicio y relanza el aplicativo."""
        self.notify(
            "Reiniciando aplicación",
            "El update se aplicó correctamente.\n\n"
            "Al pulsar OK se cerrará Cleaner X y se abrirá\n"
            "de nuevo con la versión actualizada.\n\n"
            "Espera un momento…",
            kind="success",
            buttons=[("OK — Reiniciar", "ok")],
            on_result=lambda _k: self.after(350, restart_application),
        )

    def _apply_update_then_start(self):
        """Al pulsar Aplicar: abre ventana de progreso y muestra cada paso."""
        info = self._update_info
        if not info or not info.download_url:
            self._start_after_ok()
            return

        self._busy = True
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
        win._log_line(f"URL: {(info.download_url or '')[:70]}…")

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
                        self.welcome_status.configure(text=message, fg=ACCENT_GREEN)
                        self.footer_lbl.configure(text=f"v{VERSION} · update listo")
                    except Exception:
                        pass

                    def after_restart_choice():
                        # Viene de finish_ok con "Reiniciar ahora"
                        self._restart_after_update()

                    def after_later():
                        self._start_after_ok()

                    try:
                        win.finish_ok(
                            message,
                            on_restart=after_restart_choice,
                            on_later=after_later,
                        )
                    except Exception:
                        self._restart_after_update()
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

    def _set_progress(self, value: int):
        v = max(0, min(100, int(value)))
        try:
            self.prog.set(v)
        except Exception:
            try:
                self.prog.configure(value=v)
            except Exception:
                pass
        self.pct_lbl.configure(text=f"{v}%")

    def _open_djtools(self):
        """Abre ClubRemix DJ Tools (desbloqueado en v3.2)."""
        try:
            if getattr(self, "_dj_win", None) is not None:
                try:
                    self._dj_win.lift()
                    self._dj_win.focus_force()
                    return
                except Exception:
                    self._dj_win = None
        except Exception:
            pass
        self._dj_win = DJToolsWindow(self)
        self._append_log("DJ Tools: panel ClubRemix abierto.")

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
        self.main_btn.configure(state="disabled")
        self.path_lbl.configure(text=f"  Carpeta: {folder}", fg=ACCENT_CYAN)
        self._clear_log()
        self._set_progress(0)
        self.status.configure(text="Escaneando archivos…", fg=ACCENT_ORANGE)
        self._append_log(f"Carpeta: {folder}")
        self._append_log("Modo: 1 opción — escanear + limpiar")
        self._append_log("─" * 44)

        def worker():
            try:
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
                    self.call_ui(self.status.configure, text="Sin archivos.", fg=FG_MUTED)
                    return

                self.call_ui(self._append_log, "─" * 44)
                self.call_ui(self._append_log, "Limpiando…")
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

    # Un solo root Tk: app oculta + splash Toplevel
    app = CleanerXApp(start_hidden=True, dep_report={})
    try:
        app.attributes("-alpha", 0.0)
    except tk.TclError:
        pass

    splash = LoadingSplash(
        APP_TITLE,
        version=f"v{VERSION}",
        colors=dict(FLUENT),
        master=app,
    )
    splash.set_status("Preparando Cleaner X…", 5, step=0)
    app.update_idletasks()

    dep_report: dict = {}
    boot_error: str | None = None

    def set_status(text: str):
        splash.set_status(text)
        try:
            app.update_idletasks()
        except Exception:
            pass

    def set_progress(percent: int):
        splash.set_status(splash.status.cget("text"), percent)
        try:
            app.update_idletasks()
        except Exception:
            pass

    def boot():
        nonlocal dep_report, boot_error
        try:
            # 1) Dependencias: revisar e instalar si faltan
            splash.set_status("Comprobando dependencias…", 12, step=1)
            app.update()
            dep_report = ensure_packages(status_cb=set_status, progress_cb=set_progress)
            try:
                app.refresh_dep_ui(dep_report)
            except Exception:
                app._dep_report = dep_report

            if not dep_report.get("tkinter") and not getattr(sys, "frozen", False):
                boot_error = "tkinter no disponible. Instala Python con Tcl/Tk."
                splash.set_status(boot_error, 100, step=1)
                app.update()
                time.sleep(1.2)

            # Solo avisar si falta algo crítico (mutagen); colorama/psutil son opcionales
            if not dep_report.get("ok"):
                left = ", ".join(m[0] for m in (dep_report.get("missing") or []) if m[0] == "mutagen")
                if left:
                    set_status(f"Falta: {left}")
                else:
                    set_status("Deps opcionales con fallback — continúa")

            # 2) Motor Cleaner (tras deps)
            splash.set_status("Cargando motor Cleaner…", 72, step=2)
            app.update()
            try:
                load_cleaner_module()
                try:
                    app.config_data = cleaner.cargar_config()
                except Exception:
                    app.config_data = {}
            except Exception as exc:
                boot_error = f"No se pudo cargar el motor: {exc}"
                splash.set_status(boot_error, 100)
                app.update()
                time.sleep(1.0)

            # 3) Interfaz
            splash.set_status("Abriendo bienvenida…", 92, step=3)
            app.update()
            time.sleep(0.05)
            splash.set_status("Listo", 100, step=3)
            app.update()
        except Exception as exc:
            boot_error = str(exc)
            try:
                splash.set_status(f"Error: {exc}", 100)
            except Exception:
                pass

        def show_app():
            if boot_error or not dep_report.get("ok", True):
                detail = (boot_error or "Algunas dependencias no están completas.")
                detail = f"{detail}\n\n{dep_report.get('detail', '')}".strip()

                def after_dep_warn(_k):
                    app.after(200, app._welcome_check_updates)

                def reveal_and_warn():
                    try:
                        app.attributes("-alpha", 0.0)
                    except tk.TclError:
                        pass
                    app.deiconify()
                    app.lift()
                    try:
                        fade_in_window(app, steps=12, delay_ms=16)
                    except Exception:
                        try:
                            app.attributes("-alpha", 1.0)
                        except tk.TclError:
                            pass
                    app.after(
                        350,
                        lambda: app.notify(
                            "Dependencias",
                            detail,
                            kind="warning",
                            buttons=[("OK", "ok")],
                            on_result=after_dep_warn,
                        ),
                    )

                reveal_and_warn()
            else:
                app.reveal()

        try:
            if hasattr(splash, "fade_out_and_destroy"):
                splash.fade_out_and_destroy(on_done=show_app)
            else:
                splash.destroy()
                show_app()
        except Exception:
            try:
                splash.destroy()
            except Exception:
                pass
            show_app()

    app.after(60, boot)
    app.mainloop()


if __name__ == "__main__":
    main()
