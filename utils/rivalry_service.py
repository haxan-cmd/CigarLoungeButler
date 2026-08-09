"""Async orchestration for the rivalry features.

Prefers the ACCURATE roster engine (utils.roster — lobby membership read straight
off each scoreboard) whenever any submission has a stored roster, and falls back
to the legacy time-window fingerprint (utils.rivalries) for older data that has
none. Thin I/O wrapper: it fetches submissions + rosters + the name→id map, then
runs the pure engines off the event loop. The two engines return identical shapes,
so callers (wrapped, statscape, /versus, the Butler, superlatives) don't care
which one answered.
"""
import asyncio

import utils.db as _db
from utils import roster as _R
from utils import rivalries as _RV


async def _load(subs=None):
    """(submissions, roster_by_sub, ign_index, name_map). Every fetch is
    best-effort so a missing table can't break a feature — an empty roster/index
    just routes to the legacy engine."""
    if subs is None:
        try:
            subs = await _db.get_all_submissions()
        except Exception:
            subs = []
    try:
        rosters = await _db.get_all_rosters()
    except Exception:
        rosters = {}
    try:
        name_map = await _db.get_name_to_id_map()
    except Exception:
        name_map = {}
    idx = {}
    for nm, did in name_map.items():
        n = _R.normalize_name(nm)
        if len(n) >= 2 and did:
            idx.setdefault(n, str(did))
    return subs, rosters, idx, name_map


def _names_for(key, name_map):
    return [nm for nm, d in name_map.items() if str(d) == str(key)]


async def rivalries_for(target_key, subs=None):
    """Nemesis / ally / foes / allies for one player."""
    subs, rosters, idx, nmap = await _load(subs)
    if _R.has_roster_coverage(subs, rosters):
        tnames = _names_for(target_key, nmap)
        return await asyncio.to_thread(
            _R.compute_rivalries, target_key, tnames, subs, rosters, idx)
    return await asyncio.to_thread(_RV.compute_rivalries, target_key, subs)


async def head_to_head_for(a_key, b_key, subs=None):
    """Pairwise record between two players. Roster engine first; if these two
    never shared a ROSTERED game, fall back to the fingerprint (covers legacy
    games logged before rosters existed)."""
    subs, rosters, idx, nmap = await _load(subs)
    if _R.has_roster_coverage(subs, rosters):
        h = await asyncio.to_thread(
            _R.head_to_head, a_key, _names_for(a_key, nmap),
            b_key, _names_for(b_key, nmap), subs, rosters, idx)
        if h:
            return h
    return await asyncio.to_thread(_RV.head_to_head, a_key, b_key, subs)


async def pair_awards(subs=None):
    """Server-wide bitter-rivals / inseparable pair awards."""
    subs, rosters, idx, _nmap = await _load(subs)
    if _R.has_roster_coverage(subs, rosters):
        return await asyncio.to_thread(
            _R.compute_pair_awards, subs, rosters, idx)
    return await asyncio.to_thread(_RV.compute_pair_awards, subs)
