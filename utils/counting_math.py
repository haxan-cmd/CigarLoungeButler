"""Bounded arithmetic parser. No eval(), names, functions or attribute access."""
import ast
import re
import unicodedata
from dataclasses import dataclass
from fractions import Fraction

_ALLOWED = re.compile(r'[0-9+\-*/%().^ \t\r\n]+\Z')
_PLAIN = re.compile(r'-?[0-9]+\Z')
_SYMBOLS = str.maketrans({'×':'*','÷':'/','−':'-'})
MAX_LENGTH = 200
MAX_NODES = 64
MAX_BITS = 256
MAX_EXPONENT = 32

@dataclass(frozen=True)
class Number:
    kind: str
    value: int | None = None
    reason: str = ''

def _bounded(value):
    if value.numerator.bit_length()>MAX_BITS or value.denominator.bit_length()>MAX_BITS:
        raise ValueError('Expression is too large. Use simpler arithmetic.')
    return value

def parse_number(content):
    # First decide whether this resembles arithmetic; normal conversation is ignored.
    cleaned = ''.join(c for c in content if unicodedata.category(c) != 'Cf'
                      and c not in '\u034f\ufe0e\ufe0f')
    cleaned = ''.join(' ' if c.isspace() else c for c in cleaned)
    expression = cleaned.translate(_SYMBOLS)
    if not _ALLOWED.fullmatch(expression) or not any(c.isdigit() for c in expression):
        return Number('ignore')
    if cleaned != content:
        return Number('spacing',reason='Invisible spacing detected. Retype the expression using ordinary characters.')
    if expression != expression.strip() and _PLAIN.fullmatch(expression.strip()):
        return Number('spacing',reason='Spacing detected around the number. Retype using digits only.')
    if len(expression)>MAX_LENGTH:
        return Number('invalid_math',reason='Expression is too long. Keep it within 200 characters.')
    expression = expression.strip().replace('^','**')
    try:
        if _PLAIN.fullmatch(expression):
            return Number('number',int(_bounded(Fraction(int(expression)))))
        tree = ast.parse(expression,mode='eval')
        if sum(1 for _ in ast.walk(tree))>MAX_NODES:
            raise ValueError('Expression has too many operations. Use simpler arithmetic.')

        def solve(node):
            if isinstance(node,ast.Constant) and type(node.value) in (int,float):
                return _bounded(Fraction(ast.get_source_segment(expression,node)))
            if isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.UAdd,ast.USub)):
                value=solve(node.operand)
                return value if isinstance(node.op,ast.UAdd) else -value
            if not isinstance(node,ast.BinOp):
                raise ValueError('Use numbers, parentheses and arithmetic operators only.')
            left,right=solve(node.left),solve(node.right)
            if isinstance(node.op,ast.Add):
                result=left+right
            elif isinstance(node.op,ast.Sub):
                result=left-right
            elif isinstance(node.op,ast.Mult):
                result=left*right
            elif isinstance(node.op,ast.Div):
                result=left/right
            elif isinstance(node.op,ast.FloorDiv):
                result=Fraction(left//right)
            elif isinstance(node.op,ast.Mod):
                result=left%right
            elif isinstance(node.op,ast.Pow):
                if right.denominator!=1 or abs(right)>MAX_EXPONENT:
                    raise ValueError('Use an integer exponent between -32 and 32.')
                exponent=int(right)
                if max(left.numerator.bit_length(),left.denominator.bit_length())*abs(exponent)>MAX_BITS:
                    raise ValueError('Power is too large. Use simpler arithmetic.')
                result=left**exponent
            else:
                raise ValueError('Unsupported arithmetic operator.')
            return _bounded(result)

        result=solve(tree.body)
        if result.denominator!=1:
            raise ValueError('The expression must equal a whole number.')
        return Number('number',int(result))
    except ZeroDivisionError:
        return Number('invalid_math',reason='Division by zero. Try another expression.')
    except (SyntaxError,ValueError,TypeError,OverflowError,RecursionError) as exc:
        reason=str(exc) if isinstance(exc,ValueError) else 'Invalid arithmetic. Check the numbers and parentheses.'
        return Number('invalid_math',reason=reason[:160])
