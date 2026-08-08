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
import warnings

# Missing-glyph warnings are handled by the DejaVu fallback below; anything the
# fallback can't render (rare emoji in a name) shouldn't spam the nerve centre.
warnings.filterwarnings("ignore", message="Glyph .* missing from font")

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
# Canonical faction colours (Chiv 2): Agatha blue, Mason red, Tenosia gold.
_FACTION_COLOUR = {'Agatha': BLUE, 'Mason': '#d84343', 'Tenosia': GOLD}

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
    plt.rcParams['font.family'] = [fam, 'DejaVu Sans'] if fam != 'DejaVu Sans' else ['DejaVu Sans']
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
    _h = 2.5 + _n * 0.48
    plt, fig = _new_figure((10, _h))
    # Header is positioned in INCHES from the top, converted to figure fractions.
    # Fixed fractions crowd together on a short chart: at 2 bars the figure is
    # ~3.5in tall and the gold rule cut straight through the subtitle.
    def _y(inches_from_top):
        return 1.0 - (inches_from_top / _h)
    fig.subplots_adjust(left=0.385, right=0.945, top=_y(1.05),
                        bottom=(0.62 / _h))

    fig.text(0.055, _y(0.34), title, color=FG, fontsize=21, fontweight='bold',
             ha='left', va='center')
    fig.text(0.055, _y(0.64), subtitle, color=MUT, fontsize=12.5,
             ha='left', va='center')
    fig.add_artist(plt.Line2D([0.055, 0.945], [_y(0.84), _y(0.84)],
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
        # Values can be negative (e.g. lethality vs weapon average), so scale on
        # the full span and label each bar on the side it points.
        _mx = max(vals); _mn = min(vals)
        _span = (max(abs(_mx), abs(_mn)) or 1)
        _pad = _span * 0.028
        for i, v in enumerate(vals):
            _txt = _fmt(v) + (f"   ({_samp[i]})" if _samp[i] is not None else "")
            if v >= 0:
                ax.text(v + _pad, i, _txt, color=FG, fontsize=9.5, va='center', ha='left')
            else:
                ax.text(v - _pad, i, _txt, color=FG, fontsize=9.5, va='center', ha='right')
        # Only extend left of zero when there are ACTUAL negative bars. For the
        # common all-positive chart, the axis starts at 0 so bars fill the width
        # instead of bunching against a pointless negative gap. Right pad leaves
        # room for the value label.
        _has_neg = _mn < 0
        _label_pad = _span * 0.22   # room for "127.3  (19)" past the longest bar
        # Left needs MORE room than right: a right overflow lands in empty chart,
        # but a left overflow hits the y-tick names. So pad the negative side
        # wider (Officer / -2.4 overlap).
        _lo = (_mn - _span * 0.45) if _has_neg else 0
        _hi = max(0, _mx) + _label_pad
        ax.set_xlim(left=_lo, right=_hi)
        if _has_neg and _mx > 0:
            ax.axvline(0, color=MUT, linewidth=0.8, alpha=0.5)  # zero reference
        _draw_icons(fig, ax, labels, size=0.052)
    ax.set_xlabel(value_label, color=MUT, fontsize=10.5, labelpad=8)

    # Footer sits top-right on the subtitle line, not at the bottom: a bottom
    # footer collided with the (centered) x-axis label. Up here it never does.
    fig.text(0.945, _y(0.64), footer, color=MUT, fontsize=8.5,
             ha='right', va='center')
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=125, facecolor=BG, bbox_inches='tight')
    plt.close(fig)
    return buf.getvalue()


def render_season_card(*, player, season_label, gp, rank, field_size,
                       rows, behind=None, footer='') -> bytes:
    """Personal season card.

    rows: [(category, position_or_None, gp_awarded, note)] in display order.
          position None means "not scoring"; note carries the cutoff text.
    behind: optional (gp_gap, name, their_rank) for the chase line.
    BLOCKING — call via render_async.
    """
    _n = max(1, len(rows))
    # header block (1.30in) + rows + footer band (0.75in). Over-allocating left a
    # dead gap under the last row.
    _h = 2.05 + _n * 0.42
    plt, fig = _new_figure((9.2, _h))

    def _y(inches_from_top):
        return 1.0 - (inches_from_top / _h)

    # ── Header block: name, then the GP number as the hero element ───────────
    fig.text(0.055, _y(0.36), player, color=FG, fontsize=22,
             fontweight='bold', ha='left', va='center')
    fig.text(0.055, _y(0.68), season_label, color=MUT, fontsize=12,
             ha='left', va='center')

    _rank_txt = f"{rank} of {field_size}" if rank else "unranked"
    fig.text(0.945, _y(0.40), f"{gp}", color=GOLD, fontsize=34,
             fontweight='bold', ha='right', va='center')
    fig.text(0.945, _y(0.74), f"GP · {_rank_txt}", color=MUT, fontsize=11,
             ha='right', va='center')
    fig.add_artist(plt.Line2D([0.055, 0.945], [_y(0.95), _y(0.95)],
                              color=GOLD, linewidth=1.5, alpha=0.6))

    # ── Category rows ────────────────────────────────────────────────────────
    _top = _y(1.30)
    _row_h = 0.42 / _h
    for i, (cat, pos, pts, note) in enumerate(rows):
        y = _top - i * _row_h
        scoring = pos is not None
        fig.text(0.055, y, cat, color=FG if scoring else MUT,
                 fontsize=11.5, ha='left', va='center')
        if scoring:
            fig.text(0.62, y, _ordinal(pos), color=FG, fontsize=11.5,
                     ha='right', va='center')
            fig.text(0.945, y, f"+{pts} GP", color=GOLD, fontsize=11.5,
                     fontweight='bold', ha='right', va='center')
        else:
            fig.text(0.945, y, note or '—', color=MUT, fontsize=10.5,
                     ha='right', va='center', style='italic')
        # hairline between rows
        if i < len(rows) - 1:
            fig.add_artist(plt.Line2D([0.055, 0.945], [y - _row_h / 2, y - _row_h / 2],
                                      color=GRID, linewidth=0.7, alpha=0.6))

    if behind:
        _gap, _who, _their_rank = behind
        fig.text(0.055, _y(_h - 0.42),
                 f"{_gap} GP behind {_who} in {_ordinal(_their_rank)}",
                 color=FG, fontsize=11.5, ha='left', va='center')
    if footer:
        fig.text(0.945, _y(_h - 0.42), footer, color=MUT, fontsize=8.5,
                 ha='right', va='center')

    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=125, facecolor=BG, bbox_inches='tight')
    plt.close(fig)
    return buf.getvalue()


