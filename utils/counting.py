"""Pure counting rules. No Discord, database or AI imports."""
from dataclasses import dataclass
from utils.counting_math import parse_number

MAX_COUNT = 2_000_000_000  # compatible with Butler's existing INT statistics

@dataclass(frozen=True)
class Verdict:
    kind: str
    next_number: int
    reason: str = ''

def judge(current, last_user, user_id, content, disruption=False, recovering=False):
    """Warnings do not advance the number or change the last successful player."""
    expected = current + 1
    parsed = parse_number(content)
    if parsed.kind != 'number':
        return Verdict(parsed.kind,expected,parsed.reason)
    if current >= MAX_COUNT:
        return Verdict('limit', expected, 'Count limit reached. A moderator must seed a new game.')
    correct = parsed.value == expected and str(user_id) != str(last_user)
    if correct:
        return Verdict('accepted', expected + 1)
    if recovering:
        return Verdict('recovery', expected, 'Downtime attempt skipped without a reset or penalty.')
    if disruption:
        return Verdict('disruption', expected, 'A counted message was deleted or edited. Warning only, no reset.')
    reason = 'Consecutive turn' if str(user_id) == str(last_user) else 'Wrong number'
    return Verdict('failed', 1, reason)
