"""utils/charts.py — themed matplotlib rendering for player-facing visuals.

One place for the lounge's look (dark slate + gold, Poppins, weapon icons), so
every command that grows a chart matches instead of each reinventing it.

Renders are BLOCKING — callers must go through render_async, which offloads to a
thread. matplotlib on the event loop would stall the whole bot.

Fonts and weapon icons are vendored in assets/ so Railway has them; the sandbox
having a font installed says nothing about the deploy.
"""
import asyncio
import io
import os
import re

# ── Theme ────────────────────────────────────────────────────────────────────
BG = '#22242a'          # deeper than Discord's own grey so the embed frames it
PANEL = '#2b2d34'
FG = '#f2f3f5'
MUT = '#8b8f9a'
GRID = '#34373f'
GOLD = '#e0a84c'
CORAL = '#d85a30'
BLUE = '#5b8dd9'
PURPLE = '#7a89c2'
TEAL = '#4fb3a1'

ACCENTS = [GOLD, CORAL, BLUE, TEAL, PURPLE]

_ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'assets')
_FONT_DIR = os.path.join(_ASSETS, 'fonts')
_ICON_DIR = os.path.join(_ASSETS, 'weapons')

_FONT_READY = False
_FONT_FAMILY = 'DejaVu Sans'    # fallback if the vendored font is missing


def _ensure_font():
    """Register the vendored Poppins once. Falls back silently to the matplotlib
    default, because a missing font should degrade the look, not break rendering."""
    global _FONT_READY, _FONT_FAMILY
    if _FONT_READY:
        return _FONT_FAMILY
    _FONT_READY = True
    try:
        import matplotlib.font_manager as fm
        added = 0
        for fn in ('Poppins-Regular.ttf', 'Poppins-Medium.ttf', 'Poppins-Bold.ttf'):
            p = os.path.join(_FONT_DIR, fn)
            if os.path.exists(p):
                fm.fontManager.addfont(p)
                added += 1
        if added:
            _FONT_FAMILY = 'Poppins'
    except Exception as e:
        print(f"[CHARTS] font registration failed, using default: {e}")
    return _FONT_FAMILY


def _new_figure(figsize):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fam = _ensure_font()
    plt.rcParams['font.family'] = fam
    plt.rcParams['axes.unicode_minus'] = False
    fig = plt.figure(figsize=figsize)
    fig.patch.set_facecolor(BG)
    return plt, fig


def _style_axis(ax, *, grid_axis='y'):
    """Tier-1 restyle: no box, hairline grid, muted ticks."""
    ax.set_facecolor(BG)
    for side in ('top', 'right', 'left', 'bottom'):
        ax.spines[side].set_visible(False)
    ax.tick_params(colors=MUT, labelsize=9, length=0)
    if grid_axis in ('x', 'both'):
        ax.xaxis.grid(True, color=GRID, linewidth=0.8, alpha=0.7)
    if grid_axis in ('y', 'both'):
        ax.yaxis.grid(True, color=GRID, linewidth=0.8, alpha=0.7)
    ax.set_axisbelow(True)


# ── Weapon icons ─────────────────────────────────────────────────────────────
def _icon_path(label):
    """Map a weapon label to its vendored icon, or None. Normalises the way the
    filenames are named: lowercase, no spaces or punctuation."""
    if not label:
        return None
    key = re.sub(r'[^a-z0-9]', '', str(label).lower())
    p = os.path.join(_ICON_DIR, f'{key}.webp')
    return p if os.path.exists(p) else None