def _ordinal(n):
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


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


def render_tilt_curve(*, tilts, lean, stomp, n_games) -> bytes:
    """De-biased lobby-tilt distribution. Every game is scored from BOTH teams'
    sides (winner +x, loser -x) so the poster-POV skew (people log their wins)
    cancels and the curve is symmetric by construction. Band zones are drawn
    from the live config thresholds, not hard-coded. BLOCKING: call via
    render_async."""
    import io as _io
    import numpy as _np
    from collections import Counter as _Counter
    plt, fig = _new_figure((10.2, 6.8))
    L, T = int(lean), int(stomp)
    mir = _np.array([v for x in tilts for v in (x, -x)]) if tilts else _np.array([0])
    COLB = {'TG': '#7ea6d6', 'Fav': '#57b36a', 'Even': '#d9c24f',
            'Up': '#d88a30', 'Bru': '#c0392b'}

    def _band(x):
        if x >= T: return 'TG'
        if x >= L: return 'Fav'
        if x > -L: return 'Even'
        if x > -T: return 'Up'
        return 'Bru'

    c = _Counter(_band(x) for x in mir)
    N = max(1, len(mir))
    ax = fig.add_axes([0.06, 0.18, 0.90, 0.55])
    ax.set_facecolor(BG)
    hi = max(90, int(_np.abs(mir).max()) + 15)
    edges = _np.arange(-hi - 5, hi + 6, 10)
    counts, _ = _np.histogram(mir, bins=edges)
    centers = (edges[:-1] + edges[1:]) / 2
    ax.bar(centers, counts, width=9, color=[COLB[_band(cx)] for cx in centers], zorder=3)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(colors=MUT, labelsize=10)
    ax.set_yticks([])
    ticks = sorted({tk for tk in [-150, -100, -T, -50, -L, 0, L, 50, T, 100, 150]
                    if -hi <= tk <= hi})
    ax.set_xticks(ticks)
    ax.set_xlim(-hi, hi)
    for xv in (-T, -L, L, T):
        ax.axvline(xv, color='#4a4d57', lw=1, ls=(0, (4, 3)), zorder=2)
    ymax = max(1, counts.max())
    ax.set_ylim(0, ymax * 1.30)
    mid = (L + T) / 2
    lab = [('Brutal', -(T + 30), 'Bru'), ('Uphill', -mid, 'Up'), ('Even', 0, 'Even'),
           ('Favoured', mid, 'Fav'), ('Training Grounds', T + 55, 'TG')]
    for name, x, k in lab:
        ax.text(x, ymax * 1.25, name, ha='center', color=COLB[k], fontsize=12.5, fontweight='bold')
        ax.text(x, ymax * 1.16, f'{round(100 * c[k] / N, 1)}%', ha='center', color=MUT, fontsize=11)
    ax.set_xlabel('Team kill-gap %   (– your side outkilled     + you outkilled them)',
                  color=MUT, fontsize=11, labelpad=8)
    fig.text(0.06, 0.915, 'Lobby Tilt distribution', fontsize=24, color=GOLD, fontweight='bold')
    fig.text(0.06, 0.865,
             f'{n_games} logged games scored from both sides = {N} points. '
             f'Bands from live config ({L}% / {T}%).', fontsize=12, color=MUT)
    fig.text(0.06, 0.03,
             'De-biased: both team POVs, so the "people post their wins" skew cancels out.',
             fontsize=10.8, color=FG)
    buf = _io.BytesIO()
    fig.savefig(buf, format='png', dpi=125, facecolor=BG, bbox_inches='tight', pad_inches=0.22)
    plt.close(fig)
    return buf.getvalue()


