"""Temporary bootstrap: assemble full main from split parts (restore after truncate)."""
from pathlib import Path
_p = Path(__file__).resolve().parent
_src = (_p / "_main_p1.txt").read_text(encoding="utf-8") + (_p / "_main_p2.txt").read_text(encoding="utf-8")
# Persist assembled file for next import / human inspection
try:
    (_p / "main_assembled.py").write_text(_src, encoding="utf-8")
except Exception:
    pass
exec(compile(_src, str(_p / "main.py"), "exec"), globals())
