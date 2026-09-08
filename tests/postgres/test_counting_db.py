"""Real Postgres tests. TEST_DATABASE_URL must point to a disposable test DB.
Each case owns a random schema and drops only that schema; never use production.
"""
import asyncio
import os
import uuid
from datetime import datetime,timedelta,timezone
import pytest

asyncpg = pytest.importorskip('asyncpg')
import config
import utils.db as db

pytestmark = pytest.mark.skipif(not os.getenv('TEST_DATABASE_URL'),reason='TEST_DATABASE_URL not configured')


async def isolated(case):
    url = os.environ['TEST_DATABASE_URL']
    schema = 'count_test_'+uuid.uuid4().hex
    root = await asyncpg.connect(url)
    old_pool = db._pool
    try:
        await root.execute(f'CREATE SCHEMA {schema}')
        db._pool = await asyncpg.create_pool(url,min_size=1,max_size=5,server_settings={'search_path':schema})
        async with db._pool.acquire() as conn:
            await conn.execute(db._COUNTING_SCHEMA)
            # Existing Butler stats schema, from its real startup definitions.
            for statement in db._SCHEMA_STATEMENTS:
                if statement.startswith(('CREATE TABLE IF NOT EXISTS counting_state (','CREATE TABLE IF NOT EXISTS counting_users (')):
                    await conn.execute(statement)
        await case()
    finally:
        if db._pool is not old_pool:
            await db._pool.close()
        db._pool = old_pool
        await root.execute(f'DROP SCHEMA {schema} CASCADE')
        await root.close()


def test_real_schema_is_idempotent_and_paused_initially():
    async def case():
        async with db._pool.acquire() as conn:
            await conn.execute(db._COUNTING_SCHEMA)
        await db.counting_game_init(1,2)
        await db.counting_game_init(1,2)
        assert (await db.counting_game_status(1))['paused']
        with pytest.raises(ValueError):
            await db.counting_game_init(1,3)
    asyncio.run(isolated(case))


def test_atomic_count_and_legacy_totals_survive_seeding(monkeypatch):
    monkeypatch.setattr(config,'COUNTING_CHANNEL_ID',1)
    async def case():
        await db.counting_save_state(50,'old',200,1000)
        await db.counting_add('10','Player',counts=50)
        await db.counting_game_init(1,2)
        await db.counting_game_seed(1,99,50,11,100)
        imported = await db.counting_game_status(1)
        assert imported['record']==200 and imported['total_counts']==1000
        assert (await db.counting_game_top(1))[0]['counts']==50
        results = await asyncio.gather(*[db.counting_game_attempt(1,101,10,'Player','51',77) for _ in range(2)])
        assert sum(r is not None for r in results)==1
        state = await db.counting_state()
        assert state['current']==51 and state['total_counts']==1001 and state['record']==200
        assert (await db.counting_top())[0]==('Player',51)
        await db.counting_game_seed(1,99,0,None,102)
        assert (await db.counting_state())['total_counts']==1001
    asyncio.run(isolated(case))


def test_test_channel_does_not_touch_live_stats(monkeypatch):
    monkeypatch.setattr(config,'COUNTING_CHANNEL_ID',99)
    async def case():
        await db.counting_game_init(1,2)
        await db.counting_game_seed(1,99,0,None,10)
        await db.counting_game_attempt(1,11,10,'Player','1',77)
        assert (await db.counting_state())['total_counts']==0
        assert await db.counting_top()==[]
    asyncio.run(isolated(case))


def test_spacing_disruption_and_reset_generations():
    async def case():
        await db.counting_game_init(1,2)
        await db.counting_game_seed(1,99,0,None,10)
        assert (await db.counting_game_attempt(1,11,10,'A','1\u200b',77)).kind=='spacing'
        assert await db.counting_penalties_list(2)==[]
        await db.counting_game_attempt(1,12,10,'A','1',77)
        assert await db.counting_game_disrupt(1,[12])==2
        assert await db.counting_game_disrupt(1,[12]) is None
        assert (await db.counting_game_attempt(1,13,11,'B','1',77)).kind=='disruption'
        assert (await db.counting_game_attempt(1,14,11,'B','1',77)).kind=='failed'
        assert await db.counting_game_disrupt(1,[12]) is None
        assert (await db.counting_game_status(1))['current']==0
        penalty=(await db.counting_penalties_list(2))[0]
        remaining=penalty['expires_at']-datetime.now(timezone.utc).replace(tzinfo=None)
        assert timedelta(hours=72,seconds=-5)<remaining<=timedelta(hours=72)
    asyncio.run(isolated(case))


def test_expiry_failure_retries_and_forgive():
    async def case():
        await db.counting_game_init(1,2)
        await db.counting_game_seed(1,99,0,None,10)
        await db.counting_game_attempt(1,11,10,'A','7',77)
        async def fail(penalty,expired):
            raise ValueError('Role hierarchy denied')
        await db.counting_penalty_sweep(2,fail)
        assert (await db.counting_penalties_list(2))[0]['error']=='Role hierarchy denied'
        async def apply(penalty,expired):
            return 'done' if expired else 'active'
        await db.counting_penalty_sweep(2,apply)
        assert (await db.counting_penalties_list(2))[0]['state']=='active'
        await db.counting_penalty_forgive(2,10,99,1)
        await db.counting_penalty_sweep(2,apply)
        assert await db.counting_penalties_list(2)==[]
    asyncio.run(isolated(case))