def render_tilt_ladder(*, counts, n_games) -> bytes:
    """The difficulty ladder (raw kill gap) as horizontal bars, one per
    config.TILT_BANDS row, hardest at top. `counts` is {band_name: n}. Bands that
    pay valor marks are annotated. BLOCKING: call via render_async."""
    import io as _io
    import config
    from matplotlib.patches import FancyBboxPatch as _FBP, Ellipse as _Ell
    plt, fig = _new_figure((10.4, 7.2))
    # colour per band emoji family (hardest -> easiest)
    COLW = {'Brutal': '#c0392b', 'Outmatched': '#d85a30', 'Slightly Uphill': '#d88a30',
            'Even': '#d9c24f', 'Slightly Favoured': '#8bbf6a', 'Favoured': '#57b36a',
            'Training Grounds': '#7ea6d6'}
    rows = list(reversed(config.TILT_BANDS))  # hardest first
    n = max(1, n_games)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, 100); ax.set_ylim(0, 100); ax.axis('off')

    def _t(x, y, s, size=13, color=FG, weight='normal', ha='left', va='center'):
        ax.text(x, y, s, fontsize=size, color=color, weight=weight, ha=ha, va=va)

    _t(5, 94, 'Difficulty ladder', size=23, color=GOLD, weight='bold')
    _t(5, 88.8, f'{n_games} games, raw kill gap between the two teams. Hard tail pays valor marks.',
       size=11.5, color=MUT)
    maxp = max([100.0 * counts.get(nm, 0) / n for (_lo, nm, _e, _m, _tg) in rows] + [1.0])
    x0, xw = 40.0, 40.0
    y, rh = 80, 10.4
    for (_lo, nm, emoji, marks, tag) in rows:
        c = COLW.get(nm, MUT)
        pct = 100.0 * counts.get(nm, 0) / n
        ax.add_patch(_Ell((6.5, y), 1.5, 1.95, color=c, zorder=3))
        _t(9, y, nm, size=14, color=FG, weight='bold')
        if marks:
            _t(9, y - 2.7, f'+{marks} mark{"s" if marks != 1 else ""}',
               size=10.5, color='#e6b45a', weight='bold')
        elif nm == 'Training Grounds':
            _t(9, y - 2.7, 'roast only, no marks', size=10.5, color=MUT)
        ax.add_patch(_FBP((x0, y - 1.7), xw, 3.4, boxstyle="round,pad=0,rounding_size=1",
                          fc=PANEL, ec='none', zorder=1))
        w = max(0.5, xw * pct / maxp)
        ax.add_patch(_FBP((x0, y - 1.7), w, 3.4, boxstyle="round,pad=0,rounding_size=1",
                          fc=c, ec='none', zorder=2))
        _t(x0 + xw + 2, y, f'{pct:.1f}%  ({counts.get(nm, 0)})', size=12.5, color=c, weight='bold')
        y -= rh
    ax.add_patch(plt.Rectangle((5, 3), 90, 6.5, color='#2f3138', zorder=0))
    _t(8, 6.2, 'Rolled on defence and still dropped 100? You land in the hard tail. Raw % would call it Even and pay nothing.',
       size=10.6, color=FG)
    buf = _io.BytesIO()
    fig.savefig(buf, format='png', dpi=125, facecolor=BG, bbox_inches='tight', pad_inches=0.22)
    plt.close(fig)
    return buf.getvalue()


_OUTLINE_DIR = os.path.join(_ASSETS, 'weapon_outlines')