def _draw_icons(fig, ax, labels, *, size=0.040, gap=0.012):
    """Composite weapon icons in a gutter left of the y tick labels.

    The column is MEASURED, not guessed: after a draw pass, the leftmost extent
    of the rendered tick labels is the reference, so icons clear even the longest
    weapon name and the helper works for any subplot position. Earlier fixed-x
    versions collided with the labels the moment the layout changed.

    Labels with no icon (players, maps, feats) are skipped, so one helper serves
    every grouping.
    """
    try:
        from PIL import Image
        import numpy as np
    except Exception:
        return
    fig.canvas.draw()   # tick positions/extents aren't final until a draw pass
    inv = fig.transFigure.inverted()
    # Leftmost edge of the tick-label block, in figure coords.
    try:
        lefts = [inv.transform((t.get_window_extent().x0, 0))[0]
                 for t in ax.get_yticklabels() if t.get_text()]
        label_left = min(lefts) if lefts else inv.transform(
            ax.transAxes.transform((0, 0)))[0]
    except Exception:
        label_left = inv.transform(ax.transAxes.transform((0, 0)))[0]
    x = max(0.002, label_left - gap - size)

    for i, lab in enumerate(labels):
        ip = _icon_path(lab)
        if not ip:
            continue
        try:
            img = Image.open(ip).convert('RGBA')
            _, ydev = ax.transData.transform((0, i))
            _, yf = inv.transform((0, ydev))
            iax = fig.add_axes([x, yf - size / 2, size, size], zorder=5)
            iax.imshow(np.asarray(img), interpolation='lanczos')
            iax.axis('off')
            iax.patch.set_alpha(0)
        except Exception:
            continue


async def render_async(fn, *args, **kwargs) -> bytes:
    """Run a blocking render function in a thread and return PNG bytes."""
    return await asyncio.to_thread(fn, *args, **kwargs)


def render_activity_dashboard(*, title, subtitle, series_labels, series_counts,
                              top_players, top_weapons, footer) -> bytes:
    """Activity over a window. BLOCKING — call via render_async."""
    plt, fig = _new_figure((11, 8.6))
    gs = fig.add_gridspec(2, 2, height_ratios=[1.12, 1.0],
                          hspace=0.46, wspace=0.40,
                          left=0.085, right=0.965, top=0.845, bottom=0.085)

    fig.text(0.085, 0.955, title, color=FG, fontsize=23, fontweight='bold', ha='left')
    fig.text(0.085, 0.912, subtitle, color=MUT, fontsize=12.5, ha='left')
    # Gold rule under the header — cheap, and it makes the block read as designed.
    fig.add_artist(plt.Line2D([0.085, 0.965], [0.893, 0.893],
                              color=GOLD, linewidth=1.4, alpha=0.55))

    ax1 = fig.add_subplot(gs[0, :])
    _style_axis(ax1, grid_axis='y')
    xs = list(range(len(series_counts)))
    ax1.fill_between(xs, series_counts, color=GOLD, alpha=0.055, zorder=1)
    ax1.plot(xs, series_counts, color=GOLD, linewidth=2.6, zorder=2,
             solid_capstyle='round')
    ax1.plot(xs, series_counts, 'o', color=GOLD, markersize=5, zorder=3,
             markeredgecolor=BG, markeredgewidth=1.5)
    ax1.set_xticks(xs)
    ax1.set_xticklabels(series_labels, fontsize=9.5, color=MUT)
    ax1.set_ylim(bottom=0)
    ax1.margins(x=0.03)
    ax1.set_title('Submissions over time', color=FG, fontsize=13.5, pad=12,
                  loc='left', fontweight='medium')
    if series_counts:
        _peak = max(series_counts)
        if _peak:
            _pi = series_counts.index(_peak)
            ax1.annotate(f'{_peak}', (_pi, _peak), textcoords='offset points',
                         xytext=(0, 9), ha='center', color=GOLD,
                         fontsize=11, fontweight='bold')

    ax2 = fig.add_subplot(gs[1, 0])
    _style_axis(ax2, grid_axis='x')
    _draw_hbar(ax2, top_players, 'Most active players')

    ax3 = fig.add_subplot(gs[1, 1])
    _style_axis(ax3, grid_axis='x')
    _draw_hbar(ax3, top_weapons, 'Top weapons')
    _draw_icons(fig, ax3, [p[0] for p in top_weapons][::-1], size=0.032)

    fig.text(0.965, 0.022, footer, color=MUT, fontsize=8.5, ha='right')

    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=125, facecolor=BG, bbox_inches='tight')
    plt.close(fig)
    return buf.getvalue()


