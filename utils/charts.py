"""utils/charts.py — themed matplotlib rendering for player-facing visuals.

One place for the lounge's look (dark slate + gold), so every command that grows
a chart matches instead of each reinventing colours. Renders are BLOCKING, so
callers must go through render_async (which offloads to a thread) — matplotlib on
the event loop would stall the whole bot.

Palette lifted from /lounge_graphs so the two never drift.
"""
import asyncio
import io

# Lounge theme.
BG = '#2b2d31'
PANEL = '#232428'
FG = '#dcddde'
MUT = '#8e9297'
GRID = '#3f4147'
GOLD = '#e0a84c'
CORAL = '#d85a30'
BLUE = '#5b8dd9'
PURPLE = '#7a89c2'
TEAL = '#4fb3a1'

# Ordered accent cycle for categorical bars.
ACCENTS = [GOLD, CORAL, BLUE, TEAL, PURPLE]


def _new_figure(figsize):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig = plt.figure(figsize=figsize)
    fig.patch.set_facecolor(BG)
    return plt, fig


def _style_axis(ax, *, grid_axis='y'):
    ax.set_facecolor(BG)
    for s in ax.spines.values():
        s.set_color(GRID)
    ax.tick_params(colors=MUT, labelsize=9)
    if grid_axis in ('x', 'both'):
        ax.xaxis.grid(True, color=GRID, linewidth=0.7)
    if grid_axis in ('y', 'both'):
        ax.yaxis.grid(True, color=GRID, linewidth=0.7)
    ax.set_axisbelow(True)


async def render_async(fn, *args, **kwargs) -> bytes:
    """Run a blocking render function in a thread and return PNG bytes."""
    return await asyncio.to_thread(fn, *args, **kwargs)


def render_activity_dashboard(*, title, subtitle, series_labels, series_counts,
                              top_players, top_weapons, footer) -> bytes:
    """Activity over a window.

    series_labels/series_counts: x tick labels + submission counts per bucket.
    top_players/top_weapons:     [(label, count), ...] already sorted desc.
    Returns PNG bytes. BLOCKING — call via render_async.
    """
    plt, fig = _new_figure((11, 8.5))
    gs = fig.add_gridspec(2, 2, height_ratios=[1.15, 1.0],
                          hspace=0.42, wspace=0.22,
                          left=0.08, right=0.96, top=0.86, bottom=0.09)

    fig.text(0.08, 0.955, title, color=FG, fontsize=20, fontweight='bold', ha='left')
    fig.text(0.08, 0.915, subtitle, color=MUT, fontsize=12, ha='left')

    # ── Top: submissions over time (full width) ──────────────────────────────
    ax1 = fig.add_subplot(gs[0, :])
    _style_axis(ax1, grid_axis='y')
    xs = range(len(series_counts))
    ax1.fill_between(xs, series_counts, color=GOLD, alpha=0.18, zorder=1)
    ax1.plot(xs, series_counts, color=GOLD, linewidth=2.4, zorder=2)
    ax1.plot(xs, series_counts, 'o', color=GOLD, markersize=4, zorder=3)
    ax1.set_xticks(list(xs))
    ax1.set_xticklabels(series_labels, rotation=0, fontsize=8, color=MUT)
    ax1.set_ylim(bottom=0)
    ax1.margins(x=0.02)
    ax1.set_title('Submissions over time', color=FG, fontsize=13, pad=10, loc='left')
    _peak = max(series_counts) if series_counts else 0
    if _peak:
        _pi = series_counts.index(_peak)
        ax1.annotate(f'{_peak}', (_pi, _peak), textcoords='offset points',
                     xytext=(0, 7), ha='center', color=GOLD, fontsize=10, fontweight='bold')

    # ── Bottom-left: top players ─────────────────────────────────────────────
    ax2 = fig.add_subplot(gs[1, 0])
    _style_axis(ax2, grid_axis='x')
    _draw_hbar(ax2, top_players, 'Most active players')

    # ── Bottom-right: top weapons ────────────────────────────────────────────
    ax3 = fig.add_subplot(gs[1, 1])
    _style_axis(ax3, grid_axis='x')
    _draw_hbar(ax3, top_weapons, 'Top weapons')

    fig.text(0.96, 0.02, footer, color=MUT, fontsize=8, ha='right')

    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=120, facecolor=BG, bbox_inches='tight')
    plt.close(fig)
    return buf.getvalue()


def render_breakdown(*, title, subtitle, pairs, value_label, footer,
                     value_fmt=None, samples=None) -> bytes:
    """A single horizontal-bar breakdown.

    pairs:     [(label, value), ...] sorted desc.
    value_fmt: callable(value)->str for the bar end label (default int).
    samples:   optional [n, ...] parallel to pairs; shown as "(n)" after the
               value, so a rate metric's sample size is visible.
    Returns PNG bytes. BLOCKING.
    """
    _n = max(1, len(pairs))
    plt, fig = _new_figure((10, 2.2 + _n * 0.46))
    fig.subplots_adjust(left=0.30, right=0.94, top=0.82, bottom=0.10)

    fig.text(0.055, 0.945, title, color=FG, fontsize=19, fontweight='bold', ha='left')
    fig.text(0.055, 0.895, subtitle, color=MUT, fontsize=12, ha='left')

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
        y = range(len(vals))
        ax.barh(list(y), vals, color=colours, height=0.62)
        ax.set_yticks(list(y))
        ax.set_yticklabels(labels, color=FG, fontsize=9)
        _mx = max(vals) or 1
        for i, v in enumerate(vals):
            _txt = _fmt(v) + (f"  ({_samp[i]})" if _samp[i] is not None else "")
            ax.text(v + _mx * 0.02, i, _txt, color=MUT, fontsize=9, va='center')
        ax.set_xlim(right=_mx * 1.18)
    ax.set_xlabel(value_label, color=MUT, fontsize=10)

    fig.text(0.94, 0.02, footer, color=MUT, fontsize=8, ha='right')
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=120, facecolor=BG, bbox_inches='tight')
    plt.close(fig)
    return buf.getvalue()


def _draw_hbar(ax, pairs, title):
    if not pairs:
        ax.text(0.5, 0.5, 'no data', color=MUT, fontsize=11, ha='center', va='center')
        ax.set_xticks([]); ax.set_yticks([])
        ax.set_title(title, color=FG, fontsize=13, pad=10, loc='left')
        return
    labels = [p[0] for p in pairs][::-1]        # matplotlib barh stacks bottom-up
    vals = [p[1] for p in pairs][::-1]
    colours = [ACCENTS[i % len(ACCENTS)] for i in range(len(vals))][::-1]
    y = range(len(vals))
    ax.barh(list(y), vals, color=colours, height=0.62)
    ax.set_yticks(list(y))
    ax.set_yticklabels(labels, color=FG, fontsize=9)
    ax.set_title(title, color=FG, fontsize=13, pad=10, loc='left')
    _mx = max(vals)
    for i, v in enumerate(vals):
        ax.text(v + _mx * 0.02, i, str(v), color=MUT, fontsize=9, va='center')
    ax.set_xlim(right=_mx * 1.14)
