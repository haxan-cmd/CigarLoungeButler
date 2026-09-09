"""Counting rule regression tests, runnable in the existing minimal CI."""
import ast
from pathlib import Path
import pytest
from utils.counting import judge, MAX_COUNT

@pytest.mark.parametrize('content', ['1\u200b','\ufeff1','1\u00a0','1\u034f',' 1','1\u2060','1\ufe0f'])
def test_invisible_spacing_warns_without_advance(content):
    verdict = judge(0,None,10,content)
    assert verdict.kind == 'spacing'
    assert verdict.next_number == 1

def test_alternation_and_wrong_number():
    assert judge(0,None,10,'1').kind == 'accepted'
    assert judge(1,'10',10,'2').kind == 'failed'
    assert judge(1,'10',11,'2').kind == 'accepted'
    assert judge(1,'10',11,'8').next_number == 1
    assert judge(0,None,11,'-1').kind == 'failed'

def test_deleted_number_warning_and_normal_next():
    assert judge(2,'10',11,'2',disruption=True).kind == 'disruption'
    assert judge(2,'10',11,'3',disruption=True).kind == 'accepted'
    assert judge(2,'10',10,'3',disruption=True).kind == 'disruption'

def test_downtime_never_creates_retroactive_failure():
    assert judge(2,'10',11,'8',recovering=True).kind == 'recovery'
    assert judge(2,'10',11,'3',recovering=True).kind == 'accepted'

@pytest.mark.parametrize('content',['hello','１２','', '@everyone'])
def test_non_game_text_ignored(content):
    assert judge(2,'10',11,content).kind == 'ignore'

def test_limit_is_a_warning_not_an_overflow_or_penalty():
    assert judge(MAX_COUNT,'10',11,str(MAX_COUNT+1)).kind == 'limit'

def test_counting_slash_group_descriptions_fit_discord():
    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root/'cogs/counting.py').read_text(encoding='utf-8'))
    descriptions = [k.value.value for node in ast.walk(tree) if isinstance(node,ast.Call)
                    for k in node.keywords if k.arg=='description' and isinstance(k.value,ast.Constant)]
    assert len(descriptions) == 10
    assert all(0<len(d)<=100 for d in descriptions)

def test_disabled_by_default_and_only_one_top_level_group():
    root = Path(__file__).resolve().parents[1]
    text = (root/'config.py').read_text(encoding='utf-8')
    assert "os.getenv('COUNTING_REFEREE_ENABLED', 'false')" in text
    bot = (root/'bot.py').read_text(encoding='utf-8')
    assert 'if config.COUNTING_REFEREE_ENABLED:\n    COGS.append("cogs.counting")' in bot

def test_legacy_tracker_guarded_when_referee_owns_the_channel():
    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root/'cogs/personality.py').read_text(encoding='utf-8'))
    for name in ('_track_count_ruin','_track_count_valid','counting_backfill'):
        fn = next(n for n in ast.walk(tree) if isinstance(n,ast.AsyncFunctionDef) and n.name==name)
        guard = fn.body[0]
        assert isinstance(guard,ast.If)
        assert 'COUNTING_REFEREE_ENABLED' in ast.unparse(guard.test)
        assert 'COUNTING_GAME_CHANNEL_ID == COUNTING_CHANNEL_ID' in ast.unparse(guard.test)


def test_math_and_invalid_math():
    assert judge(4,'10',11,'2+3').kind=='accepted'
    assert judge(6,'10',11,'(2*3)+1').kind=='accepted'
    assert judge(6,'10',11,'1/0').kind=='invalid_math'
    assert judge(6,'10',11,'9'*1000).kind=='invalid_math'