def render_breakdown(*, title, subtitle, pairs, value_label, footer,
                     value_fmt=None, samples=None) -> bytes:
    """A single horizontal-bar breakdown. BLOCKING — call via render_async."""
    _n = max(1, len(pairs))
    plt, fig = _new_figure((10, 2.5 + _n * 0.48))
    _top = 0.845 if _n > 3 else 0.78
    fig.subplots_adjust(left=0.385, right=0.945, top=_top, bottom=0.115)

    fig.text(0.055, 0.945, title, color=FG, fontsize=21, fontweight='bold', ha='left')
    fig.text(0.055, 0.897, subtitle, color=MUT, fontsize=12.5, ha='left')
    fig.add_artist(plt.Line2D([0.055, 0.945], [0.876, 0.876],
                              color=GOLD, linewidth=1.4, alpha=0.55))

    ax = fig.add_subplot(111)
    _style_axis(ax, grid_axis='x')

    if not pairs:
        ax.text(0.5, 0.5, 'no data', color=MUT, fontsize=12, ha='center', va='center')
        ax.set_xticks([]); ax.set_yticks([])
    else:
        _fmt = value_fmt or (lambda v: str(int(round(v))))
        labels = [p[0] for p in pairs][::-1]
        vals = [p[1] for p in pairs][::-1]
        _samp = list(samples)[::-1] if samples else [None] * len(vals)
        colours = [ACCENTS[i % len(ACCENTS)] for i in range(len(vals))][::-1]
        y = list(range(len(vals)))
        ax.barh(y, vals, color=colours, height=0.66)
        ax.set_yticks(y)
        ax.set_yticklabels(labels, color=FG, fontsize=10)
        _mx = max(vals) or 1
        for i, v in enumerate(vals):
            _txt = _fmt(v) + (f"   ({_samp[i]})" if _samp[i] is not None else "")
            ax.text(v + _mx * 0.022, i, _txt, color=FG, fontsize=9.5, va='center')
        ax.set_xlim(right=_mx * 1.20)
        _draw_icons(fig, ax, labels, size=0.052)
    ax.set_xlabel(value_label, color=MUT, fontsize=10.5, labelpad=8)

    fig.text(0.945, 0.025, footer, color=MUT, fontsize=8.5, ha='right')
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=125, facecolor=BG, bbox_inches='tight')
    plt.close(fig)
    return buf.getvalue()


def _draw_hbar(ax, pairs, title):
    if not pairs:
        ax.text(0.5, 0.5, 'no data', color=MUT, fontsize=11, ha='center', va='center')
        ax.set_xticks([]); ax.set_yticks([])
        ax.set_title(title, color=FG, fontsize=13.5, pad=12, loc='left',
                     fontweight='medium')
        return
    labels = [p[0] for p in pairs][::-1]
    vals = [p[1] for p in pairs][::-1]
    colours = [ACCENTS[i % len(ACCENTS)] for i in range(len(vals))][::-1]
    y = list(range(len(vals)))
    ax.barh(y, vals, color=colours, height=0.66)
    ax.set_yticks(y)
    ax.set_yticklabels(labels, color=FG, fontsize=9.5)
    ax.set_title(title, color=FG, fontsize=13.5, pad=12, loc='left',
                 fontweight='medium')
    _mx = max(vals) or 1
    for i, v in enumerate(vals):
        ax.text(v + _mx * 0.025, i, str(v), color=FG, fontsize=9.5, va='center')
    ax.set_xlim(right=_mx * 1.18)
