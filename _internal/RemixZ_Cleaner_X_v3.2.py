#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# TRACK Whatsapp 755 114 6718
#album Remixz Membresia Abril 2k26
#compositor Tio Dealer

# --- stdlib mínimo primero (sin terceros) ---
import os
import sys
from pathlib import Path

# =====================================================
# PATHS: lib + _internal + MEIPASS (nunca romper stdlib)
# =====================================================

def _engine_app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _engine_bootstrap_paths() -> None:
    """Añade lib/_internal sin quitar rutas del intérprete (platform, etc.)."""
    base = _engine_app_dir()
    meipass = getattr(sys, "_MEIPASS", None)
    # Orden: bundle EXE primero (stdlib frozen), luego lib local, _internal, app
    ordered = []
    if meipass:
        ordered.append(Path(meipass))
    ordered.extend([
        base / "_internal",
        base / "lib",
        base,
    ])
    for p in reversed(ordered):
        try:
            if not p or not Path(p).exists():
                continue
            s = str(Path(p).resolve())
            # no insertar si ya está al inicio
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


_engine_bootstrap_paths()

# --- resto stdlib (tras paths; platform con fallback) ---
import re
import time
import json
import getpass
import datetime
import threading
import socket
import shutil
import subprocess
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import platform
except ImportError:  # pragma: no cover
    # Fallback si el path del EXE se corrompió
    class platform:  # type: ignore
        @staticmethod
        def system():
            return os.name == "nt" and "Windows" or "Unknown"

        @staticmethod
        def release():
            return ""

        @staticmethod
        def architecture():
            return ("64bit", "") if sys.maxsize > 2**32 else ("32bit", "")

        @staticmethod
        def processor():
            return ""

        @staticmethod
        def node():
            return ""

        @staticmethod
        def machine():
            return ""


# =====================================================
# AUTO INSTALADOR Y DEPENDENCIAS (robusto / EXE / lib / vendor)
# =====================================================


def instalar_dependencias():
    """Asegura mutagen/colorama/psutil vía lib/vendor/pip."""
    _engine_bootstrap_paths()
    paquetes = ["mutagen", "colorama", "psutil"]
    missing = []
    for paquete in paquetes:
        try:
            __import__(paquete)
        except ImportError:
            missing.append(paquete)

    if not missing:
        return True

    base = _engine_app_dir()
    lib = base / "lib"
    vendor = base / "vendor"
    lib.mkdir(parents=True, exist_ok=True)

    # 1) Extraer wheels de vendor/ a lib/
    if vendor.exists():
        import zipfile
        for whl in vendor.glob("*.whl"):
            name = whl.name.lower()
            if not any(name.startswith(p + "-") or name.startswith(p.replace("-", "_") + "-") for p in missing):
                # también extraer todos si hay missing
                pass
            try:
                with zipfile.ZipFile(whl, "r") as zf:
                    zf.extractall(lib)
            except Exception:
                pass
        _engine_bootstrap_paths()
        still = []
        for p in missing:
            try:
                __import__(p)
            except ImportError:
                still.append(p)
        missing = still
        if not missing:
            return True

    # 2) pip --target=lib (python.exe, no pythonw)
    if getattr(sys, "frozen", False):
        # en EXE no usamos el propio binario; intentar py/python del sistema
        py_candidates = []
        local = os.environ.get("LOCALAPPDATA", "")
        if local:
            for ver in ("Python312", "Python311", "Python313", "Python310"):
                py_candidates.append(
                    str(Path(local) / "Programs" / "Python" / ver / "python.exe")
                )
        py_candidates.append("py")
    else:
        exe = sys.executable
        if exe.lower().endswith("pythonw.exe"):
            alt = exe[:-10] + "python.exe"
            py_candidates = [alt if Path(alt).exists() else exe]
        else:
            py_candidates = [exe]

    for py in py_candidates:
        if not missing:
            break
        try:
            cmd = [py]
            if py == "py":
                cmd += ["-3"]
            cmd += [
                "-m", "pip", "install", "--target", str(lib),
                "--upgrade", "--disable-pip-version-check", "-q",
                *missing,
            ]
            if vendor.exists() and list(vendor.glob("*.whl")):
                cmd = [py]
                if py == "py":
                    cmd += ["-3"]
                cmd += [
                    "-m", "pip", "install", "--target", str(lib),
                    "--upgrade", "--no-index", "--find-links", str(vendor),
                    "--disable-pip-version-check", "-q",
                    *missing,
                ]
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            subprocess.check_call(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=flags, timeout=300,
            )
            _engine_bootstrap_paths()
            still = []
            for p in missing:
                try:
                    sys.modules.pop(p, None)
                    __import__(p)
                except ImportError:
                    still.append(p)
            missing = still
        except Exception:
            continue

    return len(missing) == 0


instalar_dependencias()


# --- colorama (opcional: fallback sin colores) ---
try:
    from colorama import init, Fore, Back, Style
    init(autoreset=True)
    COLORAMA_OK = True
except Exception:
    COLORAMA_OK = False

    class _Empty:
        def __getattr__(self, _name):
            return ""

    Fore = Back = Style = _Empty()  # type: ignore

    def init(*_a, **_k):  # type: ignore
        return None


# --- mutagen (crítico para metadatos; fallback no-op si falta) ---
MUTAGEN_OK = False
try:
    from mutagen.id3 import ID3, ID3NoHeaderError
    from mutagen.mp4 import MP4, MP4StreamInfoError
    from mutagen.wave import WAVE
    MUTAGEN_OK = True