def render_lethality_charge(weapon, delta=0, dmax=15.0, intensity=None) -> bytes:
    """Weapon silhouette tinted grey -> red by how far a run's lethality sits
    ABOVE that weapon's average. At or below the average it stays neutral grey;
    it reaches full red at intensity 1.0 (red = lethal, matching the blood motif).
    Driven by `intensity` in [0, 1]; the legacy `delta` path maps a percentage-
    point delta onto the same grey -> red ramp.
    Returns a transparent PNG for use as an embed thumbnail, or b'' when the
    weapon has no vendored outline (caller falls back to text). BLOCKING."""
    import io as _io
    try:
        from PIL import Image as _Img
    except Exception:
        return b''
    key = re.sub(r'[^a-z0-9]', '', str(weapon or '').lower())
    p = os.path.join(_OUTLINE_DIR, key + '.webp')
    if not key or not os.path.exists(p):
        return b''
    try:
        im = _Img.open(p).convert('RGBA')
    except Exception:
        return b''
    # Intensity 0..1: 0 = neutral grey (at/below the weapon average), 1 = full
    # red (well above it). Red reads as lethal, matching the blood motif.
    if intensity is not None:
        t = max(0.0, min(1.0, intensity))
    else:
        t = max(0.0, min(1.0, (delta or 0) / dmax))
    grey = (150, 152, 158)
    red = (210, 70, 70)
    col = (int(grey[0] + (red[0] - grey[0]) * t),
           int(grey[1] + (red[1] - grey[1]) * t),
           int(grey[2] + (red[2] - grey[2]) * t))
    px = im.load()
    w, h = im.size
    for x in range(w):
        for y in range(h):
            a = px[x, y][3]
            if a:
                px[x, y] = col + (a,)
    # No edge feathering: the source outlines are already anti-aliased, so a blur
    # only adds an outward halo rather than smoothing anything.
    buf = _io.BytesIO()
    im.save(buf, format='PNG')
    return buf.getvalue()


def render_trend(*, title, subtitle, labels, values, value_label, footer,
                 value_fmt=None, samples=None) -> bytes:
    """A single time-series line (for /explore grouped by week/month). Oldest ->
    newest, left to right. BLOCKING: call via render_async."""
    plt, fig = _new_figure((10, 5.4))

    def _y(inches_from_top):
        return 1.0 - (inches_from_top / 5.4)

    fig.subplots_adjust(left=0.09, right=0.955, top=_y(1.05), bottom=0.19)
    fig.text(0.055, _y(0.34), title, color=FG, fontsize=21, fontweight='bold', ha='left', va='center')
    fig.text(0.055, _y(0.64), subtitle, color=MUT, fontsize=12.5, ha='left', va='center')
    fig.add_artist(plt.Line2D([0.055, 0.955], [_y(0.84), _y(0.84)], color=GOLD, linewidth=1.4, alpha=0.55))
    ax = fig.add_subplot(111)
    _style_axis(ax, grid_axis='y')
    if not labels:
        ax.text(0.5, 0.5, 'no data', color=MUT, fontsize=12, ha='center', va='center')
        ax.set_xticks([]); ax.set_yticks([])
    else:
        _fmt = value_fmt or (lambda v: str(int(round(v))))
        x = list(range(len(labels)))
        _lo = min(min(values), 0.0)
        ax.fill_between(x, values, _lo, color=GOLD, alpha=0.08, zorder=1)
        ax.plot(x, values, color=GOLD, linewidth=2.2, marker='o', markersize=5,
                markerfacecolor=GOLD, markeredgecolor=BG, zorder=3)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, color=MUT, fontsize=8.5, rotation=45, ha='right')
        _mx_i = max(x, key=lambda i: values[i])
        for i in sorted({0, len(x) - 1, _mx_i}):
            ax.annotate(_fmt(values[i]), (i, values[i]), textcoords="offset points",
                        xytext=(0, 8), ha='center', color=FG, fontsize=9)
        _hi = max(values); _span = (_hi - _lo) or 1
        ax.set_ylim(_lo - _span * 0.08, _hi + _span * 0.20)
        if _lo < 0 < _hi:
            ax.axhline(0, color=MUT, linewidth=0.8, alpha=0.5)
    ax.set_ylabel(value_label, color=MUT, fontsize=10.5, labelpad=8)
    fig.text(0.955, _y(0.64), footer, color=MUT, fontsize=8.5, ha='right', va='center')
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=125, facecolor=BG, bbox_inches='tight')
    plt.close(fig)
    return buf.getvalue()


