"""Tests for utils.tierlist — the Butler tier-list scoring engine."""
from utils.tierlist import (_percentiles, compute_butler_scores, assign_tiers,
                            gather_tier_inputs, DEFAULT_WEIGHTS, TIERS)


def _sub(name, did='', td=0, kills=0, vip='No', feats='', tks='', unlisted=False):
    # submissions row layout (positional): 0 ts·1 name·2 did·3 wpn·4 sub·5 map·6 fac·7 td·
    # 8 kills·9 deaths·10 vip·11 feats·12 link ... 20 team_kill_share
    row = ['2026-01-01'] + [''] * 26
    row[1] = name; row[2] = did; row[3] = 'Messer'; row[7] = str(td); row[8] = str(kills)
    row[10] = vip; row[11] = ('Unlisted' if unlisted else feats); row[12] = f"link/{name}/{td}/{kills}"
    row[20] = str(tks)
    return row


def test_gather_tier_inputs_shapes_components():
    subs = [
        _sub('Alice', 'A', td=100, kills=80, tks=30, feats='Uphill'),
        _sub('Alice', 'A', td=120, kills=60, tks=25),
        _sub('Alice', 'A', td=200, kills=90, vip='Yes'),          # VIP: activity yes, skill no
        _sub('Bob', 'B', td=50, kills=10),
        _sub('Ghost', 'G', td=90, kills=90, unlisted=True),       # unlisted -> ignored entirely
    ]
    ld = [['Messer', 'Alice', 'A', '120', 'l', ''],
          ['TUFF', 'Alice', 'A', '30', 'l', ''],
          ['Falmire - Mason', 'Alice', 'A', '120', 'l', '']]
    players = [['A', 'Alice', '', '250'], ['B', 'Bob', '', '40']]
    raw = gather_tier_inputs(subs, ld, players)
    assert raw['A']['runs'] == 3 and raw['A']['valor'] == 1        # VIP counts as a run
    assert raw['A']['lethality'] > 0 and raw['A']['warlord'] > 0   # from non-VIP runs
    assert raw['A']['boards'] == 3 and raw['A']['feats'] == 1      # 1 feat board (TUFF)
    assert raw['A']['mastery'] == 250
    assert 'G' not in raw                                          # unlisted-only -> absent


def test_gather_then_assign_end_to_end():
    subs = ([_sub('Sweat', 'S', td=180, kills=140, tks=40, feats='Brutal') for _ in range(12)]
            + [_sub('Scrub', 'C', td=40, kills=8) for _ in range(12)])
    ld = [['Messer', 'Sweat', 'S', '180', 'l', ''], ['TUFF', 'Sweat', 'S', '60', 'l', '']]
    players = [['S', 'Sweat', '', '300'], ['C', 'Scrub', '', '10']]
    res = assign_tiers(gather_tier_inputs(subs, ld, players), min_runs=10, s_floor=0.0)
    assert TIERS.index(res['S']['tier']) < TIERS.index(res['C']['tier'])  # sweat out-tiers scrub


def test_percentiles_basic_and_ties():
    assert _percentiles([]) == []
    assert _percentiles([5]) == [0.5]
    # ascending -> 0 .. 1
    assert _percentiles([1, 2, 3]) == [0.0, 0.5, 1.0]
    # ties share the average rank
    p = _percentiles([1, 1, 3])
    assert p[0] == p[1] == 0.25 and p[2] == 1.0


def _mk(runs=50, leth=0.5, war=0.5, valor=0.5, boards=0.5, feats=0.5, mastery=0.5):
    return {'runs': runs, 'lethality': leth, 'warlord': war, 'valor': valor,
            'boards': boards, 'feats': feats, 'mastery': mastery}


def test_higher_stats_score_higher():
    raw = {'good': _mk(leth=0.9, war=0.9, valor=0.9, boards=0.9, feats=0.9, mastery=0.9),
           'mid':  _mk(),
           'bad':  _mk(leth=0.1, war=0.1, valor=0.1, boards=0.1, feats=0.1, mastery=0.1)}
    s = compute_butler_scores(raw)
    assert s['good']['score'] > s['mid']['score'] > s['bad']['score']


def test_activity_gate_leaves_low_sample_unranked():
    raw = {'sweat': _mk(runs=5, leth=1.0, war=1.0, boards=1.0),   # under the gate
           'a': _mk(runs=40), 'b': _mk(runs=40, leth=0.2)}
    res = assign_tiers(raw, min_runs=10)
    assert res['sweat']['tier'] is None            # unranked, not dunked on
    assert res['a']['tier'] in TIERS and res['b']['tier'] in TIERS


def test_tiers_are_valid_letters_and_ordered_by_score():
    # 20 players with a clean skill gradient -> best gets a top tier, worst a bottom tier.
    raw = {}
    for i in range(20):
        v = i / 19.0
        raw[f'p{i}'] = _mk(leth=v, war=v, valor=v, boards=v, feats=v, mastery=v)
    res = assign_tiers(raw, min_runs=1, s_floor=0.0)
    order = TIERS.index
    for i in range(19):
        assert order(res[f'p{i}']['tier']) >= order(res[f'p{i+1}']['tier'])  # p0 worst .. p19 best
    assert res['p19']['tier'] == 'S' and res['p0']['tier'] == 'F'
    assert all(res[k]['tier'] in TIERS for k in raw)


def test_s_floor_demotes_weak_field():
    # Two near-identical mediocre players: the "top" one lands in the S band by position
    # but its blended score is ~0.5, under the floor, so it's demoted out of S.
    raw = {'x': _mk(leth=0.5), 'y': _mk(leth=0.4)}
    res = assign_tiers(raw, min_runs=1, s_floor=0.9)
    assert res['x']['tier'] != 'S'   # no S in a weak field


def test_weights_sum_and_components_present():
    assert abs(sum(DEFAULT_WEIGHTS.values()) - 1.0) < 1e-9
    for c in ('lethality', 'warlord', 'valor', 'boards', 'feats', 'mastery'):
        assert c in DEFAULT_WEIGHTS
