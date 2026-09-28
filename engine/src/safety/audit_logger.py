# -*- coding: utf-8 -*-
import sqlite3, os, json, hashlib, threading, time

class AuditLogger:
    def __init__(self, db_path=None):
        self._lock = threading.Lock()
        if db_path is None:
            root = os.path.join(os.path.dirname(__file__), "..", "..")
            db_path = os.path.abspath(os.path.join(root, "data", "audit.db"))
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _conn(self):
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def _init_db(self):
        with self._lock:
            c = self._conn()
            c.execute("CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, event_type TEXT, data TEXT, prev_hash TEXT, hash TEXT, created_at TEXT)")
            c.commit(); c.close()

    def log(self, task_id, event_type, data):
        with self._lock:
            c = self._conn()
            prev = c.execute("SELECT hash FROM audit ORDER BY id DESC LIMIT 1").fetchone()
            prev_hash = prev["hash"] if prev else "GENESIS"
            payload = json.dumps({"task_id": task_id, "event_type": event_type,
                                  "data": data, "prev": prev_hash},
                                 ensure_ascii=False, default=str)
            h = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            c.execute("INSERT INTO audit (task_id, event_type, data, prev_hash, hash, created_at) VALUES (?,?,?,?,?,?)",
                      (task_id, event_type, json.dumps(data, ensure_ascii=False, default=str),
                       prev_hash, h, time.strftime("%Y-%m-%dT%H:%M:%S")))
            c.commit(); c.close()
            return h

    def query(self, task_id=None, limit=20):
        c = self._conn()
        if task_id:
            rows = c.execute("SELECT * FROM audit WHERE task_id=? ORDER BY id DESC LIMIT ?",
                             (task_id, limit)).fetchall()
        else:
            rows = c.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        c.close()
        return [dict(r) for r in rows]

    def count(self):
        c = self._conn()
        n = c.execute("SELECT COUNT(*) AS n FROM audit").fetchone()["n"]
        c.close()
        return n

    def verify_chain(self):
        """验证审计链完整性：prev_hash 连续性 + 每条记录 hash 可重算复现。

        修复缺陷：原实现仅检查 prev_hash 连续性，且 payload 变量计算后未使用（死代码），
        不重新计算 SHA-256 与存储 hash 比对，审计链篡改检测形同虚设。
        现按 log() 的 payload 构造方式重算 hash 并严格比对。
        """
        c = self._conn()
        rows = c.execute("SELECT id, task_id, event_type, data, prev_hash, hash FROM audit ORDER BY id ASC").fetchall()
        c.close()
        prev = "GENESIS"
        for r in rows:
            # 1) 链式连续性：prev_hash 必须等于上一条 hash
            if r["prev_hash"] != prev:
                return False
            # 2) hash 可复现：按 log() 的 payload 构造重算 SHA-256
            payload = json.dumps({"task_id": r["task_id"], "event_type": r["event_type"],
                                  "data": json.loads(r["data"]), "prev": r["prev_hash"]},
                                 ensure_ascii=False, default=str)
            recomputed = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            if recomputed != r["hash"]:
                return False
            prev = r["hash"]
        return True