def render_statscape(*, weapon_weights, damage_map, faction_weights, title, subtitle,
                     signature="Cigar Lounge Butler, mixed media on despair, 2026",
                     feat_icons=None, watermark=None, mood=0.0, nemesis_icon=None,
                     nemesis_name=None, cursed=False, seed=0) -> bytes:
    """A gleefully-silly COLLAGE of a player's (or the server's) real weapon icons plus:
    earned-feat sticker confetti, a faint title/rank watermark, a valor mood-tint (warm
    for uphill grinders, cold for farmers), a struck-out nemesis cameo, a gold museum
    frame, the Butler's signature stamp, and a rare 'cursed' neon variant. Seeded so it is
    stable per-state but drifts as the data does. BLOCKING: call via render_async."""
    import io as _io
    import random as _rnd
    import math as _math
    from matplotlib.patches import Circle as _Circle, RegularPolygon as _Reg, Ellipse as _Ell
    from matplotlib.offsetbox import OffsetImage as _OI, AnnotationBbox as _AB
    try:
        from PIL import Image as _Img
        import numpy as _np
    except Exception:
        _Img = None
    plt, fig = _new_figure((9.6, 9.6))
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, 100); ax.set_ylim(0, 100); ax.axis('off')
    ax.set_facecolor(BG)
    rng = _rnd.Random(seed)

    if cursed:
        DMG = {'Cut': '#ff2d95', 'Chop': '#39ff14', 'Blunt': '#ff6a00', 'Ranged': '#00e5ff'}
        FAC = {'Mason': '#ff2d95', 'Agatha': '#39ff14', 'Tenosia': '#00e5ff'}
        frame_c, wm_c, title_c = '#ff2d95', '#39ff14', '#ff2d95'
    else:
        DMG = {'Cut': BLUE, 'Chop': CORAL, 'Blunt': GOLD, 'Ranged': TEAL}
        FAC = {'Mason': GOLD, 'Agatha': BLUE, 'Tenosia': CORAL}
        frame_c, wm_c, title_c = GOLD, FG, GOLD

    # Valor mood-tint — a full-canvas wash, warm for uphill grinders, cold for farmers.
    if mood:
        ax.add_patch(plt.Rectangle((0, 0), 100, 100, color=(CORAL if mood > 0 else BLUE),
                     alpha=min(0.16, abs(mood) * 0.22), zorder=-2))
    # Title / rank watermark, huge and faint behind everything.
    if watermark:
        ax.text(50, 52, str(watermark).upper(), fontsize=62, color=wm_c, alpha=0.06,
                ha='center', va='center', rotation=16, weight='bold', zorder=-1)

    # Faction blobs.
    _fac = sorted((faction_weights or {}).items(), key=lambda kv: -kv[1])[:4]
    _fmax = max([v for _, v in _fac] + [1])
    for fac, cnt in _fac:
        c = FAC.get(fac, PURPLE)
        r = 20 + 26 * (cnt / _fmax)
        ax.add_patch(_Ell((rng.uniform(25, 75), rng.uniform(28, 78)),
                          r * rng.uniform(1.0, 1.5), r, angle=rng.uniform(0, 180),
                          color=c, alpha=0.09, zorder=0))

    # Weapon icons — biggest-used near centre, the rest ringed around it.
    _w = sorted((weapon_weights or {}).items(), key=lambda kv: -kv[1])[:18]
    _wmax = max([v for _, v in _w] + [1])
    for idx, (wpn, cnt) in enumerate(_w):
        frac = cnt / _wmax
        c = DMG.get((damage_map or {}).get(wpn), PURPLE)
        if idx == 0:
            cx, cy = 50 + rng.uniform(-5, 5), 55 + rng.uniform(-5, 5)
        else:
            ang = rng.uniform(0, 2 * _math.pi); rad = rng.uniform(20, 42)
            cx, cy = 50 + rad * _math.cos(ang), 52 + rad * _math.sin(ang)
        ax.add_patch(_Circle((cx, cy), 5 + 7 * frac, color=c,
                             alpha=0.16 + 0.12 * frac, zorder=1))
        ip = _icon_path(wpn); placed = False
        if _Img and ip:
            try:
                img = _Img.open(ip).convert('RGBA').rotate(
                    rng.uniform(-28, 28), expand=True, resample=_Img.BICUBIC)
                oi = _OI(_np.asarray(img), zoom=0.30 + 0.85 * _math.sqrt(frac),
                         alpha=0.92 if idx == 0 else 0.82)
                ax.add_artist(_AB(oi, (cx, cy), frameon=False, xycoords='data', zorder=3))
                placed = True
            except Exception:
                placed = False
        if not placed:
            sides = [3, 4, 5, 6][sum(ord(ch) for ch in wpn) % 4]
            ax.add_patch(_Reg((cx, cy), sides, radius=3 + 5 * frac,
                              orientation=rng.uniform(0, 6.28), color=c, alpha=0.8,
                              zorder=3, ec=FG, lw=0.6))

    # Feat confetti — the player's earned-feat stickers.
    if feat_icons and _Img:
        for _fp, _wt in feat_icons:
            for _ in range(min(3, max(1, int(_wt)))):
                try:
                    _fi = _Img.open(_fp).convert('RGBA').rotate(
                        rng.uniform(-22, 22), expand=True, resample=_Img.BICUBIC)
                    ax.add_artist(_AB(_OI(_np.asarray(_fi), zoom=0.34, alpha=0.95),
                                  (rng.uniform(6, 94), rng.uniform(22, 96)),
                                  frameon=False, xycoords='data', zorder=4))
                except Exception:
                    continue

    # Nemesis cameo — their most-faced opponent's signature weapon, struck out.
    if nemesis_icon and _Img:
        try:
            ax.add_artist(_AB(_OI(_np.asarray(_Img.open(nemesis_icon).convert('RGBA')),
                          zoom=0.26, alpha=0.85), (84, 90), frameon=False,
                          xycoords='data', zorder=8))
            ax.plot([77, 91], [96, 84], color='#e02b2b', lw=3, alpha=0.9, zorder=9)
            if nemesis_name:
                ax.text(84, 79.5, f'NEMESIS: {nemesis_name}', fontsize=8, color='#e02b2b',
                        ha='center', va='center', weight='bold', zorder=9)
        except Exception:
            pass

    # Museum placard, bottom-left.
    ax.add_patch(plt.Rectangle((3, 3), 66, 15, color=BG, alpha=0.74, zorder=6))
    ax.text(5, 14.2, title, fontsize=17, color=title_c, weight='bold', zorder=7, va='center')
    ax.text(5, 9.6, subtitle, fontsize=10.5, color=FG, zorder=7, va='center')
    ax.text(5, 6.0, signature, fontsize=8.5, color=MUT, style='italic', zorder=7, va='center')

    # Butler signature stamp, bottom-right.
    _stamp = os.path.join(_ASSETS, 'butler.png')
    if _Img and os.path.exists(_stamp):
        try:
            ax.add_artist(_AB(_OI(_np.asarray(_Img.open(_stamp).convert('RGBA')),
                          zoom=0.11, alpha=0.9), (92, 10), frameon=False,
                          xycoords='data', zorder=8))
        except Exception:
            pass

    # Ornate double frame (gold, or cursed-neon).
    for _off, _lw in ((1.4, 2.6), (3.0, 1.0)):
        ax.add_patch(plt.Rectangle((_off, _off), 100 - 2 * _off, 100 - 2 * _off,
                     fill=False, edgecolor=frame_c, linewidth=_lw, alpha=0.85, zorder=10))

    buf = _io.BytesIO()
    fig.savefig(buf, format='png', dpi=120, facecolor=BG, bbox_inches='tight', pad_inches=0.15)
    plt.close(fig)
    return buf.getvalue()