except Exception:
    class ID3NoHeaderError(Exception):
        pass

    class MP4StreamInfoError(Exception):
        pass

    class ID3(dict):  # type: ignore
        def __init__(self, *_a, **_k):
            super().__init__()
            raise ID3NoHeaderError("mutagen no instalado")

        def save(self, *_a, **_k):
            pass

    class MP4(dict):  # type: ignore
        def __init__(self, *_a, **_k):
            super().__init__()
            raise MP4StreamInfoError("mutagen no instalado")

        def save(self, *_a, **_k):
            pass

    class WAVE:  # type: ignore
        def __init__(self, *_a, **_k):
            self.tags = None

        def save(self, *_a, **_k):
            pass


# --- psutil (opcional) ---
try:
    import psutil
    PSUTIL_OK = True
except Exception:
    psutil = None  # type: ignore
    PSUTIL_OK = False


# =====================================================
# CONFIGURACION
# =====================================================

VERSION = "3.2"
APP_NAME = "RemixZ Cleaner X"
AUTHOR = "Tio Dealer / SMOD"

LOGO = [
    "  ██████╗ ███████╗███╗   ███╗██╗██╗  ██╗",
    "  ██╔══██╗██╔════╝████╗ ████║██║╚██╗██╔╝",
    "  ██████╔╝█████╗  ██╔████╔██║██║ ╚███╔╝ ",
    "  ██╔══██╗██╔══╝  ██║╚██╔╝██║██║ ██╔██╗ ",
    "  ██║  ██║███████╗██║ ╚═╝ ██║██║██╔╝ ██╗",
    "  ╚═╝  ╚═╝╚══════╝╚═╝     ╚═╝╚═╝╚═╝  ╚═╝",
]

EXTENSIONES = {
    ".mp3", ".m4a", ".wav", ".flac", ".ogg", ".wma", ".aac",
    ".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv",
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"
}

EXT_AUDIO = {".mp3", ".m4a", ".wav", ".flac", ".ogg", ".wma", ".aac"}
EXT_VIDEO = {".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv"}
EXT_IMG = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}

CONFIG_FILE = "config.json"
MARCADORES_SUCIOS = [
    "remixz", "tio dealer", "755", "whatsapp", "membresia", "abril 2k26",
    "julio 2k26", "todo para dj", "music dealer"
]

DEFAULT_CONFIG = {
    "tema": "classic",
    "hilos": os.cpu_count() or 4,
    "confirmar_salida": True,
    "analizar_antes_limpiar": True,
    "patrones": [
        r"\[?\s*Remixz\s*By\s*Tio\s*Dealer\s*\]?",
        r"#?\s*TRACK\s*WhatsApp\s*755\s*114\s*6718",
        r"#?\s*WhatsApp\s*755\s*114\s*6718",
        r"#?\s*album\s*Remixz\s*Membresia\s*Abril\s*2k26",
        r"#?\s*compositor\s*Tio\s*Dealer",
        r"Tio\s*Dealer",
        r"DISCNUMBER",
        r"TRACK",
        r"\s*Todo\s*Para\s*DJ"
    ]
}

THEMES = {
    "classic": {
        "primary": Fore.CYAN,
        "accent": Fore.GREEN,
        "warning": Fore.YELLOW,
        "error": Fore.RED,
        "info": Fore.WHITE,
        "muted": Fore.LIGHTBLACK_EX,
        "highlight": Fore.CYAN,
        "badge": Back.BLUE + Fore.WHITE,
    },
    "dark": {
        "primary": Fore.MAGENTA,
        "accent": Fore.GREEN,
        "warning": Fore.YELLOW,
        "error": Fore.RED,
        "info": Fore.WHITE,
        "muted": Fore.LIGHTBLACK_EX,
        "highlight": Fore.MAGENTA,
        "badge": Back.MAGENTA + Fore.WHITE,
    },
    "minimal": {
        "primary": Fore.WHITE,
        "accent": Fore.GREEN,
        "warning": Fore.YELLOW,
        "error": Fore.RED,
        "info": Fore.LIGHTWHITE_EX,
        "muted": Fore.LIGHTBLACK_EX,
        "highlight": Fore.WHITE,
        "badge": Back.WHITE + Fore.BLACK,
    },
    "neon": {
        "primary": Fore.CYAN,
        "accent": Fore.GREEN,
        "warning": Fore.YELLOW,
        "error": Fore.RED,
        "info": Fore.WHITE,
        "muted": Fore.LIGHTBLACK_EX,
        "highlight": Fore.LIGHTCYAN_EX,
        "badge": Back.CYAN + Fore.BLACK,
    },
}


def cargar_config():
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, indent=4)
        return DEFAULT_CONFIG.copy()
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return DEFAULT_CONFIG.copy()


def guardar_config(config):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)


def escribir_log(archivo, acciones, tipo="procesados"):
    if not os.path.exists("logs"):
        os.makedirs("logs")
    fecha = datetime.datetime.now().strftime("%Y-%m-%d")
    hora = datetime.datetime.now().strftime("%H:%M:%S")
    ruta_log = f"logs/{tipo}_{fecha}.log"
    with open(ruta_log, "a", encoding="utf-8") as f:
        f.write(f"[{hora}] {archivo:<40} -> {', '.join(acciones) if acciones else 'OK'}\n")


# =====================================================
# INTERFAZ PROFESIONAL
# =====================================================

