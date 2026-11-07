"""Gráficas y tablas del cuaderno de sustentación.

Las gráficas se dibujan con matplotlib (imagen). Las tablas son DataFrames de pandas con el formato nativo del visor (VS Code, Jupyter).

Estilo según la skill de visualización: paleta categórica validada (azul = slot 1, naranja = slot 2; pasan todos los
chequeos de CVD y contraste), rampa secuencial azul para magnitud, marcas finas, cuadrícula hairline, texto en tintas
de texto (nunca en el color de la serie) y leyenda siempre presente con 2 o más series.
"""
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from IPython.display import display
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import FancyBboxPatch, Rectangle

ROOT = Path(__file__).resolve().parent.parent

# ---- paleta (superficie clara) ------------------------------------------------------------------------------------
SURF, INK, INK2, MUTED = "#fcfcfb", "#0b0b0b", "#52514e", "#898781"
GRID, AXIS = "#e1e0d9", "#c3c2b7"
S1, S2 = "#2a78d6", "#eb6834"                       # categórica, slots 1 y 2
SEQ = ["#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7", "#3987e5", "#2a78d6", "#256abf", "#1c5cab",
       "#184f95", "#104281", "#0d366b"]             # secuencial azul 100 → 700
CMAP = LinearSegmentedColormap.from_list("lifemap_seq", SEQ)
TINT = "#cde2fb"                                    # fila destacada en tablas


def configurar():
    """Estilo global: tipografía del sistema, retina y fondo de la superficie."""
    from matplotlib_inline.backend_inline import set_matplotlib_formats
    set_matplotlib_formats("retina")
    plt.rcParams.update({
        "font.family": ["Segoe UI", "DejaVu Sans"], "figure.dpi": 100, "figure.facecolor": SURF, "savefig.facecolor": SURF,
        "axes.facecolor": SURF, "axes.edgecolor": AXIS, "axes.labelcolor": INK2, "xtick.color": MUTED, "ytick.color": MUTED,
        "text.color": INK, "axes.spines.top": False, "axes.spines.right": False, "axes.linewidth": 1,
        "xtick.labelsize": 9, "ytick.labelsize": 9, "axes.labelsize": 9.5, "legend.frameon": False, "legend.fontsize": 9.5,
    })


# ---- formato de números (es-CO: 1.234,5) ---------------------------------------------------------------------------
def num(x, d=0):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "—"
    s = f"{x:,.{d}f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def pct(x, d=1):
    return num(x, d) + " %"


# ---- encabezado de una figura --------------------------------------------------------------------------------------
def cabecera(fig, titulo, subtitulo=None, x=0.012):
    fig.text(x, 0.985, titulo, ha="left", va="top", fontsize=13, fontweight="semibold", color=INK)
    if subtitulo:
        fig.text(x, 0.985 - 0.075 * (4.2 / fig.get_figheight()), subtitulo, ha="left", va="top", fontsize=9.5, color=INK2)


def ejes(fig, rect):
    ax = fig.add_axes(rect)
    ax.tick_params(length=0)
    return ax


def rejilla_y(ax):
    ax.yaxis.grid(True, color=GRID, lw=1)
    ax.set_axisbelow(True)


def rejilla_x(ax):
    ax.xaxis.grid(True, color=GRID, lw=1)
    ax.set_axisbelow(True)


# ---- tablas: DataFrame nativo (así lo dibuja VS Code / Jupyter) ----------------------------------------------------------
def tabla(df, titulo=None, formatos=None, resaltar=(), **_):
    """Muestra un DataFrame con el formato nativo del visor, sin índice y con números en formato es-CO (1.234,5).

    formatos: {columna: función}. resaltar: posiciones de fila que se ponen en negrita."""
    formatos = formatos or {}
    df = df.reset_index(drop=True)
    st = df.style.hide(axis="index")
    fm = {}
    for c in df.columns:
        if c in formatos:
            fm[c] = formatos[c]
        elif np.issubdtype(df[c].dtype, np.integer):
            fm[c] = num
        elif np.issubdtype(df[c].dtype, np.floating):
            fm[c] = lambda v: num(v, 2)
    st = st.format(fm)
    if resaltar:
        st = st.apply(lambda fila: ["font-weight: 600" if fila.name in resaltar else ""] * len(fila), axis=1)
    if titulo:
        st = st.set_caption(titulo)
    display(st)


