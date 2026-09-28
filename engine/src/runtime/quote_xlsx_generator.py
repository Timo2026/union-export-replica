# -*- coding: utf-8 -*-
def generate_quote_xlsx(quote_data, path=None):
    # minimal stub: writes a CSV next to exports (kept for /api/reload compatibility)
    import os, json, time
    if path is None:
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        path = os.path.join(root, "data", "exports",
                            "quote_%s.csv" % time.strftime("%Y%m%d%H%M%S"))
    try:
        with open(path, "w", encoding="utf-8-sig") as f:
            f.write("key,value\n")
            for k, v in (quote_data or {}).items():
                f.write("%s,%s\n" % (k, json.dumps(v, ensure_ascii=False)))
    except Exception:
        pass
    return path