class ConsoleUI:
    BOX_W = 72

    def __init__(self, config):
        self.config = config
        self.theme = THEMES.get(config.get("tema", "classic"), THEMES["classic"])
        self._lock = threading.Lock()

    def _c(self, key):
        return self.theme.get(key, Fore.WHITE)

    def _width(self):
        try:
            return max(60, min(shutil.get_terminal_size().columns, 100))
        except Exception:
            return self.BOX_W

    def _pad(self, text, width, align="left"):
        plain = Style.RESET_ALL.join(re.split(r"\x1b\[[0-9;]*m", str(text)))
        visible = len(plain)
        if visible >= width:
            return text[:width]
        space = width - visible
        if align == "center":
            left = space // 2
            return " " * left + text + " " * (space - left)
        if align == "right":
            return " " * space + text
        return text + " " * space

    def clear(self):
        os.system("cls" if os.name == "nt" else "clear")

    def set_title(self):
        if os.name == "nt":
            os.system(f"title {APP_NAME} v{VERSION} - Developed by SMOD")

    def logo_banner(self):
        for line in LOGO:
            print(self._c("primary") + line + Style.RESET_ALL)
        print(
            self._c("muted") + "       CLASSIC EDITION  "
            + self._c("accent") + f"v{VERSION}"
            + self._c("muted") + "  |  "
            + self._c("highlight") + f"Tema: {self.config.get('tema', 'classic')}"
            + Style.RESET_ALL
        )
        print()

    @staticmethod
    def _icon_ext(path):
        ext = Path(path).suffix.lower()
        if ext in EXT_AUDIO: return "♫"
        if ext in EXT_VIDEO: return "▶"
        if ext in EXT_IMG: return "◆"
        return "•"

    @staticmethod
    def _mini_bar(value, total, width=12):
        if total <= 0:
            return "░" * width
        filled = int(value / total * width)
        return "█" * filled + "░" * (width - filled)

    def rule(self, char="─"):
        w = self._width()
        print(self._c("muted") + char * w + Style.RESET_ALL)

    def spacer(self, lines=1):
        print("\n" * (lines - 1))

    def _box_line(self, content, width, border="│"):
        inner = width - 2
        return (
            self._c("primary") + border
            + self._pad(content, inner)
            + self._c("primary") + border
            + Style.RESET_ALL
        )

    def panel(self, title, lines, footer=None):
        w = min(self._width(), self.BOX_W)
        top = "╔" + "═" * (w - 2) + "╗"
        mid = "╠" + "═" * (w - 2) + "╣"
        bot = "╚" + "═" * (w - 2) + "╝"
        print(self._c("primary") + top)
        print(self._box_line(
            self._c("highlight") + f" {title} " + Style.RESET_ALL,
            w, "║"
        ))
        print(self._c("primary") + mid)
        for line in lines:
            print(self._box_line(" " + line, w, "║"))
        if footer:
            print(self._c("primary") + mid)
            print(self._box_line(" " + footer, w, "║"))
        print(self._c("primary") + bot + Style.RESET_ALL)

    def header(self):
        print()
        self.logo_banner()
        fecha = datetime.datetime.now().strftime("%d/%m/%Y  %H:%M")
        hilos = self.config.get("hilos", 4)
        self.panel(
            "PANEL DE CONTROL",
            [
                self._c("info") + "Motor" + Style.RESET_ALL
                + self._c("muted") + " ··········· " + Style.RESET_ALL
                + self._c("accent") + "Limpieza profunda de metadatos",
                self._c("info") + "Formatos" + Style.RESET_ALL
                + self._c("muted") + " ········ " + Style.RESET_ALL
                + self._c("highlight") + "MP3 · WAV · MP4 · M4A · Imagen",
                self._c("info") + "Hilos" + Style.RESET_ALL
                + self._c("muted") + " ············ " + Style.RESET_ALL
                + self._c("accent") + f"{hilos} concurrentes",
                self._c("info") + "Sesion" + Style.RESET_ALL
                + self._c("muted") + " ··········· " + Style.RESET_ALL
                + self._c("accent") + fecha,
            ],
            footer=self._c("muted") + f"{AUTHOR}  |  TRACK WhatsApp 755 114 6718" + Style.RESET_ALL,
        )

    def splash(self):
        self.clear()
        print("\n")
        self.logo_banner()
        pasos = [
            "Cargando modulos",
            "Verificando dependencias",
            "Inicializando motor ID3/MP4",
            "Preparando interfaz",
            "Listo",
        ]
        for paso_idx, paso in enumerate(pasos):
            for i in range(21):
                pct = min(100, paso_idx * 20 + i)
                filled = "█" * (pct // 5)
                empty = "░" * (20 - pct // 5)
                bar = f"  [{filled}{empty}] {pct:>3}%  {paso}"
                sys.stdout.write("\r" + self._c("primary") + bar + Style.RESET_ALL)
                sys.stdout.flush()
                time.sleep(0.012)
        print(self._c("accent") + "\n\n  ✓ Sistema preparado\n" + Style.RESET_ALL)
        time.sleep(0.3)

    def menu(self):
        items = [
            ("1", "♫", "Limpiar carpeta o archivo", "Escaneo + limpieza profunda"),
            ("2", "◎", "Analizar metadatos ID3", "MP3 y WAV sin modificar"),
            ("3", "⬇", "Drag & Drop (.exe)", "Arrastra carpeta al ejecutable"),
            ("4", "ℹ", "Informacion del sistema", "CPU, RAM y entorno"),
            ("5", "⚙", "Ajustes", f"Tema {self.config.get('tema')} · {self.config.get('hilos')} hilos"),
            ("0", "✕", "Salir", "Cerrar aplicacion"),
        ]
        w = min(self._width(), self.BOX_W)
        print(self._c("primary") + "┌" + "─" * (w - 2) + "┐")
        print(self._box_line(self._c("highlight") + " MENU PRINCIPAL " + Style.RESET_ALL, w, "│"))
        print(self._c("primary") + "├" + "─" * (w - 2) + "┤")
        for key, icon, label, desc in items:
            color = self._c("error") if key == "0" else self._c("accent")
            row = (
                color + f" {icon} [{key}] "
                + self._c("info") + label
                + self._c("muted") + f"  -  {desc}"
                + Style.RESET_ALL
            )
            print(self._box_line(row, w, "│"))
        print(self._c("primary") + "└" + "─" * (w - 2) + "┘")
        print(self._c("muted") + "  Tip: arrastra una carpeta sobre el .exe para limpiar directo" + Style.RESET_ALL)
        print()
        return input(self._c("warning") + "  Opcion › " + Style.RESET_ALL).strip()

    def menu_ajustes(self):
        while True:
            self.clear()
            self.header()
            temas = ", ".join(THEMES.keys())
            self.panel(
                "AJUSTES",
                [
                    self._c("info") + "[1] Hilos" + Style.RESET_ALL
                    + self._c("muted") + " ········· " + Style.RESET_ALL
                    + self._c("accent") + str(self.config.get("hilos", 4)),
                    self._c("info") + "[2] Tema visual" + Style.RESET_ALL
                    + self._c("muted") + " · " + Style.RESET_ALL
                    + self._c("accent") + self.config.get("tema", "classic"),
                    self._c("info") + "[3] Analizar antes de limpiar" + Style.RESET_ALL
                    + self._c("muted") + " " + Style.RESET_ALL
                    + self._c("accent") + ("Si" if self.config.get("analizar_antes_limpiar", True) else "No"),
                    self._c("info") + "[4] Confirmar al salir" + Style.RESET_ALL
                    + self._c("muted") + " · " + Style.RESET_ALL
                    + self._c("accent") + ("Si" if self.config.get("confirmar_salida", True) else "No"),
                    self._c("muted") + "[0] Volver al menu",
                ],
                footer=self._c("muted") + f"Temas: {temas}" + Style.RESET_ALL,
            )
            op = input(self._c("warning") + "\n  Opcion › " + Style.RESET_ALL).strip()
            if op == "0":
                return
            elif op == "1":
                try:
                    n = int(input(self._c("info") + f"  Hilos (1-{os.cpu_count() or 8}): " + Style.RESET_ALL))
                    self.config["hilos"] = max(1, min(n, (os.cpu_count() or 8) * 2))
                    self.theme = THEMES.get(self.config.get("tema", "classic"), THEMES["classic"])
                except ValueError:
                    self.status("warn", "Valor invalido.")
            elif op == "2":
                nuevo = input(self._c("info") + f"  Tema ({temas}): " + Style.RESET_ALL).strip().lower()
                if nuevo in THEMES:
                    self.config["tema"] = nuevo
                    self.theme = THEMES[nuevo]
            elif op == "3":
                self.config["analizar_antes_limpiar"] = not self.config.get("analizar_antes_limpiar", True)
            elif op == "4":
                self.config["confirmar_salida"] = not self.config.get("confirmar_salida", True)
            else:
                self.status("warn", "Opcion no valida.")
            guardar_config(self.config)

    def prompt_path(self):
        print()
        self.panel(
            "SELECCIONAR RUTA",
            [
                self._c("info") + "Arrastra una carpeta o archivo" + Style.RESET_ALL,
                self._c("muted") + "Tambien puedes pegar la ruta completa" + Style.RESET_ALL,
                self._c("highlight") + "Ej: E:\\Musica\\Latin" + Style.RESET_ALL,
            ],
        )
        return input(self._c("primary") + "  Ruta › " + Style.RESET_ALL).strip('" ')

    def info_sistema(self):
        lines = [
            self._c("info") + "Usuario" + Style.RESET_ALL
            + self._c("muted") + " ············· " + Style.RESET_ALL
            + self._c("accent") + getpass.getuser(),
            self._c("info") + "Equipo" + Style.RESET_ALL
            + self._c("muted") + " ··············· " + Style.RESET_ALL
            + self._c("accent") + socket.gethostname(),
            self._c("info") + "Sistema" + Style.RESET_ALL
            + self._c("muted") + " ············· " + Style.RESET_ALL
            + self._c("accent") + f"{platform.system()} {platform.release()}",
            self._c("info") + "Arquitectura" + Style.RESET_ALL
            + self._c("muted") + " ········ " + Style.RESET_ALL
            + self._c("accent") + platform.architecture()[0],
            self._c("info") + "Procesador" + Style.RESET_ALL
            + self._c("muted") + " ·········· " + Style.RESET_ALL
            + self._c("accent") + (platform.processor() or "N/D")[:40],
            self._c("info") + "Hilos activos" + Style.RESET_ALL
            + self._c("muted") + " ········ " + Style.RESET_ALL
            + self._c("accent") + str(self.config.get("hilos", 4)),
        ]
        if PSUTIL_OK:
            ram = psutil.virtual_memory()
            cpu = psutil.cpu_percent(interval=0.1)
            lines.append(
                self._c("info") + "Memoria RAM" + Style.RESET_ALL
                + self._c("muted") + " ······· " + Style.RESET_ALL
                + self._c("accent") + f"{ram.total / (1024**3):.1f} GB ({ram.percent}% uso)"
            )
            lines.append(
                self._c("info") + "CPU actual" + Style.RESET_ALL
                + self._c("muted") + " ········ " + Style.RESET_ALL
                + self._c("accent") + f"{cpu}%"
            )
        self.panel("INFORMACIÓN DEL SISTEMA", lines)
        input(self._c("muted") + "\n  Presiona ENTER para volver al menú..." + Style.RESET_ALL)

    def scan_summary(self, archivos):
        c_audio = sum(1 for f in archivos if f.suffix.lower() in EXT_AUDIO)
        c_video = sum(1 for f in archivos if f.suffix.lower() in EXT_VIDEO)
        c_img = sum(1 for f in archivos if f.suffix.lower() in EXT_IMG)
        total = len(archivos)

        rows = [
            self._c("info") + "Total" + Style.RESET_ALL
            + self._c("muted") + " ········· " + Style.RESET_ALL
            + self._c("accent") + f"{total} archivos",
            self._c("info") + "♫ Audio" + Style.RESET_ALL
            + self._c("muted") + " ··· " + Style.RESET_ALL
            + self._c("primary") + self._mini_bar(c_audio, total) + " "
            + self._c("highlight") + str(c_audio),
            self._c("info") + "▶ Video" + Style.RESET_ALL
            + self._c("muted") + " ··· " + Style.RESET_ALL
            + self._c("primary") + self._mini_bar(c_video, total) + " "
            + self._c("highlight") + str(c_video),
            self._c("info") + "◆ Imagen" + Style.RESET_ALL
            + self._c("muted") + " · " + Style.RESET_ALL
            + self._c("primary") + self._mini_bar(c_img, total) + " "
            + self._c("highlight") + str(c_img),
        ]
        self.panel("RESULTADO DEL ESCANEO", rows)
        return total, c_audio, c_video, c_img

    def confirm(self, message, default_no=False):
        hint = "(S/N)" if default_no else "(S/n)"
        resp = input(self._c("warning") + f"\n  {message} {hint}: " + Style.RESET_ALL).strip().lower()
        if default_no:
            return resp in ("s", "si", "y", "yes")
        return resp not in ("n", "no")

    def confirm_exit(self):
        if not self.confirm("¿Deseas salir de la aplicación?", default_no=True):
            return False
        print(self._c("accent") + "\n  ✓ Cerrando de forma segura. ¡Hasta pronto!\n" + Style.RESET_ALL)
        sys.exit(0)

    def status(self, kind, message):
        icons = {
            "info": ("●", "primary"),
            "ok": ("✓", "accent"),
            "warn": ("!", "warning"),
            "error": ("✗", "error"),
            "scan": ("◎", "highlight"),
        }
        icon, color = icons.get(kind, ("•", "info"))
        print(self._c(color) + f"  {icon} " + Style.RESET_ALL + message)

    def progress_start(self, total, hilos):
        print()
        self.status("scan", f"Iniciando limpieza con {hilos} hilos concurrentes...")
        self.rule("─")
        self._progress_total = total
        self._progress_count = 0

    def progress_update(self, actual, total, nombre, tiempo_inicio):
        with self._lock:
            pct = int(actual / total * 100) if total else 0
            filled = int(pct / 4)
            bar = "█" * filled + "░" * (25 - filled)
            elapsed = time.time() - tiempo_inicio
            speed = actual / elapsed if elapsed > 0 else 0
            eta_sec = (total - actual) / speed if speed > 0 else 0
            eta = time.strftime("%M:%S", time.gmtime(eta_sec))
            cpu = f"{psutil.cpu_percent():.0f}%" if PSUTIL_OK else "N/D"
            icono = self._icon_ext(nombre)
            line = (
                f"\r  {self._c('primary')}[{bar}] {pct:>3}%  "
                f"{self._c('accent')}{actual}/{total}  "
                f"{self._c('warning')}ETA {eta}  "
                f"{self._c('muted')}CPU {cpu}  "
                f"{icono} {self._c('info')}{nombre[:26]:<26}"
                + Style.RESET_ALL
            )
            sys.stdout.write(line)
            sys.stdout.flush()

    def log_file(self, nombre, acciones):
        acciones_txt = ", ".join(acciones)
        if len(acciones_txt) > 45:
            acciones_txt = acciones_txt[:42] + "..."
        with self._lock:
            sys.stdout.write("\r" + " " * 110 + "\r")
            print(
                self._c("muted") + "  │ "
                + self._c("info") + f"{nombre[:32]:<32}"
                + self._c("muted") + " │ "
                + self._c("accent") + acciones_txt
                + Style.RESET_ALL
            )

    def log_error(self, nombre):
        with self._lock:
            sys.stdout.write("\r" + " " * 110 + "\r")
            print(self._c("error") + f"  ✗ Error al procesar: {nombre}" + Style.RESET_ALL)

    def report_final(self, total, corregidos, errores, tiempo_total):
        print("\n")
        vel = (total / tiempo_total) * 60 if tiempo_total > 0 else 0
        t_fmt = time.strftime("%H:%M:%S", time.gmtime(tiempo_total))
        pct = int(corregidos / total * 100) if total else 0
        barra = self._mini_bar(corregidos, total, 16)
        lines = [
            self._c("info") + "Archivos escaneados" + Style.RESET_ALL
            + self._c("muted") + " ·· " + Style.RESET_ALL
            + self._c("accent") + str(total),
            self._c("info") + "Archivos corregidos" + Style.RESET_ALL
            + self._c("muted") + " ·· " + Style.RESET_ALL
            + self._c("primary") + barra + " "
            + self._c("highlight") + f"{corregidos} ({pct}%)",
            self._c("info") + "Errores" + Style.RESET_ALL
            + self._c("muted") + " ············· " + Style.RESET_ALL
            + self._c("error" if errores else "accent") + str(errores),
            self._c("info") + "Tiempo total" + Style.RESET_ALL
            + self._c("muted") + " ······· " + Style.RESET_ALL
            + self._c("warning") + t_fmt,
            self._c("info") + "Velocidad media" + Style.RESET_ALL
            + self._c("muted") + " ··· " + Style.RESET_ALL
            + self._c("warning") + f"{vel:.1f} arch/min",
        ]
        estado = (
            self._c("accent") + "✓ Librería optimizada correctamente"
            if errores == 0
            else self._c("warning") + "⚠ Proceso completado con advertencias"
        )
        self.panel("REPORTE FINAL", lines, footer=estado + Style.RESET_ALL)

    def analisis_id3(self, archivos):
        mp3s = [f for f in archivos if f.suffix.lower() in (".mp3", ".wav")]
        if not mp3s:
            return 0, 0

        self.status("scan", f"Analizando metadatos ID3 de {len(mp3s)} archivos (MP3/WAV)...")
        self.rule("─")
        sucios = 0

        for idx, archivo in enumerate(mp3s, 1):
            print(
                self._c("warning") + f"  [{idx:03d}/{len(mp3s)}] "
                + self._c("info") + archivo.name + Style.RESET_ALL
            )
            try:
                if archivo.suffix.lower() == ".wav":
                    wave = WAVE(archivo)
                    if not wave.tags:
                        raise ID3NoHeaderError(archivo)
                    audio = wave.tags
                else:
                    audio = ID3(archivo)
                problemas = 0
                for tag in sorted(audio.keys()):
                    valor = str(audio[tag]).strip()
                    valor_show = valor[:55] + "..." if len(valor) > 55 else valor
                    if any(m in valor.lower() for m in MARCADORES_SUCIOS):
                        print(
                            f"    {self._c('error')}{tag:<12} → {valor_show}"
                            + Style.RESET_ALL
                        )
                        problemas += 1
                    else:
                        print(
                            f"    {self._c('muted')}{tag:<12} → "
                            + self._c('highlight') + valor_show + Style.RESET_ALL
                        )

                if problemas > 0:
                    sucios += 1
                    self.status("error", f"{problemas} tag(s) con datos RemixZ detectados")
                else:
                    self.status("ok", "Limpio")
            except ID3NoHeaderError:
                self.status("warn", "Sin tags ID3")
            except Exception:
                self.status("error", "Error al leer metadatos")
            print()

        limpios = len(mp3s) - sucios
        rows = [
            self._c("info") + "MP3 analizados" + Style.RESET_ALL
            + self._c("muted") + " ····· " + Style.RESET_ALL
            + self._c("accent") + str(len(mp3s)),
            self._c("info") + "Con metadatos sucios" + Style.RESET_ALL
            + self._c("muted") + " · " + Style.RESET_ALL
            + self._c("error" if sucios else "accent") + str(sucios),
            self._c("info") + "Archivos limpios" + Style.RESET_ALL
            + self._c("muted") + " ···· " + Style.RESET_ALL
            + self._c("accent") + str(limpios),
        ]
        footer = (
            self._c("warning") + "Se recomienda limpiar los archivos marcados"
            if sucios
            else self._c("accent") + "Todos los archivos analizados están libres de marcas RemixZ"
        )
        self.panel("ANÁLISIS ID3 FINALIZADO", rows, footer=footer + Style.RESET_ALL)
        return sucios, len(mp3s)


# =====================================================
# LIMPIADOR INTELIGENTE
# =====================================================

def _log_unico(logs, mensaje):
    if mensaje not in logs:
        logs.append(mensaje)


def _log_tag_mp3(tag, logs):
    if tag.startswith("APIC"):
        _log_unico(logs, "Artwork borrado")
    elif tag.startswith("TRCK"):
        _log_unico(logs, "Track borrado")
    elif tag.startswith("TPOS"):
        _log_unico(logs, "Discnumber borrado")
    elif tag.startswith("COMM"):
        _log_unico(logs, "Comment borrado")
    elif not any(tag.startswith(t) for t in ("APIC", "TRCK", "COMM", "TPOS")):
        _log_unico(logs, "Metadatos limpiados")


def _log_tag_mp4(tag, logs):
    if tag == "covr":
        _log_unico(logs, "Artwork borrado")
    elif tag == "trkn":
        _log_unico(logs, "Track borrado")
    elif tag == "disk":
        _log_unico(logs, "Discnumber borrado")
    elif tag == "\xa9cmt":
        _log_unico(logs, "Comment borrado")
    elif tag.startswith("----"):
        _log_unico(logs, "Custom tag borrado")
    elif tag not in ("covr", "trkn", "disk", "\xa9cmt"):
        _log_unico(logs, "Metadatos limpiados")


def limpiar_texto(texto, patrones):
    if not texto:
        return texto
    for patron in patrones:
        texto = re.sub(patron, "", texto, flags=re.IGNORECASE)

    texto = re.sub(r"\[\s*\]", "", texto)
    texto = re.sub(r"\(\s*\)", "", texto)
    texto = re.sub(r"\s+", " ", texto)
    texto = re.sub(r"\s+\.", ".", texto)
    return texto.strip()


def limpiar_nombre(ruta, patrones):
    nuevo = limpiar_texto(ruta.stem, patrones).strip()
    if not nuevo:
        nuevo = "Sin nombre"
    destino = ruta.with_name(nuevo + ruta.suffix)
    if destino == ruta:
        return ruta, False
    contador = 1
    while destino.exists():
        destino = ruta.with_name(f"{nuevo}_{contador}{ruta.suffix}")
        contador += 1
    try:
        ruta.rename(destino)
        return destino, True
    except Exception as e:
        raise e


def limpiar_mp3(ruta, patrones):
    logs = []
    try:
        audio = ID3(ruta)
    except ID3NoHeaderError:
        return False, logs

    eliminar = [
        "APIC", "TALB", "TPE1", "TPE2", "COMM", "TCOM", "TCON",
        "TCOP", "TRCK", "TPOS", "TDRC", "TYER", "TXXX"
    ]
    cambio = False

    for tag in list(audio.keys()):
        if any(tag.startswith(x) for x in eliminar):
            del audio[tag]
            cambio = True
            _log_tag_mp3(tag, logs)

    if "TIT2" in audio:
        original = str(audio["TIT2"])
        nuevo = limpiar_texto(original, patrones)
        if original != nuevo:
            audio["TIT2"].text = [nuevo]
            cambio = True
            logs.append("Título corregido")

    if cambio:
        audio.save()
    return cambio, logs


def limpiar_wav(ruta, patrones):
    logs = []
    try:
        audio = WAVE(ruta)
    except Exception:
        return False, logs
    if not audio.tags:
        return False, logs

    tags = audio.tags
    eliminar = [
        "APIC", "TALB", "TPE1", "TPE2", "COMM", "TCOM", "TCON",
        "TCOP", "TRCK", "TPOS", "TDRC", "TYER", "TXXX"
    ]
    cambio = False

    for tag in list(tags.keys()):
        if any(str(tag).startswith(x) for x in eliminar):
            del tags[tag]
            cambio = True
            _log_tag_mp3(str(tag), logs)

    if "TIT2" in tags:
        original = str(tags["TIT2"])
        nuevo = limpiar_texto(original, patrones)
        if original != nuevo:
            tags["TIT2"].text = [nuevo]
            cambio = True
            logs.append("Título corregido")

    if cambio:
        audio.save()
    return cambio, logs


def limpiar_mp4(ruta, patrones):
    logs = []
    try:
        audio = MP4(ruta)
    except MP4StreamInfoError:
        return False, logs

    borrar = [
        "\xa9alb", "\xa9ART", "aART", "\xa9cmt", "\xa9wrt", "\xa9gen",
        "trkn", "disk", "\xa9day", "covr"
    ]
    cambio = False

    for tag in list(audio.keys()):
        if tag in borrar or tag.startswith("----"):
            del audio[tag]
            cambio = True
            _log_tag_mp4(tag, logs)

    if "\xa9nam" in audio:
        original = audio["\xa9nam"][0]
        nuevo = limpiar_texto(original, patrones)
        if original != nuevo:
            audio["\xa9nam"] = [nuevo]
            cambio = True
            logs.append("Título corregido")

    if cambio:
        audio.save()
    return cambio, logs


# =====================================================
# NÚCLEO DE PROCESAMIENTO
# =====================================================

def recolectar_archivos(rutas):
    archivos = []
    for ruta in rutas:
        carpeta = Path(ruta.strip('"'))
        if not carpeta.exists():
            continue
        if carpeta.is_file() and carpeta.suffix.lower() in EXTENSIONES:
            archivos.append(carpeta)
        else:
            archivos.extend(
                x for x in carpeta.rglob("*")
                if x.suffix.lower() in EXTENSIONES
            )
    return archivos


def ejecutar_limpieza(archivos, config, ui):
    total = len(archivos)
    errores = 0
    corregidos = 0
    tiempo_inicio = time.time()
    lock = threading.Lock()
    progreso_actual = 0

    ui.progress_start(total, config["hilos"])

    def procesar_archivo(multimedia):
        nonlocal progreso_actual, errores, corregidos
        acciones_realizadas = []
        try:
            archivo_limpio, renombrado = limpiar_nombre(multimedia, config["patrones"])
            if renombrado:
                acciones_realizadas.append("Nombre corregido")

            ext = archivo_limpio.suffix.lower()
            if ext == ".mp3":
                modificado, detalles = limpiar_mp3(archivo_limpio, config["patrones"])
                if modificado:
                    acciones_realizadas.extend(detalles)
            elif ext == ".wav":
                modificado, detalles = limpiar_wav(archivo_limpio, config["patrones"])
                if modificado:
                    acciones_realizadas.extend(detalles)
            elif ext in (".mp4", ".m4a"):
                modificado, detalles = limpiar_mp4(archivo_limpio, config["patrones"])
                if modificado:
                    acciones_realizadas.extend(detalles)

            with lock:
                progreso_actual += 1
                if acciones_realizadas:
                    corregidos += 1
                    escribir_log(archivo_limpio.name, acciones_realizadas, "procesados")
                    ui.log_file(archivo_limpio.name, acciones_realizadas)
                ui.progress_update(
                    progreso_actual, total, archivo_limpio.name, tiempo_inicio
                )

        except Exception:
            with lock:
                errores += 1
                progreso_actual += 1
                escribir_log(multimedia.name, [traceback.format_exc()], "errores")
                ui.log_error(multimedia.name)
                ui.progress_update(
                    progreso_actual, total, multimedia.name, tiempo_inicio
                )

    with ThreadPoolExecutor(max_workers=config["hilos"]) as executor:
        futures = [executor.submit(procesar_archivo, f) for f in archivos]
        for _ in as_completed(futures):
            pass

    tiempo_total = time.time() - tiempo_inicio
    ui.report_final(total, corregidos, errores, tiempo_total)
    return total, corregidos, errores


def flujo_analisis(rutas, config, ui):
    ui.status("scan", "Escaneando archivos MP3...")
    archivos = recolectar_archivos(rutas)

    if not archivos:
        ui.status("error", "No se encontraron archivos multimedia compatibles.")
        input(ui._c("muted") + "\n  Presiona ENTER para continuar..." + Style.RESET_ALL)
        return

    ui.scan_summary(archivos)
    sucios, total_mp3 = ui.analisis_id3(archivos)

    if sucios > 0 and ui.confirm("¿Deseas limpiar los archivos detectados ahora?"):
        ejecutar_limpieza(archivos, config, ui)

    input(ui._c("muted") + "\n  Presiona ENTER para volver al menú..." + Style.RESET_ALL)


def flujo_limpieza(rutas, config, ui):
    ui.status("scan", "Escaneando estructura de directorios...")
    archivos = recolectar_archivos(rutas)

    if not archivos:
        ui.status("error", "No se encontraron archivos multimedia compatibles.")
        input(ui._c("muted") + "\n  Presiona ENTER para continuar..." + Style.RESET_ALL)
        return

    ui.scan_summary(archivos)

    con_id3 = [f for f in archivos if f.suffix.lower() in (".mp3", ".wav")]
    if con_id3 and config.get("analizar_antes_limpiar", True):
        sucios, _ = ui.analisis_id3(archivos)
        if sucios == 0 and not ui.confirm("No hay metadatos sucios. ¿Limpiar de todos modos?"):
            ui.status("warn", "Operación cancelada.")
            time.sleep(0.8)
            return
        elif sucios > 0 and not ui.confirm("¿Comenzar la limpieza profunda ahora?"):
            ui.status("warn", "Operación cancelada.")
            time.sleep(0.8)
            return
    elif not ui.confirm("¿Comenzar la limpieza profunda ahora?"):
        ui.status("warn", "Operación cancelada.")
        time.sleep(0.8)
        return

    ejecutar_limpieza(archivos, config, ui)
    input(ui._c("muted") + "\n  Presiona ENTER para volver al menú..." + Style.RESET_ALL)


# =====================================================
# MODO GUI (integracion PowerShell script.ps1)
# =====================================================

class GuiOutputUI:
    """Salida JSON linea a linea para consumo desde script.ps1."""

    def __init__(self):
        self._lock = threading.Lock()

    def _emit(self, payload):
        print(json.dumps(payload, ensure_ascii=False), flush=True)

    def progress_start(self, total, hilos):
        self._emit({"type": "start", "total": total, "hilos": hilos})

    def progress_update(self, actual, total, nombre, tiempo_inicio):
        self._emit({
            "type": "progress",
            "current": actual,
            "total": total,
            "file": nombre,
        })

    def log_file(self, nombre, acciones):
        self._emit({
            "type": "file",
            "file": nombre,
            "actions": acciones,
            "status": "ok",
        })

    def log_error(self, nombre):
        self._emit({"type": "file", "file": nombre, "status": "error"})

    def report_final(self, total, corregidos, errores, tiempo_total):
        self._emit({
            "type": "summary",
            "total": total,
            "fixed": corregidos,
            "errors": errores,
            "seconds": round(tiempo_total, 2),
        })


def _analizar_archivo_id3(archivo):
    problemas = []
    limpio = True
    try:
        if archivo.suffix.lower() == ".wav":
            wave = WAVE(archivo)
            if not wave.tags:
                raise ID3NoHeaderError(archivo)
            audio = wave.tags
        else:
            audio = ID3(archivo)
        for tag in sorted(audio.keys()):
            valor = str(audio[tag]).strip()
            sucio = any(m in valor.lower() for m in MARCADORES_SUCIOS)
            if sucio:
                limpio = False
                problemas.append({"tag": str(tag), "value": valor[:120], "dirty": True})
            else:
                problemas.append({"tag": str(tag), "value": valor[:120], "dirty": False})
    except ID3NoHeaderError:
        return {"file": archivo.name, "status": "no_tags", "tags": [], "dirty": False}
    except Exception as exc:
        return {"file": archivo.name, "status": "error", "message": str(exc), "dirty": False}
    return {
        "file": archivo.name,
        "status": "dirty" if not limpio else "clean",
        "tags": problemas,
        "dirty": not limpio,
    }


def modo_gui(accion, rutas):
    config = cargar_config()
    archivos = recolectar_archivos(rutas)

    c_audio = sum(1 for f in archivos if f.suffix.lower() in EXT_AUDIO)
    c_video = sum(1 for f in archivos if f.suffix.lower() in EXT_VIDEO)
    c_img = sum(1 for f in archivos if f.suffix.lower() in EXT_IMG)

    print(json.dumps({
        "type": "scan",
        "total": len(archivos),
        "audio": c_audio,
        "video": c_video,
        "image": c_img,
    }, ensure_ascii=False), flush=True)

    if not archivos:
        print(json.dumps({"type": "error", "message": "No se encontraron archivos compatibles."}, ensure_ascii=False), flush=True)
        return 1

    if accion == "--gui-analyze":
        mp3s = [f for f in archivos if f.suffix.lower() in (".mp3", ".wav")]
        sucios = 0
        for archivo in mp3s:
            resultado = _analizar_archivo_id3(archivo)
            if resultado.get("dirty"):
                sucios += 1
            print(json.dumps({"type": "analyze", **resultado}, ensure_ascii=False), flush=True)
        print(json.dumps({
            "type": "analyze_summary",
            "analyzed": len(mp3s),
            "dirty": sucios,
            "clean": len(mp3s) - sucios,
        }, ensure_ascii=False), flush=True)
        return 0

    if accion == "--gui-clean":
        ui = GuiOutputUI()
        ejecutar_limpieza(archivos, config, ui)
        return 0

    print(json.dumps({"type": "error", "message": f"Accion GUI desconocida: {accion}"}, ensure_ascii=False), flush=True)
    return 1


# =====================================================
# MAIN
# =====================================================

def main():
    config = cargar_config()
    ui = ConsoleUI(config)
    ui.set_title()
    ui.splash()

    argv_paths = [p for p in sys.argv[1:] if p.strip()]
    if argv_paths:
        ui.clear()
        ui.header()
        ui.status("ok", "Drag & Drop detectado — iniciando escaneo automático")
        flujo_limpieza(argv_paths, config, ui)
        if config.get("confirmar_salida", True):
            ui.confirm_exit()
        return

    while True:
        ui.clear()
        ui.header()
        opcion = ui.menu()

        if opcion == "0":
            if config.get("confirmar_salida", True):
                ui.confirm_exit()
            sys.exit(0)

        elif opcion == "1":
            ruta = ui.prompt_path()
            if ruta:
                flujo_limpieza([ruta], config, ui)

        elif opcion == "2":
            ruta = ui.prompt_path()
            if ruta:
                flujo_analisis([ruta], config, ui)

        elif opcion == "3":
            ui.status("info", "Arrastra carpetas o archivos sobre el .exe del programa.")
            ui.status("info", "También puedes ejecutar: RemixZ_Cleaner.exe \"C:\\ruta\\carpeta\"")
            input(ui._c("muted") + "\n  Presiona ENTER para volver..." + Style.RESET_ALL)

        elif opcion == "4":
            ui.clear()
            ui.header()
            ui.info_sistema()

        elif opcion == "5":
            ui.menu_ajustes()

        else:
            ui.status("warn", "Opción no válida. Intenta de nuevo.")
            time.sleep(0.6)


if __name__ == "__main__":
    try:
        if len(sys.argv) >= 3 and sys.argv[1] in ("--gui-clean", "--gui-analyze"):
            sys.exit(modo_gui(sys.argv[1], sys.argv[2:]))
        main()
    except KeyboardInterrupt:
        print(Fore.RED + "\n  [!] Proceso interrumpido.\n" + Style.RESET_ALL)
        sys.exit(0)