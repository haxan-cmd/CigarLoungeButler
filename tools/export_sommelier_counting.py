"""Run against Sommelier's SQLite DB after /count pause; exports counting only."""
import argparse,json,sqlite3
from pathlib import Path
from datetime import datetime,timezone
parser=argparse.ArgumentParser()
parser.add_argument('database')
parser.add_argument('destination')
args=parser.parse_args()
source=Path(args.database).resolve()
destination=Path(args.destination)
if destination.exists():
    raise SystemExit('Destination exists; choose a fresh filename.')
with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as db:
    db.row_factory=sqlite3.Row
    db.execute('BEGIN')
    state=dict(db.execute('SELECT * FROM counting WHERE id=1').fetchone())
    if not state['paused']:
        raise SystemExit('Pause Sommelier with /count pause before exporting.')
    guild=int(db.execute("SELECT value FROM runtime_metadata WHERE key='guild_id'").fetchone()[0])
    snapshot=dict(format='sommelier-counting-v1',guild_id=guild,channel_id=1510068548775579868,
        exported_at=datetime.now(timezone.utc).isoformat(),state=state,
        total_counts=db.execute('SELECT COUNT(*) FROM counted_messages').fetchone()[0],
        players=[dict(r) for r in db.execute('SELECT * FROM count_players')],
        penalties=[dict(r) for r in db.execute("SELECT * FROM timed_roles WHERE state!='done'")])
with destination.open('x',encoding='utf-8') as f:
    json.dump(snapshot,f,indent=2)
print('Exported counting stats and active penalties. No tokens or message content included.')
