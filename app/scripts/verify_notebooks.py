"""verify_notebooks.py — 本机无 ipykernel, 直接按序 exec 每个 notebook 的 code cell 验证可运行.

用法: python scripts/verify_notebooks.py
"""
from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_NB = _ROOT / "notebooks"


def run_nb(path: Path) -> bool:
    nbj = json.loads(path.read_text(encoding="utf-8"))
    g = {"__name__": "__nb__"}
    # 让 notebook 内的 ROOT 推断正确: cwd 设为 trunk root
    ok = True
    for i, cell in enumerate(nbj["cells"]):
        if cell["cell_type"] != "code":
            continue
        src = "".join(cell["source"])
        try:
            exec(compile(src, f"{path.name}#cell{i}", "exec"), g)
        except Exception:
            ok = False
            print(f"  [FAIL] {path.name} cell#{i}")
            traceback.print_exc()
            break
    return ok


def main():
    import os
    os.chdir(_ROOT)
    sys.path.insert(0, str(_ROOT))
    nbs = sorted(_NB.glob("*.ipynb"))
    if not nbs:
        print("no notebooks found"); return 1
    allok = True
    for p in nbs:
        print(f"verify {p.name} ...", end=" ")
        ok = run_nb(p)
        print("PASS" if ok else "FAIL")
        allok = allok and ok
    print("=" * 40)
    print("ALL NOTEBOOKS:", "PASS ✅" if allok else "FAIL ❌")
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