# ---- barras horizontales: 4 px redondeado en la punta, cuadrado en la base --------------------------------------------
def barras_h(ax, valores, color=S1, grosor_px=18, radio_px=4, margen=1.18):
    n = len(valores)
    xmax = max(valores) * margen
    ax.set_xlim(0, xmax); ax.set_ylim(n - 0.5, -0.5)
    caja = ax.get_window_extent()
    pxx, pxy = caja.width / xmax, caja.height / n
    h, rs = grosor_px / pxy, radio_px / pxx
    for i, v in enumerate(valores):
        ax.add_patch(FancyBboxPatch((0, i - h / 2), v, h, boxstyle=f"round,pad=0,rounding_size={rs}", mutation_aspect=pxx / pxy,
                                    fc=color, ec="none", zorder=3))
        ax.add_patch(Rectangle((0, i - h / 2), min(v, rs), h, fc=color, ec="none", zorder=3))   # base cuadrada
    return pxx


# ---- matriz de confusión (mapa de calor secuencial, con 2 px de separación) -------------------------------------------
def matriz(ax, cm, etiquetas, titulo):
    cm = np.asarray(cm)
    p = cm / cm.sum(1, keepdims=True)
    ax.pcolormesh(p, cmap=CMAP, vmin=0, vmax=1, edgecolors=SURF, linewidth=3)
    ax.set_xlim(0, cm.shape[1]); ax.set_ylim(cm.shape[0], 0)
    for i in range(cm.shape[0]):
        for j in range(cm.shape[1]):
            ax.text(j + .5, i + .5, f"{num(cm[i, j])}\n{round(100 * p[i, j])} %", ha="center", va="center", fontsize=9.5,
                    color="#ffffff" if p[i, j] > .5 else INK)
    ax.set_xticks(np.arange(len(etiquetas)) + .5, etiquetas); ax.set_yticks(np.arange(len(etiquetas)) + .5, etiquetas)
    ax.tick_params(length=0, labelcolor=INK2)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_xlabel("predicho", labelpad=8); ax.set_ylabel("real", labelpad=10)
    ax.set_title(titulo, loc="left", fontsize=11, fontweight="semibold", color=INK, pad=10)
    return ax


# ---- código del repositorio con resaltado de sintaxis (claro u oscuro según el tema del visor) ------------------------------
def fuente(ruta, desde, hasta=None):
    """Muestra, con resaltado de sintaxis, un fragmento del archivo REAL del repositorio: desde la línea que contiene `desde` hasta antes de la que contiene `hasta`."""
    nombre_archivo = Path(ruta).name
    if nombre_archivo.startswith("terraform.tfstate") or nombre_archivo in ("terraform.tfvars", ".env") or nombre_archivo.endswith(".pem"):
        raise ValueError(f"{nombre_archivo} puede contener secretos y no se muestra nunca en el cuaderno")
    lineas = (ROOT / ruta).read_text(encoding="utf-8").splitlines()
    i = next(k for k, l in enumerate(lineas) if desde in l)
    j = len(lineas) if hasta is None else next(k for k in range(i + 1, len(lineas)) if hasta in lineas[k])
    codigo = "\n".join(lineas[i:j])
    from html import escape
    from pygments import highlight
    from pygments.formatters import HtmlFormatter
    from pygments.lexers import get_lexer_by_name
    nombre = Path(ruta).name
    lenguaje = "groovy" if nombre == "Jenkinsfile" else {".py": "python", ".sh": "bash", ".yml": "yaml", ".yaml": "yaml", ".tf": "terraform", ".tftpl": "bash"}.get(Path(ruta).suffix, "text")
    cuerpo = highlight(codigo, get_lexer_by_name(lenguaje), HtmlFormatter(cssclass="lm-code", style="default"))
    html = _css_codigo(set(__import__('re').findall(r'class="([^"]+)"', cuerpo))) + f'<div class="lm-box"><div class="lm-head">{escape(ruta)} · líneas {i + 1}–{j}</div>{cuerpo}</div>'
    # text/plain queda como respaldo para los visores que no muestran HTML
    display({"text/html": html, "text/plain": f"# {ruta}, líneas {i + 1}–{j}\n{codigo}"}, raw=True)


