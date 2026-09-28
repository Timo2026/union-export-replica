# -*- coding: utf-8 -*-
import os, json, zipfile, uuid, time

def create_bundle(task_id, files, quote_data, metadata, reasoning_chain=None):
    task_id = task_id or uuid.uuid4().hex[:8]
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    exports = os.path.join(root, "data", "exports")
    os.makedirs(exports, exist_ok=True)
    zip_name = "bundle_%s_%s.zip" % (task_id, time.strftime("%Y%m%d%H%M%S"))
    zip_path = os.path.join(exports, zip_name)
    packed = 0  # 实际写入 zip 的文件数（修复缺陷：原返回传入数，含不存在文件）
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("quote.json", json.dumps(quote_data or {}, ensure_ascii=False, indent=2, default=str))
        z.writestr("metadata.json", json.dumps(metadata or {}, ensure_ascii=False, indent=2, default=str))
        if reasoning_chain:
            z.writestr("reasoning_chain.json", json.dumps(reasoning_chain, ensure_ascii=False, indent=2, default=str))
        for f in (files or []):
            if isinstance(f, str):
                p = f
            else:
                p = f.get("path", "")
            if not p:
                continue
            if not os.path.isabs(p):
                p = os.path.join(root, "data", p)
            if os.path.exists(p):
                z.write(p, os.path.basename(p))
                packed += 1
    return {"zip_url": "/api/download/" + zip_name, "zip_file": zip_name,
            "task_id": task_id, "files": packed}
