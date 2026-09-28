# -*- coding: utf-8 -*-
import sqlite3, os, threading

class HistoryLookup:
    def __init__(self, db_path=None):
        self._lock = threading.Lock()
        if db_path is None:
            root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            db_path = os.path.join(root, "data", "orders.db")
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _conn(self):
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def _init_db(self):
        c = self._conn()
        c.execute("CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY AUTOINCREMENT, customer_name TEXT, part_name TEXT, material TEXT, quantity INTEGER, unit_price REAL, created_at TEXT)")
        c.commit(); c.close()

    def seed_demo_data(self):
        with self._lock:
            c = self._conn()
            n = c.execute("SELECT COUNT(*) AS n FROM orders").fetchone()["n"]
            if n == 0:
                rows = [
                    ("示例客户A", "法兰", "6061", 50, 154.06),
                    ("示例客户B", "轴套", "45钢", 100, 118.0),
                    ("示例客户C", "法兰", "304", 20, 181.25),
                ]
                import time
                for r in rows:
                    c.execute("INSERT INTO orders (customer_name, part_name, material, quantity, unit_price, created_at) VALUES (?,?,?,?,?,?)",
                              (r[0], r[1], r[2], r[3], r[4], time.strftime("%Y-%m-%d")))
            c.commit(); c.close()

    def lookup(self, material=None, customer_name=None, part_name=None, limit=10):
        c = self._conn()
        q = "SELECT * FROM orders WHERE 1=1"
        args = []
        if material:
            q += " AND material=?"; args.append(material)
        if customer_name:
            q += " AND customer_name LIKE ?"; args.append("%" + customer_name + "%")
        if part_name:
            q += " AND part_name LIKE ?"; args.append("%" + part_name + "%")
        q += " ORDER BY id DESC LIMIT ?"; args.append(limit)
        rows = c.execute(q, args).fetchall()
        c.close()
        return [dict(r) for r in rows]