_TEMAS_OSCUROS = (".vscode-dark", ".vscode-high-contrast:not(.vscode-high-contrast-light)", "body[data-jp-theme-light='false']")


def _css_codigo(clases_usadas=()):
    """CSS del bloque de código con dos paletas: clara (por defecto) y oscura cuando el visor está en tema oscuro.

    Detección del tema: VS Code pone la clase `vscode-dark` en el body del visor de resultados; JupyterLab usa
    data-jp-theme-light='false'; un HTML suelto (el respaldo) usa la preferencia del sistema (prefers-color-scheme)."""
    from pygments.formatters import HtmlFormatter
    usadas = {c for grupo in clases_usadas for c in grupo.split()}

    def reglas(estilo):
        """Solo las reglas de los tokens que el fragmento usa (sin las globales de Pygments: pre, td.linenos...) y sin comentarios."""
        import re
        out = []
        for l in HtmlFormatter(style=estilo).get_style_defs(".lm-box .lm-code").splitlines():
            if not l.startswith(".lm-box"):
                continue
            m = re.match(r"\.lm-box \.lm-code \.([A-Za-z0-9_]+)", l)
            if m and clases_usadas and m.group(1) not in usadas:
                continue
            out.append(re.sub(r"\s*/\*.*?\*/", "", l))
        return out

    claro = "\n".join(reglas("default"))
    oscuro = reglas("github-dark")

    def con_prefijo(prefijo):
        return "\n".join(f"{prefijo} {l}" if l.startswith(".lm-box") else l for l in oscuro)

    bajo_tema = "".join(con_prefijo(sel) + "\n" for sel in _TEMAS_OSCUROS)
    sistema = "body:not(.vscode-light):not([data-jp-theme-light='true'])"
    fondo = ", ".join(f"{s} .lm-box" for s in _TEMAS_OSCUROS)
    cabecera_ = ", ".join(f"{s} .lm-box .lm-head" for s in _TEMAS_OSCUROS)
    return f"""<style>
.lm-box {{ border:1px solid rgba(128,128,128,.35); border-radius:6px; overflow:hidden; margin:4px 0; background:#fcfcfb; }}
.lm-box .lm-head {{ padding:6px 14px; background:rgba(128,128,128,.14); color:#52514e; font:12px 'Segoe UI',system-ui,sans-serif; border-bottom:1px solid rgba(128,128,128,.3); }}
.lm-box .lm-code {{ margin:0; padding:12px 14px; font-size:12.5px; line-height:1.5; overflow-x:auto; }}
.lm-box .lm-code pre {{ margin:0; line-height:1.5; }}
{claro}
@media (prefers-color-scheme: dark) {{
{con_prefijo(sistema)}
{sistema} .lm-box {{ background:#1a1a19; }}
{sistema} .lm-box .lm-head {{ color:#c3c2b7; }}
}}
{bajo_tema}
{fondo} {{ background:var(--vscode-editor-background, #1a1a19); }}
{cabecera_} {{ color:#c3c2b7; }}
.lm-box .lm-code {{ background:transparent !important; }}
</style>
"""
