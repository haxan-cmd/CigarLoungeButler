"""Validate snapshot; --apply imports into a fresh, disabled Butler referee."""
import argparse
import asyncio
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import asyncpg
import config
import utils.db as db
import os

async def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('snapshot')
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    snapshot=json.loads(Path(args.snapshot).read_text(encoding='utf-8'))
    if snapshot.get('format')!='sommelier-counting-v1' or snapshot['guild_id']!=config.GUILD_ID or snapshot['channel_id']!=config.COUNTING_GAME_CHANNEL_ID:
        raise SystemExit('Snapshot does not match the configured guild/channel.')
    print(f"Current: {snapshot['state']['current']}; last player: {snapshot['state']['last_user']}; players: {len(snapshot['players'])}; penalties: {len(snapshot['penalties'])}")
    if not args.apply:
        print('Preview only. Use --apply with Butler stopped and DATABASE_URL set to its database.')
        return
    db._pool=await asyncpg.create_pool(os.environ['DATABASE_URL'],min_size=1,max_size=2)
    try:
        async with db._pool.acquire() as conn:
            await conn.execute(db._COUNTING_SCHEMA)
        await db.counting_game_init(config.COUNTING_GAME_CHANNEL_ID,config.GUILD_ID)
        await db.counting_import_sommelier(config.COUNTING_GAME_CHANNEL_ID,config.GUILD_ID,snapshot)
    finally:
        await db._pool.close()
    print('Imported; still paused. Run /count check then seed the displayed current/last player after disabling Sommelier.')

asyncio.run(main())
