"""Pure tests for utils/aggregates.py — the Butler's server-wide ranking engine.

No cog/discord imports (CI runs pytest+dotenv only). Builds legacy-shape rows by
hand and asserts identity collapse, each metric, gating, weapon param, overrides.
"""
from utils import aggregates as agg


# ── row builders (legacy list-of-strings shape) ──────────────────────────────

def sub(name, did='', weapon='Messer', map_='Coxwell', td=10, kills=5, deaths=1,
        vip='No', feats='', score=1000):
    r = [''] * 27
    r[1] = name
    r[2] = did
    r[3] = weapon
    r[5] = map_
    r[6] = 'Agatha'
    r[7] = str(td)
    r[8] = str(kills)
    r[9] = str(deaths)
    r[10] = vip
    r[11] = feats
    r[24] = str(score)
    return r


def board(name_, player, did='', score=100):
    return [name_, player, did, str(score), 'http://x', '']


def player(did, name, marks=0, k100=None, td200=None, triple=None):
    return [did, name, 'thread', str(marks), '0', '', '', '', k100, td200, triple]


# ── identity ─────────────────────────────────────────────────────────────────

def test_identity_collapses_igns_via_name_map():
    # "Llama" and "Arbiter of Lethality" both map to did 111 -> one person.
    n2i = {'llama': '111', 'arbiter of lethality': '111'}
    players = [player('111', 'Llama')]
    ident = agg.Identity(players, n2i)
    k1, d1 = ident.resolve('Llama', '')
    k2, d2 = ident.resolve('Arbiter of Lethality', '')
    assert k1 == k2 == '111'
    assert d1 == d2 == 'Llama'  # displayed under registry name


def test_identity_override_wins():
    players = [player('833', 'oldname')]
    ident = agg.Identity(players, {}, {'833': 'Massive Σggplant'})
    _, disp = ident.resolve('oldname', '833')
    assert disp == 'Massive Σggplant'


def test_identity_unregistered_stays_distinct():
    ident = agg.Identity([], {}, {})
    k, d = ident.resolve('RandoGuy', '')
    assert k == 'randoguy' and d == 'RandoGuy'


# ── metrics ──────────────────────────────────────────────────────────────────

def data_of(submissions=None, boards=None, players=None):
    return {'submissions': submissions or [], 'boards': boards or [], 'players': players or []}


def test_most_games_collapses_and_counts():
    subs = [sub('Llama', '111'), sub('Arbiter of Lethality', '111'), sub('kc', '222')]
    d = data_of(subs, players=[player('111', 'Llama'), player('222', 'kc')])
    out = agg.context_block('who has the most games logged', d,
                            name_to_id={'llama': '111', 'arbiter of lethality': '111', 'kc': '222'})
    assert 'Llama (2 games)' in out
    assert 'kc (1 games)' in out


def test_excluded_rows_skipped():
    subs = [sub('kc', '222'), sub('kc', '222', feats='Resubmit'), sub('kc', '222', feats='Unlisted')]
    d = data_of(subs, players=[player('222', 'kc')])
    out = agg.context_block('most games logged', d, name_to_id={'kc': '222'})
    assert 'kc (1 games)' in out  # only the clean row counts


def test_most_deaths_sums():
    subs = [sub('A', '1', deaths=3), sub('A', '1', deaths=2), sub('B', '2', deaths=1)]
    d = data_of(subs, players=[player('1', 'A'), player('2', 'B')])
    out = agg.context_block('who dies the most', d, name_to_id={'a': '1', 'b': '2'})
    assert 'A (5 deaths)' in out and 'B (1 deaths)' in out


def test_best_kd_respects_min_games():
    # C has a perfect ratio but only 1 game -> excluded by min_n=5.
    subs = [sub('A', '1', kills=10, deaths=2) for _ in range(5)]
    subs += [sub('C', '3', kills=9, deaths=0)]
    d = data_of(subs, players=[player('1', 'A'), player('3', 'C')])
    out = agg.context_block('best k/d ratio', d, name_to_id={'a': '1', 'c': '3'})
    assert 'A (' in out
    assert 'C (' not in out


def test_map_variety_distinct():
    subs = [sub('A', '1', map_='Coxwell'), sub('A', '1', map_='Coxwell'), sub('A', '1', map_='Bridgetown')]
    d = data_of(subs, players=[player('1', 'A')])
    out = agg.context_block('who has played the most maps', d, name_to_id={'a': '1'})
    assert 'A (2 maps)' in out  # distinct, not 3


def test_most_marks_from_players_table():
    players = [player('1', 'A', marks=50), player('2', 'B', marks=120)]
    d = data_of(players=players)
    out = agg.context_block('who has the most marks', d)
    assert out.index('B (120 marks)') < out.index('A (50 marks)')