def test_renewal_waits_for_removal_then_requeues():
    async def case():
        await db.counting_game_init(1,2)
        await db.counting_game_seed(1,99,0,None,10)
        await db.counting_game_attempt(1,11,10,'A','7',77)
        await db.counting_penalty_forgive(2,10,99,1)
        entered,release=asyncio.Event(),asyncio.Event()
        async def slow_removal(penalty,expired):
            assert expired
            entered.set()
            await release.wait()
            return 'done'
        worker=asyncio.create_task(db.counting_penalty_sweep(2,slow_removal))
        await asyncio.wait_for(entered.wait(),2)
        renewal=asyncio.create_task(db.counting_game_attempt(1,12,10,'A','8',77))
        await asyncio.sleep(0.05)
        assert not renewal.done()
        release.set()
        await asyncio.gather(worker,renewal)
        penalty=(await db.counting_penalties_list(2))[0]
        assert penalty['state']=='pending'
        assert penalty['expires_at']>datetime.now(timezone.utc).replace(tzinfo=None)+timedelta(hours=71)
    asyncio.run(isolated(case))


def test_overlapping_role_workers_apply_once():
    async def case():
        await db.counting_game_init(1,2)
        await db.counting_game_seed(1,99,0,None,10)
        await db.counting_game_attempt(1,11,10,'A','7',77)
        calls=[]
        async def apply(penalty,expired):
            calls.append(penalty['discord_id'])
            await asyncio.sleep(0.05)
            return 'active'
        await asyncio.gather(db.counting_penalty_sweep(2,apply),db.counting_penalty_sweep(2,apply))
        assert calls==['10']
    asyncio.run(isolated(case))


def test_math_stats_reset_and_history():
    async def case():
        await db.counting_game_init(1,2)
        await db.counting_game_seed(1,99,0,None,100)
        await db.counting_game_attempt(1,101,10,'A','2-1',77)
        await db.counting_game_attempt(1,102,11,'B','1+1',77)
        await db.counting_game_attempt(1,103,10,'A','1/0',77)
        player,server=await db.counting_user_stats(1,10)
        assert player['successes']==1 and player['mistakes']==0 and player['highest_valid']==1
        assert server['high_score']==2 and server['record_message_id']==102
        assert await db.counting_game_message(1,102)=='1+1'
        before=await db.counting_game_status(1)
        async def remove(desired):
            assert desired is False
            return 'lost'
        await db.counting_member_action(1,10,99,remove,reset=True,reason='test')
        player,server=await db.counting_user_stats(1,10)
        assert player['successes']==0 and player['place'] is None
        assert server['total_counts']==2
        assert await db.counting_game_status(1)==before
        assert (await db.counting_game_latest(1))['expression']=='1+1'
        assert (await db.counting_user_stats(1,11))[0]['successes']==1
    asyncio.run(isolated(case))


def test_bean_threshold_loss_and_role_failure_preserves_reset():
    async def case():
        await db.counting_game_init(1,2)
        async with db._pool.acquire() as conn:
            await conn.execute("INSERT INTO counting_game_users(channel_id,discord_id,name,counts,breaks) VALUES(1,'10','A',49,0)")
        desired_values=[]
        async def callback(desired):
            desired_values.append(desired)
            return None
        await db.counting_member_action(1,10,99,callback)
        async with db._pool.acquire() as conn:
            await conn.execute("UPDATE counting_game_users SET counts=50")
        await db.counting_member_action(1,10,99,callback)
        async with db._pool.acquire() as conn:
            await conn.execute("UPDATE counting_game_users SET counts=197,breaks=3")
        await db.counting_member_action(1,10,99,callback)
        async with db._pool.acquire() as conn:
            await conn.execute("UPDATE counting_game_users SET counts=196,breaks=4")
        await db.counting_member_action(1,10,99,callback)
        assert desired_values==[None,True,True,False]
        async def fail(desired):
            raise ValueError('Discord role failure')
        with pytest.raises(ValueError):
            await db.counting_member_action(1,10,99,fail,reset=True)
        assert (await db.counting_user_stats(1,10))[0]['successes']==196
    asyncio.run(isolated(case))


def test_snapshot_import_preserves_reset_stats_and_penalty_deadline():
    async def case():
        await db.counting_game_init(1,2)
        expiry=(datetime.now(timezone.utc)+timedelta(hours=5)).isoformat()
        snapshot=dict(format='sommelier-counting-v1',guild_id=2,channel_id=1,
            state=dict(current=7,last_user=10,high_score=52,record_message_id=100),total_counts=80,
            players=[dict(user_id=10,successes=50,mistakes=0,highest_valid=7,highest_message_id=101,last_active_id=101,idiot_penalties=0)],
            penalties=[dict(user_id=11,role_id=77,expires_at=expiry)])
        await db.counting_import_sommelier(1,2,snapshot)
        player,server=await db.counting_user_stats(1,10)
        assert player['successes']==50 and server['total_counts']==80 and server['paused']
        penalty=(await db.counting_penalties_list(2))[0]
        assert penalty['expires_at']==datetime.fromisoformat(expiry).replace(tzinfo=None)
        with pytest.raises(ValueError):
            await db.counting_import_sommelier(1,2,snapshot)
    asyncio.run(isolated(case))
