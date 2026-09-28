#!/usr/bin/env python3
"""
decision_ledger.py - 报价决策审计账本
来源: cat-eatmagic Decision Ledger (SQLite只增不删) + SparkLive audit表
功能: 记录每次报价的完整决策链, 支持回溯查询

表结构: decisions
  - id (自增)
  - timestamp
  - chain (编排链名称)
  - input_hash (STEP文件SHA-256, 用于去重缓存)
  - request_json (材料/表面/公差/数量/来源)
  - model_output (模型原始输出)
  - rule_check (硬规则检查结果)
  - final_quote (9项成本和)
  - status (passed/blocked/warned)
  - version (版本号)
"""
import os
import sys
import json
import hashlib
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional, Any

DB_PATH = os.path.expanduser("~/.openclaw/skills/cnc-risk-guardian/data/decision_ledger.db")

class DecisionLedger:
    """只增不删的决策审计账本"""
    
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()
    
    def _init_db(self):
        """初始化数据库"""
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                chain TEXT,
                input_hash TEXT,
                request_json TEXT,
                model_output TEXT,
                rule_check TEXT,
                final_quote TEXT,
                status TEXT,
                version INTEGER DEFAULT 1,
                notes TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON decisions(timestamp)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_input_hash ON decisions(input_hash)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON decisions(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chain ON decisions(chain)")
        conn.commit()
        conn.close()
    
    def _hash(self, data: Any) -> str:
        """计算SHA-256"""
        if isinstance(data, str):
            return hashlib.sha256(data.encode()).hexdigest()[:16]
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]
    
    def log(self, chain: str, request: dict, model_output: dict, 
            rule_check: dict, final_quote: dict, status: str = "passed",
            notes: str = None) -> int:
        """
        记录一条决策
        返回: record id
        """
        conn = sqlite3.connect(self.db_path)
        input_hash = self._hash(request)
        
        cursor = conn.execute("""
            INSERT INTO decisions (timestamp, chain, input_hash, request_json, 
                                   model_output, rule_check, final_quote, status, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.now().isoformat(),
            chain,
            input_hash,
            json.dumps(request, ensure_ascii=False),
            json.dumps(model_output, ensure_ascii=False),
            json.dumps(rule_check, ensure_ascii=False),
            json.dumps(final_quote, ensure_ascii=False),
            status,
            notes,
        ))
        record_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return record_id
    
    def find_cached(self, request: dict) -> Optional[dict]:
        """
        查找缓存: 同一input_hash+相同参数 -> 返回上次结果
        """
        input_hash = self._hash(request)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("""
            SELECT * FROM decisions WHERE input_hash = ? 
            AND status = 'passed' 
            ORDER BY timestamp DESC LIMIT 1
        """, (input_hash,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                "id": row[0],
                "timestamp": row[1],
                "chain": row[2],
                "input_hash": row[3],
                "request": json.loads(row[4]),
                "model_output": json.loads(row[5]),
                "rule_check": json.loads(row[6]),
                "final_quote": json.loads(row[7]),
                "status": row[8],
                "cached": True,
            }
        return None
    
    def query(self, limit=20, chain=None, status=None, material=None, 
              start_date=None, end_date=None) -> List[dict]:
        """
        查询决策记录
        """
        conn = sqlite3.connect(self.db_path)
        sql = "SELECT * FROM decisions WHERE 1=1"
        params = []
        
        if chain:
            sql += " AND chain = ?"
            params.append(chain)
        if status:
            sql += " AND status = ?"
            params.append(status)
        if start_date:
            sql += " AND timestamp >= ?"
            params.append(start_date)
        if end_date:
            sql += " AND timestamp <= ?"
            params.append(end_date)
        if material:
            sql += " AND request_json LIKE ?"
            params.append(f'%"{material}"%')
        
        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        
        cursor = conn.execute(sql, params)
        rows = cursor.fetchall()
        conn.close()
        
        results = []
        for row in rows:
            results.append({
                "id": row[0],
                "timestamp": row[1],
                "chain": row[2],
                "input_hash": row[3],
                "request": json.loads(row[4]) if row[4] else {},
                "model_output": json.loads(row[5]) if row[5] else {},
                "rule_check": json.loads(row[6]) if row[6] else {},
                "final_quote": json.loads(row[7]) if row[7] else {},
                "status": row[8],
            })
        return results
    
    def stats(self) -> dict:
        """统计信息"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("SELECT COUNT(*) FROM decisions")
        total = cursor.fetchone()[0]
        
        cursor = conn.execute("SELECT status, COUNT(*) FROM decisions GROUP BY status")
        by_status = dict(cursor.fetchall())
        
        cursor = conn.execute("SELECT chain, COUNT(*) FROM decisions GROUP BY chain")
        by_chain = dict(cursor.fetchall())
        
        cursor = conn.execute("SELECT COUNT(DISTINCT input_hash) FROM decisions")
        unique_parts = cursor.fetchone()[0]
        
        conn.close()
        return {
            "total": total,
            "by_status": by_status,
            "by_chain": by_chain,
            "unique_parts": unique_parts,
        }


# === CLI入口 ===
if __name__ == "__main__":
    ledger = DecisionLedger()
    
    # 测试: 插入几条决策记录
    test_records = [
        {
            "chain": "chain_8_cost_optimization",
            "request": {"material": "铝合金6061", "quantity": 100, "surface": "阳极氧化"},
            "model_output": {"unit_price": 45.5, "total": 4550, "confidence": 0.92},
            "rule_check": {"status": "passed", "violations": []},
            "final_quote": {"material_cost": 1200, "machining_cost": 2000, "surface_cost": 800, 
                           "fixture_cost": 200, "total": 4550},
            "status": "passed",
            "notes": "测试记录",
        },
        {
            "chain": "chain_1_customer_quote",
            "request": {"material": "304不锈钢", "quantity": 50, "surface": "镀锌"},
            "model_output": {"unit_price": 68.0, "total": 3400, "confidence": 0.88},
            "rule_check": {"status": "blocked", "violations": ["304不锈钢不能镀锌"]},
            "final_quote": {},
            "status": "blocked",
            "notes": "硬规则拦截: 材料表面处理禁忌",
        },
    ]
    
    print("=== DecisionLedger 测试 ===\n")
    for rec in test_records:
        rid = ledger.log(**rec)
        print(f"✅ 记录 #{rid}: {rec['chain']} / {rec['status']}")
    
    # 查询统计
    stats = ledger.stats()
    print(f"\n=== 统计 ===")
    print(f"总记录: {stats['total']}")
    print(f"唯一零件: {stats['unique_parts']}")
    print(f"按状态: {stats['by_status']}")
    print(f"按链: {stats['by_chain']}")
    
    # 测试缓存命中
    print(f"\n=== 缓存测试 ===")
    cached = ledger.find_cached({"material": "铝合金6061", "quantity": 100, "surface": "阳极氧化"})
    if cached:
        print(f"✅ 缓存命中: #{cached['id']} / {cached['timestamp']}")
    else:
        print("❌ 无缓存")