def render_scatter(*, title, subtitle, points, x_label, y_label, r, footer, trend=None,
                   groups=None, group_label=None, colour_map=None) -> bytes:
    """Scatter of per-run (x, y) points with a least-squares trend line and the Pearson r
    annotated (with a plain-language strength/direction). Powers /explore's 'does X track
    with Y' correlation view. BLOCKING: call via render_async."""
    plt, fig = _new_figure((10, 6.8))

    def _y(inches_from_top):
        return 1.0 - (inches_from_top / 6.8)

    fig.subplots_adjust(left=0.10, right=0.955, top=_y(1.15), bottom=0.13)
    fig.text(0.055, _y(0.36), title, color=FG, fontsize=21, fontweight='bold', ha='left', va='center')
    fig.text(0.055, _y(0.66), subtitle, color=MUT, fontsize=12.5, ha='left', va='center')
    fig.add_artist(plt.Line2D([0.055, 0.955], [_y(0.86), _y(0.86)], color=GOLD, linewidth=1.4, alpha=0.55))

    ax = fig.add_subplot(111)
    _style_axis(ax, grid_axis='both')
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    if groups:
        # Colour dots by category. Keep the legend legible: the 8 most common
        # groups get their own colour, everything else folds into a grey "Other".
        _palette = [GOLD, BLUE, CORAL, TEAL, PURPLE, '#e0729b', '#8bd3dd', '#b5e48c', '#f4a259']
        _freq = {}
        for g in groups:
            _freq[g] = _freq.get(g, 0) + 1
        _keep = [g for g, _ in sorted(_freq.items(), key=lambda kv: (-kv[1], str(kv[0])))[:8]]
        _norm = [g if g in _keep else 'Other' for g in groups]
        _order = _keep + (['Other'] if 'Other' in _norm else [])
        _override = dict(_FACTION_COLOUR if group_label == 'Faction' else {})
        if colour_map:
            _override.update(colour_map)
        _cmap = {}
        for i, g in enumerate(_keep):
            if g == '—':
                _cmap[g] = '#8a8f98'          # unknown/blank stays grey
            else:
                _cmap[g] = _override.get(g, _palette[i] if i < len(_palette) else '#8a8f98')
        _cmap['Other'] = '#8a8f98'
        for g in _order:
            _gx = [xs[i] for i in range(len(xs)) if _norm[i] == g]
            _gy = [ys[i] for i in range(len(ys)) if _norm[i] == g]
            if _gx:
                ax.scatter(_gx, _gy, s=42, color=_cmap[g], edgecolor=BG, linewidth=0.6,
                           alpha=0.85, zorder=3, label=str(g))
        _leg = ax.legend(title=group_label, loc='upper left', fontsize=8.5,
                         framealpha=0.0, handletextpad=0.35, borderpad=0.4, labelspacing=0.3)
        if _leg:
            for _tx in _leg.get_texts():
                _tx.set_color(FG)
            if _leg.get_title():
                _leg.get_title().set_color(MUT)
    else:
        ax.scatter(xs, ys, s=44, color=GOLD, edgecolor=BG, linewidth=0.7, alpha=0.85, zorder=3)
    if trend is not None and len(points) >= 2:
        m, b = trend
        x0, x1 = min(xs), max(xs)
        ax.plot([x0, x1], [m * x0 + b, m * x1 + b], color=CORAL, linewidth=2.4, alpha=0.9, zorder=2)
    ax.set_xlabel(x_label, color=MUT, fontsize=11, labelpad=6)
    ax.set_ylabel(y_label, color=MUT, fontsize=11, labelpad=6)

    if r is None:
        _txt = "r = n/a"
    else:
        _mag = abs(r)
        _strength = ('no' if _mag < 0.15 else 'weak' if _mag < 0.40
                     else 'moderate' if _mag < 0.70 else 'strong')
        _dir = '' if _mag < 0.15 else (' positive' if r > 0 else ' negative')
        _txt = f"r = {r:+.2f}   ({_strength}{_dir})"
    ax.text(0.98, 0.97, _txt, transform=ax.transAxes, ha='right', va='top',
            color=FG, fontsize=12.5, fontweight='bold',
            bbox=dict(boxstyle='round,pad=0.45', fc=PANEL, ec='none'))
    fig.text(0.955, _y(0.66), footer, color=MUT, fontsize=8.5, ha='right', va='center')

    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=125, facecolor=BG, bbox_inches='tight')
    plt.close(fig)
    return buf.getvalue()