def test_weapon_usage_parametric():
    subs = [sub('A', '1', weapon='Messer'), sub('A', '1', weapon='Messer'), sub('B', '2', weapon='Messer'),
            sub('A', '1', weapon='Maul')]
    d = data_of(subs, players=[player('1', 'A'), player('2', 'B')])
    out = agg.context_block('who plays messer the most', d,
                            name_to_id={'a': '1', 'b': '2'}, param_weapon='Messer')
    assert 'Messer — most games logged' in out
    assert 'A (2 games)' in out and 'B (1 games)' in out


def test_weapon_usage_needs_param():
    # Same phrasing without a resolved weapon must NOT fire the parametric spec.
    subs = [sub('A', '1', weapon='Messer')]
    d = data_of(subs, players=[player('1', 'A')])
    out = agg.context_block('who plays the most', d, name_to_id={'a': '1'}, param_weapon=None)
    assert 'most games logged' not in out


# ── feat boards + overrides ──────────────────────────────────────────────────

def test_feat_count_board():
    boards = [board('100 Kills', 'A', '1'), board('100 Kills', 'A', '1'), board('100 Kills', 'B', '2'),
              board('Messer', 'A', '1')]  # non-feat board ignored
    d = data_of(boards=boards, players=[player('1', 'A'), player('2', 'B')])
    out = agg.context_block('who has the most 100 kill games', d, name_to_id={'a': '1', 'b': '2'})
    assert 'Most 100 Kills games' in out
    assert 'A (2 games)' in out and 'B (1 games)' in out


def test_feat_manual_override_wins():
    boards = [board('100 Kills', 'A', '1')]  # auto count = 1
    players = [player('1', 'A', k100=7)]     # manual override = 7 wins
    d = data_of(boards=boards, players=players)
    out = agg.context_block('most 100 kill games', d, name_to_id={'a': '1'})
    assert 'A (7 games)' in out


def test_pacifist_counts_runs_from_submissions_not_board():
    # The Pacifist BOARD keeps one row per player; the real count is qualifying runs
    # (0 kills, <=10 TD). A single board row must not cap everyone at 1.
    subs = [sub('A', '1', kills=0, td=3), sub('A', '1', kills=0, td=8),
            sub('A', '1', kills=5, td=20),          # not pacifist (has kills)
            sub('B', '2', kills=0, td=2)]
    boards = [board('Pacifist', 'A', '1'), board('Pacifist', 'B', '2')]  # one row each
    d = data_of(subs, boards=boards, players=[player('1', 'A'), player('2', 'B')])
    out = agg.context_block('who has the most pacifist runs', d, name_to_id={'a': '1', 'b': '2'})
    assert 'Most Pacifist runs' in out
    assert 'A (2 runs)' in out and 'B (1 runs)' in out


def test_tuff_matches_word_not_stuff():
    boards = [board('TUFF', 'A', '1'), board('TUFF', 'A', '1'), board('TUFF', 'B', '2')]
    d = data_of(boards=boards, players=[player('1', 'A'), player('2', 'B')])
    assert 'A (2 games)' in agg.context_block('most tuff games', d, name_to_id={'a': '1', 'b': '2'})
    assert agg.context_block('who has the most stuff', d, name_to_id={'a': '1', 'b': '2'}) == ''


def test_feat_identity_collapse():
    boards = [board('Flawless', 'Llama', '111'), board('Flawless', 'Arbiter of Lethality', '111')]
    d = data_of(boards=boards, players=[player('111', 'Llama')])
    out = agg.context_block('most flawless games', d,
                            name_to_id={'llama': '111', 'arbiter of lethality': '111'})
    assert 'Llama (2 games)' in out
    assert 'Arbiter' not in out  # collapsed


# ── gating / dispatch ────────────────────────────────────────────────────────

def test_gate_keywords_exclude_parametric():
    ks = agg.gate_keywords()
    assert 'most marks' in ks and 'most 100 kill'.startswith('most 100 kill') and '100 kill' in ks
    assert 'plays' not in ks and 'main' not in ks  # parametric generics stay out of the gate


def test_no_false_fire_on_banter():
    d = data_of([sub('A', '1')], players=[player('1', 'A')])
    assert agg.context_block('you are the most annoying butler', d, name_to_id={'a': '1'}) == ''
    assert agg.match_specs('who has the most stuff') == []


def test_tuff_not_matched_by_stuff():
    # 'tuff' handling lives in personality's block; here just ensure no feat spec
    # keyword accidentally catches 'stuff'.
    assert agg.match_specs('who has the most stuff') == []
