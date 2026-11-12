"""
Buttons and menu items pass Qt's `checked` flag to the method they are connected to (2026-11-12: File > Open a results
folder… crashed -- the flag, False, arrived as the folder). A method connected directly whose first parameter is
optional would take the flag for that parameter; such methods are connected through a lambda instead. This test finds
any that aren't, in the window code. (A first parameter named `_checked` / `checked` is there to receive the flag.)

Run with: python tests/test_gui_signals.py
"""
import _isolation  # noqa: F401,E402 -- first: the user's own data never reaches a test (tests/_isolation.py)
import re
from pathlib import Path

GUI = Path(__file__).resolve().parents[1] / "src" / "parameter_extractor" / "gui"
CONNECTED = re.compile(r"(?:triggered|clicked|toggled)(?:\.connect\(|=)self\.(\w+)\b(?!\()")


def test_no_slot_takes_the_checked_flag_by_mistake():
    found = []
    for f in sorted(GUI.glob("*.py")):
        source = f.read_text()
        for m in CONNECTED.finditer(source):
            name = m.group(1)
            d = re.search(rf"def {name}\(self(?:,\s*(\w+)(?:\s*:\s*[^=,)]+)?\s*=)?", source)
            if d and d.group(1) and d.group(1) not in ("_checked", "checked", "_"):
                line = source[:m.start()].count("\n") + 1
                found.append(f"{f.name}:{line} {name}({d.group(1)}=...)")
    assert not found, "connect these through a lambda (the checked flag would arrive as the first argument):\n" + \
        "\n".join(found)


if __name__ == "__main__":
    test_no_slot_takes_the_checked_flag_by_mistake()
    print("PASS: test_no_slot_takes_the_checked_flag_by_mistake")
