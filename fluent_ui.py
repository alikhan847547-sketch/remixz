"""Componentes UI estilo Fluent Design (Windows 11) con efectos y transiciones."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk


# Paleta profesional (dark SaaS / dashboard)
FLUENT = {
    "bg": "#0b0f14",
    "surface": "#111821",
    "card": "#151c27",
    "card_hover": "#1c2533",
    "input": "#1a2330",
    "hover": "#243044",
    "border": "#2a3545",
    "border_hot": "#3d8bfd",
    "fg": "#e8eef7",
    "muted": "#8b9bb0",
    "accent": "#2f6fed",
    "accent_light": "#6aa8ff",
    "accent_hover": "#3d7ff5",
    "success": "#3ecf8e",
    "warning": "#f5c542",
    "error": "#ff6b7a",
    "subtle": "#1a2330",
    "btn": "#243044",
    "blue": "#2f6fed",
    "green": "#3ecf8e",
    "cyan": "#5ec8ff",
    "orange": "#ff8a3d",
    "header": "#0e141c",
    "glow": "#4d8dff",
    "panel": "#121a24",
    "text_dim": "#6b7c90",
    "divider": "#1e2836",
}


# ---------------------------------------------------------------------------
# Animación / color helpers
# ---------------------------------------------------------------------------

def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    c = color.lstrip("#")
    if len(c) != 6:
        return 32, 32, 32
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{max(0, min(255, r)):02x}{max(0, min(255, g)):02x}{max(0, min(255, b)):02x}"


def lerp_color(c1: str, c2: str, t: float) -> str:
    t = max(0.0, min(1.0, t))
    r1, g1, b1 = _hex_to_rgb(c1)
    r2, g2, b2 = _hex_to_rgb(c2)
    return _rgb_to_hex(
        int(r1 + (r2 - r1) * t),
        int(g1 + (g2 - g1) * t),
        int(b1 + (b2 - b1) * t),
    )


def ease_out_cubic(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def ease_in_out(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 3 * t * t - 2 * t * t * t


class Animator:
    """Gestor ligero de animaciones con widget.after (cancelable)."""

    def __init__(self, root: tk.Misc):
        self.root = root
        self._jobs: dict[str, str] = {}

    def cancel(self, key: str) -> None:
        job = self._jobs.pop(key, None)
        if job:
            try:
                self.root.after_cancel(job)
            except Exception:
                pass

    def cancel_all(self) -> None:
        for key in list(self._jobs):
            self.cancel(key)

    def run(
        self,
        key: str,
        frames: int,
        step_ms: int,
        on_frame,
        on_done=None,
        *,
        easing=ease_out_cubic,
    ) -> None:
        self.cancel(key)
        if frames < 1:
            frames = 1

        def tick(i: int = 0):
            t = easing(i / max(frames - 1, 1)) if frames > 1 else 1.0
            try:
                on_frame(t, i)
            except tk.TclError:
                self._jobs.pop(key, None)
                return
            if i >= frames - 1:
                self._jobs.pop(key, None)
                if on_done:
                    try:
                        on_done()
                    except Exception:
                        pass
                return
            self._jobs[key] = self.root.after(step_ms, lambda: tick(i + 1))

        tick(0)

    def color_to(
        self,
        key: str,
        widget: tk.Misc,
        attr: str,
        start: str,
        end: str,
        *,
        frames: int = 8,
        step_ms: int = 16,
    ) -> None:
        def on_frame(t, _i):
            widget.configure(**{attr: lerp_color(start, end, t)})

        self.run(key, frames, step_ms, on_frame)


def apply_fluent_style(root: tk.Misc) -> ttk.Style:
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    c = FLUENT
    style.configure("TNotebook", background=c["bg"], borderwidth=0, tabmargins=[6, 10, 6, 0])
    style.configure(
        "TNotebook.Tab",
        background=c["card"],
        foreground=c["muted"],
        padding=[22, 12],
        font=("Segoe UI Semibold", 10),
        borderwidth=0,
        focuscolor=c["bg"],
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", c["surface"]), ("active", c["hover"])],
        foreground=[("selected", c["accent_light"]), ("active", c["fg"])],
    )
    style.configure(
        "Fluent.Horizontal.TProgressbar",
        troughcolor=c["input"],
        background=c["accent"],
        bordercolor=c["border"],
        lightcolor=c["accent_light"],
        darkcolor=c["accent"],
        thickness=10,
    )
    style.configure(
        "TProgressbar",
        troughcolor=c["input"],
        background=c["accent"],
        bordercolor=c["border"],
        thickness=10,
    )
    return style


class RoundedGradientProgress(tk.Canvas):
    """
    Barra de progreso redondeada (pill) con relleno en degradado.
    API compatible con ttk: configure(value=), start()/stop(), ['value'].
    """

    def __init__(
        self,
        parent,
        *,
        height: int = 12,
        maximum: float = 100,
        mode: str = "determinate",
        colors: dict | None = None,
        gradient: tuple[str, str] | None = None,
        trough: str | None = None,
        bg: str | None = None,
        **pack_ignore,
    ):
        c = {**FLUENT, **(colors or {})}
        self._c = c
        self._height = max(8, int(height))
        self._maximum = max(1.0, float(maximum))
        self._value = 0.0
        self._mode = mode  # determinate | indeterminate
        self._grad = gradient or (c["accent"], c["cyan"])
        self._trough = trough or c["input"]
        self._track_border = c.get("border", "#2a3545")
        self._indeterminate = False
        self._ind_job = None
        self._ind_pos = 0.0
        self._ind_dir = 1.0
        canvas_bg = bg or c.get("card") or c["bg"]
        super().__init__(
            parent,
            height=self._height + 4,
            bg=canvas_bg,
            highlightthickness=0,
            bd=0,
        )
        self.bind("<Configure>", self._on_configure)
        self.after_idle(self._redraw)

    # ── API ttk-like ──────────────────────────────────────────────────────
    def configure(self, cnf=None, **kwargs):  # type: ignore[override]
        if cnf and isinstance(cnf, dict):
            kwargs = {**cnf, **kwargs}
        if "value" in kwargs:
            self.set(kwargs.pop("value"))
        if "maximum" in kwargs:
            self._maximum = max(1.0, float(kwargs.pop("maximum")))
            self._redraw()
        if "mode" in kwargs:
            self._mode = str(kwargs.pop("mode"))
        if "bg" in kwargs:
            super().configure(bg=kwargs.pop("bg"))
        if kwargs:
            try:
                super().configure(**kwargs)
            except tk.TclError:
                pass
        return None

    config = configure

    def __setitem__(self, key, value):
        if key in ("value", "maximum", "mode"):
            self.configure(**{key: value})
        else:
            super().__setitem__(key, value)

    def __getitem__(self, key):
        if key == "value":
            return self._value
        if key == "maximum":
            return self._maximum
        if key == "mode":
            return self._mode
        return super().__getitem__(key)

    def set(self, value: float) -> None:
        self._value = max(0.0, min(self._maximum, float(value)))
        if not self._indeterminate:
            self._redraw()

    def get(self) -> float:
        return self._value

    def start(self, interval: int = 18) -> None:
        self._indeterminate = True
        self._mode = "indeterminate"
        self._ind_pos = 0.0
        self._ind_dir = 1.0
        self._tick_indeterminate(max(12, int(interval)))

    def stop(self) -> None:
        self._indeterminate = False
        if self._ind_job is not None:
            try:
                self.after_cancel(self._ind_job)
            except Exception:
                pass
            self._ind_job = None
        self._redraw()

    # ── Dibujo ────────────────────────────────────────────────────────────
    def _on_configure(self, _event=None):
        self._redraw()

    def _tick_indeterminate(self, interval: int) -> None:
        if not self._indeterminate:
            return
        self._ind_pos += 0.018 * self._ind_dir
        if self._ind_pos >= 1.0:
            self._ind_pos = 1.0
            self._ind_dir = -1.0
        elif self._ind_pos <= 0.0:
            self._ind_pos = 0.0
            self._ind_dir = 1.0
        self._redraw()
        try:
            self._ind_job = self.after(interval, lambda: self._tick_indeterminate(interval))
        except tk.TclError:
            self._ind_job = None

    def _rounded_pill(self, x1: float, y1: float, x2: float, y2: float, fill: str, tag: str):
        """Píldora sólida (óvalos + rectángulo)."""
        if x2 - x1 < 1:
            return
        h = y2 - y1
        r = h / 2.0
        # Si es muy estrecha, solo un círculo
        if x2 - x1 <= h:
            cx = (x1 + x2) / 2
            self.create_oval(cx - r, y1, cx + r, y2, fill=fill, outline=fill, tags=tag)
            return
        self.create_oval(x1, y1, x1 + h, y2, fill=fill, outline=fill, tags=tag)
        self.create_oval(x2 - h, y1, x2, y2, fill=fill, outline=fill, tags=tag)
        self.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill, outline=fill, tags=tag)

    def _gradient_pill(self, x1: float, y1: float, x2: float, y2: float, c0: str, c1: str, tag: str):
        """Relleno en pill con degradado horizontal (por franjas)."""
        w = x2 - x1
        if w < 1:
            return
        h = y2 - y1
        r = h / 2.0
        steps = max(int(w), 1)
        # franjas verticales de 1px
        for i in range(steps):
            t = i / max(steps - 1, 1)
            col = lerp_color(c0, c1, t)
            x = x1 + i
            # recorte a forma pill: distancia al segmento central
            # centro vertical del pill
            # para cada x, altura visible del pill
            # forma: círculo izq [x1, x1+h], rect [x1+r, x2-r], círculo der
            local = x - x1
            if local < r:
                # semi-círculo izquierdo: half-chord
                dx = r - local
                half = (r * r - dx * dx) ** 0.5 if dx * dx <= r * r else 0
                cy = (y1 + y2) / 2
                ya, yb = cy - half, cy + half
            elif local > w - r:
                dx = local - (w - r)
                half = (r * r - dx * dx) ** 0.5 if dx * dx <= r * r else 0
                cy = (y1 + y2) / 2
                ya, yb = cy - half, cy + half
            else:
                ya, yb = y1, y2
            if yb - ya >= 0.5:
                self.create_line(x, ya, x, yb, fill=col, width=1, tags=tag)

    def _redraw(self) -> None:
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        self.delete("all")
        w = max(self.winfo_width(), 40)
        h_total = self.winfo_height() or (self._height + 4)
        pad_y = max(1, (h_total - self._height) // 2)
        pad_x = 2
        x1, y1 = pad_x, pad_y
        x2, y2 = w - pad_x, pad_y + self._height

        # Track (fondo pill)
        self._rounded_pill(x1, y1, x2, y2, self._trough, "trough")
        # borde sutil exterior
        # (sin outline nativo; se ve limpio sobre cards)

        g0, g1 = self._grad
        # highlight secundario al final del degradado (cyan → acento claro)
        g_mid = lerp_color(g0, g1, 0.55)

        if self._indeterminate:
            # bloque móvil ~28% del ancho
            track_w = x2 - x1
            block = max(track_w * 0.28, self._height * 2)
            max_off = max(track_w - block, 0)
            off = max_off * self._ind_pos
            bx1 = x1 + off
            bx2 = bx1 + block
            self._gradient_pill(bx1, y1, bx2, y2, g0, g1, "fill")
        else:
            pct = self._value / self._maximum if self._maximum else 0
            pct = max(0.0, min(1.0, pct))
            fill_w = (x2 - x1) * pct
            if fill_w >= 1:
                # si es muy pequeña, pill sólido con color medio
                if fill_w < self._height:
                    self._rounded_pill(x1, y1, x1 + fill_w, y2, g_mid, "fill")
                else:
                    self._gradient_pill(x1, y1, x1 + fill_w, y2, g0, g1, "fill")
                    # brillo superior sutil (línea semi-clara)
                    try:
                        shine = lerp_color(g1, "#ffffff", 0.35)
                        mid_y = y1 + 1
                        self.create_line(
                            x1 + self._height / 2,
                            mid_y,
                            x1 + fill_w - self._height / 2,
                            mid_y,
                            fill=shine,
                            width=1,
                            tags="shine",
                        )
                    except Exception:
                        pass


class FluentUI:
    """Helpers para construir paneles estilo Fluent con micro-interacciones."""

    def __init__(self, colors: dict | None = None, root: tk.Misc | None = None):
        self.c = {**FLUENT, **(colors or {})}
        self.root = root
        self.anim = Animator(root) if root is not None else None

    def set_root(self, root: tk.Misc) -> None:
        self.root = root
        self.anim = Animator(root)

    def app_header(
        self,
        parent,
        title: str,
        version: str = "",
        subtitle: str = "",
        logo_image: tk.PhotoImage | None = None,
    ) -> tk.Frame:
        """Barra superior profesional con marca X y estado."""
        bar = tk.Frame(parent, bg=self.c["header"], height=70)
        bar.pack(fill="x")
        bar.pack_propagate(False)

        accent = tk.Frame(bar, bg=self.c["accent"], width=3)
        accent.pack(side="left", fill="y")
        self._pulse_accent(accent)

        # Logo X (imagen) o badge fallback
        badge_wrap = tk.Frame(bar, bg=self.c["header"])
        badge_wrap.pack(side="left", padx=(14, 0), pady=10)
        if logo_image is not None:
            logo_lbl = tk.Label(
                badge_wrap,
                image=logo_image,
                bg=self.c["header"],
                bd=0,
                highlightthickness=0,
            )
            logo_lbl.image = logo_image  # evitar GC
            logo_lbl.pack(side="left")
        else:
            logo = tk.Frame(
                badge_wrap,
                bg=self.c["accent"],
                width=36,
                height=36,
                highlightthickness=0,
            )
            logo.pack(side="left")
            logo.pack_propagate(False)
            tk.Label(
                logo,
                text="X",
                font=("Segoe UI Black", 16),
                fg="#ffffff",
                bg=self.c["accent"],
            ).place(relx=0.5, rely=0.5, anchor="center")

        left = tk.Frame(bar, bg=self.c["header"])
        left.pack(side="left", fill="y", padx=(12, 0), pady=12)
        brand_row = tk.Frame(left, bg=self.c["header"])
        brand_row.pack(anchor="w")
        tk.Label(
            brand_row,
            text="REMIXZ",
            font=("Segoe UI Black", 13),
            fg=self.c["fg"],
            bg=self.c["header"],
        ).pack(side="left")
        tk.Label(
            brand_row,
            text="  ·  ",
            font=("Segoe UI", 11),
            fg=self.c["text_dim"],
            bg=self.c["header"],
        ).pack(side="left")
        tk.Label(
            brand_row,
            text=title,
            font=("Segoe UI Semibold", 12),
            fg=self.c["accent_light"],
            bg=self.c["header"],
        ).pack(side="left")
        if subtitle:
            tk.Label(
                left,
                text=subtitle,
                font=("Segoe UI", 8),
                fg=self.c["muted"],
                bg=self.c["header"],
            ).pack(anchor="w", pady=(2, 0))

        right = tk.Frame(bar, bg=self.c["header"])
        right.pack(side="right", fill="y", padx=16, pady=14)
        if version:
            ver_chip = tk.Frame(
                right,
                bg=self.c["input"],
                highlightthickness=1,
                highlightbackground=self.c["border"],
            )
            ver_chip.pack(anchor="e")
            tk.Label(
                ver_chip,
                text=version,
                font=("Segoe UI Semibold", 8),
                fg=self.c["accent_light"],
                bg=self.c["input"],
                padx=10,
                pady=3,
            ).pack()

        line = tk.Frame(parent, bg=self.c["divider"], height=1)
        line.pack(fill="x")
        glow = tk.Frame(parent, bg=self.c["accent"], height=1)
        glow.pack(fill="x")
        self._shimmer_line(glow)
        return bar

    def _pulse_accent(self, widget: tk.Frame) -> None:
        if not self.anim:
            return
        colors = [self.c["accent"], self.c["accent_light"], self.c["glow"], self.c["accent"]]
        state = {"i": 0, "alive": True}

        def loop():
            if not state["alive"]:
                return
            try:
                if not widget.winfo_exists():
                    state["alive"] = False
                    return
            except tk.TclError:
                state["alive"] = False
                return
            i = state["i"]
            a = colors[i % len(colors)]
            b = colors[(i + 1) % len(colors)]
            state["i"] = i + 1

            def on_frame(t, _j):
                try:
                    if widget.winfo_exists():
                        widget.configure(bg=lerp_color(a, b, t))
                except tk.TclError:
                    state["alive"] = False

            def on_done():
                if state["alive"] and self.anim:
                    try:
                        self.anim.root.after(40, loop)
                    except tk.TclError:
                        state["alive"] = False

            self.anim.run(f"pulse-{id(widget)}", 18, 40, on_frame, on_done, easing=ease_in_out)

        loop()

    def _shimmer_line(self, line: tk.Frame) -> None:
        if not self.anim:
            return
        c0, c1 = self.c["border"], self.c["accent"]
        state = {"up": True, "alive": True}

        def loop():
            if not state["alive"]:
                return
            try:
                if not line.winfo_exists():
                    state["alive"] = False
                    return
            except tk.TclError:
                state["alive"] = False
                return
            start, end = (c0, c1) if state["up"] else (c1, c0)
            state["up"] = not state["up"]

            def on_frame(t, _i):
                try:
                    if line.winfo_exists():
                        line.configure(bg=lerp_color(start, end, t))
                except tk.TclError:
                    state["alive"] = False

            def on_done():
                if state["alive"] and self.anim:
                    try:
                        self.anim.root.after(80, loop)
                    except tk.TclError:
                        state["alive"] = False

            self.anim.run(f"shimmer-{id(line)}", 24, 35, on_frame, on_done, easing=ease_in_out)

        loop()

    def header(self, parent, title: str, subtitle: str = "") -> tk.Frame:
        wrap = tk.Frame(parent, bg=self.c["bg"])
        title_lbl = tk.Label(
            wrap,
            text=title,
            font=("Segoe UI Semibold", 20),
            fg=self.c["fg"],
            bg=self.c["bg"],
            anchor="w",
        )
        title_lbl.pack(fill="x")
        if subtitle:
            tk.Label(
                wrap,
                text=subtitle,
                font=("Segoe UI", 10),
                fg=self.c["muted"],
                bg=self.c["bg"],
                anchor="w",
                wraplength=780,
                justify="left",
            ).pack(fill="x", pady=(4, 0))
        # underline accent
        und = tk.Frame(wrap, bg=self.c["accent"], height=2, width=48)
        und.pack(anchor="w", pady=(8, 0))
        if self.anim:
            self._grow_bar(und, 48, 160)
        return wrap

    def _grow_bar(self, bar: tk.Frame, start_w: int, end_w: int) -> None:
        def on_frame(t, _i):
            w = int(start_w + (end_w - start_w) * t)
            try:
                bar.configure(width=max(1, w))
            except tk.TclError:
                pass

        self.anim.run(f"grow-{id(bar)}", 14, 18, on_frame)

    def card(self, parent, title: str = "", pad: int = 14) -> tuple[tk.Frame, tk.Frame]:
        shell = tk.Frame(parent, bg=self.c["bg"])
        shell.pack(fill="x")
        card = tk.Frame(
            shell,
            bg=self.c["card"],
            highlightthickness=1,
            highlightbackground=self.c["border"],
            highlightcolor=self.c["border_hot"],
        )
        card.pack(fill="x", padx=2, pady=6)
        body = tk.Frame(card, bg=self.c["card"])
        body.pack(fill="both", expand=True, padx=pad, pady=pad)
        if title:
            head = tk.Frame(body, bg=self.c["card"])
            head.pack(fill="x", pady=(0, 10))
            tk.Frame(head, bg=self.c["accent"], width=3, height=14).pack(side="left", padx=(0, 8))
            tk.Label(
                head,
                text=title,
                font=("Segoe UI Semibold", 11),
                fg=self.c["accent_light"],
                bg=self.c["card"],
                anchor="w",
            ).pack(side="left", fill="x")

        self._bind_card_hover(card, body)
        return shell, body

    def _bind_card_hover(self, card: tk.Frame, body: tk.Frame) -> None:
        normal_bg = self.c["card"]
        hot_bg = self.c["card_hover"]
        normal_border = self.c["border"]
        hot_border = self.c["border_hot"]

        def set_tree_bg(widget, color):
            try:
                if isinstance(widget, (tk.Frame, tk.Label)):
                    # no tocar labels de color especial
                    if isinstance(widget, tk.Label):
                        return
                    widget.configure(bg=color)
            except tk.TclError:
                return
            for child in widget.winfo_children():
                if isinstance(child, tk.Frame):
                    set_tree_bg(child, color)

        def on_enter(_e=None):
            try:
                card.configure(highlightbackground=hot_border, bg=hot_bg)
                body.configure(bg=hot_bg)
            except tk.TclError:
                pass

        def on_leave(_e=None):
            try:
                card.configure(highlightbackground=normal_border, bg=normal_bg)
                body.configure(bg=normal_bg)
            except tk.TclError:
                pass

        card.bind("<Enter>", on_enter)
        card.bind("<Leave>", on_leave)
        body.bind("<Enter>", on_enter)
        body.bind("<Leave>", on_leave)

    def badge(self, parent, label: str, value: str = "—", color: str | None = None) -> tk.Label:
        chip = tk.Frame(
            parent,
            bg=self.c["input"],
            highlightthickness=1,
            highlightbackground=self.c["border"],
        )
        chip.pack(side="left", padx=(0, 8), pady=2)
        tk.Label(
            chip,
            text=label,
            font=("Segoe UI", 8),
            fg=self.c["muted"],
            bg=self.c["input"],
        ).pack(padx=10, pady=(4, 0))
        val = tk.Label(
            chip,
            text=value,
            font=("Segoe UI Semibold", 11),
            fg=color or self.c["fg"],
            bg=self.c["input"],
        )
        val.pack(padx=10, pady=(0, 6))

        def on_enter(_e):
            chip.configure(highlightbackground=self.c["accent"])

        def on_leave(_e):
            chip.configure(highlightbackground=self.c["border"])

        chip.bind("<Enter>", on_enter)
        chip.bind("<Leave>", on_leave)
        return val

    def entry(self, parent, **kwargs) -> tk.Entry:
        e = tk.Entry(
            parent,
            font=("Segoe UI", 10),
            bg=self.c["input"],
            fg=self.c["fg"],
            insertbackground=self.c["fg"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=self.c["border"],
            highlightcolor=self.c["accent"],
            **kwargs,
        )

        def on_focus_in(_e):
            e.configure(highlightbackground=self.c["accent"], highlightcolor=self.c["accent_light"])

        def on_focus_out(_e):
            e.configure(highlightbackground=self.c["border"], highlightcolor=self.c["accent"])

        e.bind("<FocusIn>", on_focus_in)
        e.bind("<FocusOut>", on_focus_out)
        return e

    def _hover(self, widget: tk.Button, normal: str, hover: str) -> None:
        def on_enter(_e):
            if self.anim:
                self.anim.color_to(
                    f"btn-in-{id(widget)}", widget, "bg", widget.cget("bg"), hover, frames=6, step_ms=14,
                )
            else:
                widget.configure(bg=hover)

        def on_leave(_e):
            if self.anim:
                self.anim.color_to(
                    f"btn-out-{id(widget)}", widget, "bg", widget.cget("bg"), normal, frames=6, step_ms=14,
                )
            else:
                widget.configure(bg=normal)

        def on_press(_e):
            widget.configure(bg=lerp_color(hover, "#000000", 0.18))

        def on_release(_e):
            widget.configure(bg=hover)

        widget.bind("<Enter>", on_enter)
        widget.bind("<Leave>", on_leave)
        widget.bind("<ButtonPress-1>", on_press)
        widget.bind("<ButtonRelease-1>", on_release)

    def button(
        self,
        parent,
        text: str,
        command,
        *,
        kind: str = "subtle",
        width: int | None = None,
    ) -> tk.Button:
        c = self.c
        styles = {
            "accent": (c["accent"], c["accent_hover"], "#ffffff"),
            "success": (c["green"], "#35b87d", "#04140c"),
            "danger": ("#d63b4a", "#b82f3c", "#ffffff"),
            "subtle": (c["subtle"], c["hover"], c["fg"]),
            "standard": (c["btn"], c["hover"], c["fg"]),
            "ghost": (c["card"], c["card_hover"], c["fg"]),
        }
        bg, hbg, fg = styles.get(kind, styles["subtle"])
        btn = tk.Button(
            parent,
            text=text,
            font=("Segoe UI Semibold", 10),
            width=width or 0,
            bg=bg,
            fg=fg,
            activebackground=hbg,
            activeforeground=fg,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=c["border"] if kind in ("standard", "subtle", "ghost") else bg,
            highlightcolor=c["border_hot"],
            padx=18,
            pady=10,
            cursor="hand2",
            command=command,
        )
        self._hover(btn, bg, hbg)
        return btn

    def log_area(self, parent, height: int = 14) -> tk.Text:
        from tkinter import scrolledtext

        log = scrolledtext.ScrolledText(
            parent,
            height=height,
            font=("Consolas", 9),
            bg=self.c["input"],
            fg=self.c["fg"],
            insertbackground=self.c["fg"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=self.c["border"],
            state="disabled",
        )
        return log

    def center_window(self, window: tk.Toplevel, parent: tk.Misc) -> None:
        window.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() // 2) - (window.winfo_width() // 2)
        y = parent.winfo_rooty() + (parent.winfo_height() // 2) - (window.winfo_height() // 2)
        window.geometry(f"+{max(0, x)}+{max(0, y)}")
        # fade-in del diálogo
        fade_in_window(window, steps=8, delay_ms=18)

    def fade_in_widget(self, widget: tk.Misc, *, steps: int = 10, delay_ms: int = 20) -> None:
        """Simula aparición: eleva opacidad visual del borde/fondo."""
        if not self.anim:
            return
        start = self.c["bg"]
        end = widget.cget("bg") if "bg" in widget.keys() else self.c["card"]

        def on_frame(t, _i):
            try:
                if "bg" in widget.keys():
                    widget.configure(bg=lerp_color(start, end, t))
            except tk.TclError:
                pass

        self.anim.run(f"fadew-{id(widget)}", steps, delay_ms, on_frame)


def fade_in_window(window: tk.Misc, *, steps: int = 12, delay_ms: int = 20, start: float = 0.0) -> None:
    """Fade-in de ventana con atributos -alpha (Windows)."""
    try:
        window.attributes("-alpha", start)
    except tk.TclError:
        return

    def tick(i: int = 0):
        t = ease_out_cubic(i / max(steps - 1, 1))
        try:
            window.attributes("-alpha", start + (1.0 - start) * t)
        except tk.TclError:
            return
        if i < steps - 1:
            window.after(delay_ms, lambda: tick(i + 1))
        else:
            try:
                window.attributes("-alpha", 1.0)
            except tk.TclError:
                pass

    tick(0)


def fade_out_window(window: tk.Misc, *, steps: int = 10, delay_ms: int = 18, on_done=None) -> None:
    try:
        window.attributes("-alpha", 1.0)
    except tk.TclError:
        if on_done:
            on_done()
        return

    def tick(i: int = 0):
        t = ease_in_out(i / max(steps - 1, 1))
        try:
            window.attributes("-alpha", 1.0 - t)
        except tk.TclError:
            if on_done:
                on_done()
            return
        if i < steps - 1:
            window.after(delay_ms, lambda: tick(i + 1))
        else:
            if on_done:
                on_done()

    tick(0)


class ScrollableFrame(tk.Frame):
    """Contenedor con scroll vertical para pestañas con mucho contenido."""

    def __init__(self, parent, colors: dict | None = None, **kwargs):
        c = {**FLUENT, **(colors or {})}
        super().__init__(parent, bg=c["bg"], **kwargs)
        self._canvas = tk.Canvas(self, bg=c["bg"], highlightthickness=0, borderwidth=0)
        self._scrollbar = ttk.Scrollbar(self, orient="vertical", command=self._canvas.yview)
        self.body = tk.Frame(self._canvas, bg=c["bg"])
        self._win = self._canvas.create_window((0, 0), window=self.body, anchor="nw")
        self._canvas.configure(yscrollcommand=self._scrollbar.set)
        self._scrollbar.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)
        self.body.bind("<Configure>", self._on_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        self.bind_mousewheel(self._canvas)

    def _on_configure(self, _event=None):
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self._canvas.itemconfigure(self._win, width=event.width)

    def bind_mousewheel(self, widget):
        widget.bind("<Enter>", lambda _e: widget.bind_all("<MouseWheel>", self._on_mousewheel))
        widget.bind("<Leave>", lambda _e: widget.unbind_all("<MouseWheel>"))

    def _on_mousewheel(self, event):
        self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")


class LoadingSplash(tk.Toplevel):
    """Pantalla de carga profesional con fade y pasos animados (Toplevel del root app)."""

    _STEPS = (
        "Entorno",
        "Dependencias",
        "FFmpeg",
        "Interfaz",
    )

    def __init__(self, title: str, version: str = "", colors: dict | None = None, master: tk.Misc | None = None):
        # Preferir Toplevel del root principal para un solo mainloop
        if master is None:
            # fallback: crear root temporal invisible
            self._owned_root = tk.Tk()
            self._owned_root.withdraw()
            master = self._owned_root
        else:
            self._owned_root = None
        super().__init__(master)
        self.c = {**FLUENT, **(colors or {})}
        self._allow_close = False
        self._alive = True
        self.anim = Animator(self)

        self.title(title)
        self.configure(bg=self.c["bg"])
        self.resizable(False, False)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        apply_fluent_style(self)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        w, h = 540, 320
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")

        try:
            self.attributes("-alpha", 0.0)
        except tk.TclError:
            pass

        outer = tk.Frame(self, bg=self.c["border"], highlightthickness=0)
        outer.pack(fill="both", expand=True, padx=1, pady=1)

        root = tk.Frame(outer, bg=self.c["surface"])
        root.pack(fill="both", expand=True)

        self._top_bar = tk.Frame(root, bg=self.c["accent"], height=3)
        self._top_bar.pack(fill="x")
        self._top_bar.pack_propagate(False)

        body = tk.Frame(root, bg=self.c["surface"])
        body.pack(fill="both", expand=True, padx=32, pady=24)

        self._brand = tk.Label(
            body,
            text="REMIXZ",
            font=("Segoe UI Black", 34),
            fg=self.c["accent_light"],
            bg=self.c["surface"],
        )
        self._brand.pack(anchor="w")
        tk.Label(
            body,
            text=title,
            font=("Segoe UI Semibold", 12),
            fg=self.c["fg"],
            bg=self.c["surface"],
        ).pack(anchor="w", pady=(2, 0))
        if version:
            tk.Label(
                body,
                text=version,
                font=("Segoe UI", 9),
                fg=self.c["muted"],
                bg=self.c["surface"],
            ).pack(anchor="w", pady=(2, 16))

        self.status = tk.Label(
            body,
            text="Iniciando...",
            font=("Segoe UI", 10),
            fg=self.c["muted"],
            bg=self.c["surface"],
            anchor="w",
        )
        self.status.pack(fill="x", pady=(0, 12))

        self.prog = RoundedGradientProgress(
            body,
            height=12,
            maximum=100,
            mode="determinate",
            colors=self.c,
            gradient=(self.c["accent"], self.c["cyan"]),
            bg=self.c["surface"],
        )
        self.prog.pack(fill="x")

        pct_row = tk.Frame(body, bg=self.c["surface"])
        pct_row.pack(fill="x", pady=(6, 16))
        self.pct = tk.Label(
            pct_row,
            text="0%",
            font=("Segoe UI Semibold", 10),
            fg=self.c["accent_light"],
            bg=self.c["surface"],
        )
        self.pct.pack(side="right")

        steps_row = tk.Frame(body, bg=self.c["surface"])
        steps_row.pack(fill="x")
        self._step_labels: list[tk.Label] = []
        for step in self._STEPS:
            lbl = tk.Label(
                steps_row,
                text=f"○ {step}",
                font=("Segoe UI", 8),
                fg=self.c["muted"],
                bg=self.c["surface"],
            )
            lbl.pack(side="left", padx=(0, 14))
            self._step_labels.append(lbl)

        self.update_idletasks()
        fade_in_window(self, steps=14, delay_ms=18)
        self._pulse_top()

    def _pulse_top(self) -> None:
        c0, c1 = self.c["accent"], self.c["accent_light"]
        state = {"up": True}

        def loop():
            if not getattr(self, "_alive", False):
                return
            a, b = (c0, c1) if state["up"] else (c1, c0)
            state["up"] = not state["up"]

            def on_frame(t, _i):
                if not getattr(self, "_alive", False):
                    return
                try:
                    self._top_bar.configure(bg=lerp_color(a, b, t))
                    self._brand.configure(
                        fg=lerp_color(
                            self.c["accent_light"],
                            self.c["glow"],
                            t if state["up"] else 1 - t,
                        )
                    )
                except tk.TclError:
                    pass

            def on_done():
                if not getattr(self, "_alive", False):
                    return
                try:
                    self.after(30, loop)
                except tk.TclError:
                    pass

            self.anim.run("splash-pulse", 20, 30, on_frame, on_done, easing=ease_in_out)

        loop()

    def set_status(self, text: str, percent: int | None = None, *, step: int | None = None) -> None:
        self.status.configure(text=text)
        if percent is not None:
            pct = max(0, min(100, int(percent)))
            # animar barra suavemente
            try:
                current = float(self.prog["value"])
            except Exception:
                current = 0
            target = pct
            steps = 8

            def on_frame(t, _i):
                try:
                    self.prog["value"] = current + (target - current) * t
                    self.pct.configure(text=f"{int(self.prog['value'])}%")
                except tk.TclError:
                    pass

            self.anim.run("splash-prog", steps, 16, on_frame)
        if step is not None:
            done_all = percent is not None and int(percent) >= 100
            for i, lbl in enumerate(self._step_labels):
                if done_all or i < step:
                    lbl.configure(text=f"● {self._STEPS[i]}", fg=self.c["success"])
                elif i == step:
                    lbl.configure(text=f"◉ {self._STEPS[i]}", fg=self.c["accent_light"])
                else:
                    lbl.configure(text=f"○ {self._STEPS[i]}", fg=self.c["muted"])
        self.update_idletasks()

    def allow_close(self, value: bool = True) -> None:
        self._allow_close = value

    def _on_close(self) -> None:
        if self._allow_close:
            self.destroy()

    def fade_out_and_destroy(self, on_done=None) -> None:
        self._allow_close = True
        self._alive = False
        try:
            self.anim.cancel_all()
        except Exception:
            pass

        def done():
            try:
                self.destroy()
            except Exception:
                pass
            if self._owned_root is not None:
                try:
                    self._owned_root.destroy()
                except Exception:
                    pass
            if on_done:
                try:
                    on_done()
                except Exception:
                    pass

        fade_out_window(self, steps=10, delay_ms=16, on_done=done)