def render_corr_matrix(*, title, subtitle, matrix, footer) -> bytes:
    """Diverging stats × stats correlation heatmap. `matrix` is the dict from
    stats_engine.correlation_matrix (stats, labels, r, n). Teal = move together,
    coral = pull apart, gold diagonal, grey dot where the sample is too small.
    BLOCKING: call via render_async."""
    import numpy as _np
    from matplotlib.colors import LinearSegmentedColormap as _LSC
    from matplotlib.patches import Rectangle as _Rect
    keys = matrix['stats']
    labels = matrix['labels']
    R = matrix['r']
    n = len(keys)
    arr = _np.full((n, n), _np.nan)
    for i in range(n):
        for j in range(n):
            v = R.get((i, j))
            if v is not None and i != j:
                arr[i, j] = v

    plt, fig = _new_figure((max(7.4, n * 0.92 + 2.4), max(6.6, n * 0.82 + 2.2)))

    def _yt(inches_from_top, H):
        return 1.0 - (inches_from_top / H)
    _H = fig.get_size_inches()[1]
    fig.text(0.045, _yt(0.36, _H), title, color=FG, fontsize=20, fontweight='bold', ha='left', va='center')
    fig.text(0.045, _yt(0.64, _H), subtitle, color=MUT, fontsize=12, ha='left', va='center')

    ax = fig.add_axes([0.20, 0.06, 0.75, 0.70])
    cmap = _LSC.from_list('lounge_div', [CORAL, '#3a3d45', TEAL])
    ax.imshow(arr, cmap=cmap, vmin=-1, vmax=1, aspect='equal', zorder=1)
    for i in range(n):
        for j in range(n):
            v = R.get((i, j))
            if i == j:
                ax.add_patch(_Rect((j - 0.5, i - 0.5), 1, 1, color=GOLD, zorder=2))
                ax.text(j, i, '1', ha='center', va='center', color='#241c08',
                        fontsize=9, fontweight='bold', zorder=3)
            elif v is None:
                ax.text(j, i, '·', ha='center', va='center', color=MUT, fontsize=11, zorder=3)
            else:
                _t = f'{v:+.2f}'.replace('0.', '.')
                ax.text(j, i, _t, ha='center', va='center', color=FG,
                        fontsize=8.6, fontweight='bold', zorder=3)
    ax.set_xticks(range(n))
    ax.set_xticklabels(labels, rotation=38, ha='left', fontsize=8.8, color=MUT)
    ax.xaxis.set_ticks_position('top')
    ax.set_yticks(range(n))
    ax.set_yticklabels(labels, fontsize=8.8, color=MUT)
    ax.tick_params(length=0)
    for _sp in ax.spines.values():
        _sp.set_visible(False)
    ax.set_xticks([x - 0.5 for x in range(1, n)], minor=True)
    ax.set_yticks([y - 0.5 for y in range(1, n)], minor=True)
    ax.grid(which='minor', color=BG, linewidth=2)

    fig.text(0.045, _yt(_H - 0.30, _H),
             '■ teal = move together    ■ coral = pull apart    · = too few runs',
             color=MUT, fontsize=9, ha='left', va='center')
    fig.text(0.955, _yt(_H - 0.30, _H), footer, color=MUT, fontsize=8.5, ha='right', va='center')

    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=125, facecolor=BG, bbox_inches='tight')
    plt.close(fig)
    return buf.getvalue()


