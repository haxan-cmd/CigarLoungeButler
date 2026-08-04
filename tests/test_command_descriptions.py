"""Guard: Discord rejects the ENTIRE command-sync batch (HTTP 400 / 50035) if any
one slash-command description exceeds 100 characters — so a single long description
silently blocks every command update. This static check (no discord import needed)
scans the cog source and fails if any description is over the limit."""
import os
import re
import glob

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_CMD = re.compile(r'app_commands\.command\(name="([^"]+)",\s*description="((?:[^"\\]|\\.)*)"\)')


def test_slash_command_descriptions_within_100_chars():
    offenders = []
    for path in glob.glob(os.path.join(ROOT, "cogs", "*.py")):
        src = open(path, encoding="utf-8").read()
        for m in _CMD.finditer(src):
            name, desc = m.group(1), m.group(2)
            try:
                rendered = bytes(desc, "utf-8").decode("unicode_escape")
            except Exception:
                rendered = desc
            if len(rendered) > 100:
                offenders.append((os.path.basename(path), name, len(rendered)))
    assert not offenders, (
        "Discord caps slash-command descriptions at 100 chars; a single overflow "
        f"breaks the whole command sync (50035): {offenders}")