def render_group_compare(*, title, subtitle, groups, group_order, stat_keys, stat_labels,
                         footer, colour_map=None) -> bytes:
    """Grouped comparison bars (e.g. 1H vs 2H across stats). Bars are normalised
    per stat (each stat scaled to its own max) so wildly different scales stay
    comparable; the real value is printed at the bar end. `groups` is the dict
    from stats_engine.group_compare. BLOCKING: call via render_async."""
    _palette = [GOLD, BLUE, CORAL, TEAL, PURPLE]
    order = [g for g in group_order if g in groups]
    _cmap = dict(colour_map or {})
    for i, g in enumerate(order):
        _cmap.setdefault(g, _palette[i % len(_palette)])

    S = len(stat_keys)
    G = len(order)
    plt, fig = _new_figure((9.6, max(4.2, S * (G * 0.34 + 0.5) + 1.8)))
    _H = fig.get_size_inches()[1]
    fig.text(0.055, 1.0 - 0.34 / _H, title, color=FG, fontsize=20, fontweight='bold', ha='left', va='center')
    fig.text(0.055, 1.0 - 0.62 / _H, subtitle, color=MUT, fontsize=12, ha='left', va='center')
    fig.add_artist(plt.Line2D([0.055, 0.955], [1.0 - 0.82 / _H, 1.0 - 0.82 / _H],
                              color=GOLD, linewidth=1.4, alpha=0.55))

    ax = fig.add_axes([0.24, 0.09, 0.72, 1.0 - (1.30 / _H) - 0.09])
    _step = G + 0.9
    _centres = []
    _has_neg = False
    for si, k in enumerate(stat_keys):
        vals = [groups[g].get(k) for g in order]
        present = [abs(v) for v in vals if v is not None]
        m = max(present) if present else 1.0
        base = si * _step
        _centres.append(base + (G - 1) / 2.0)
        for gi, g in enumerate(order):
            v = vals[gi]
            if v is None:
                continue
            if v < 0:
                _has_neg = True
            y = base + gi
            nv = v / m if m else 0
            ax.barh(y, nv, height=0.82, color=_cmap[g], zorder=2)
            _ha = 'left' if nv >= 0 else 'right'
            _off = 0.02 if nv >= 0 else -0.02
            _txt = f'{v:g}'
            ax.text(nv + _off, y, _txt, va='center', ha=_ha, color=FG, fontsize=9, zorder=3)
    ax.set_yticks(_centres)
    ax.set_yticklabels(stat_labels, fontsize=9.5, color=FG)
    ax.set_ylim(-0.8, (S - 1) * _step + G - 0.2 + 0.6)
    ax.invert_yaxis()
    ax.set_xlim(-1.28 if _has_neg else -0.02, 1.28)
    ax.set_xticks([])
    if _has_neg:
        ax.axvline(0, color=MUT, linewidth=0.8, alpha=0.5)
    for _sp in ax.spines.values():
        _sp.set_visible(False)
    ax.tick_params(length=0)
    ax.xaxis.grid(False)

    # Legend (group -> colour), top-left of the plot area.
    from matplotlib.patches import Patch as _Patch
    _handles = [_Patch(color=_cmap[g], label=f'{g}  (n={groups[g].get("_n", "?")})') for g in order]
    _leg = ax.legend(handles=_handles, loc='upper right', fontsize=9, framealpha=0.0,
                     handlelength=1.1, borderpad=0.4)
    for _tx in _leg.get_texts():
        _tx.set_color(FG)

    fig.text(0.955, 0.028, footer, color=MUT, fontsize=8.5, ha='right', va='center')
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=125, facecolor=BG, bbox_inches='tight')
    plt.close(fig)
    return buf.getvalue()
