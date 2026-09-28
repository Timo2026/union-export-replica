#!/usr/bin/env python3
"""
artifact_hash.py - SHA-256工件溯源
为每个报价请求/STEP文件/决策生成不可篡改的哈希指纹
"""
import hashlib, json, time, os

class ArtifactHasher:
    def __init__(self):
        self.ledger = {}  # hash -> metadata
    
    def hash_data(self, data: dict) -> str:
        """为任意数据字典生成SHA-256指纹"""
        serialized = json.dumps(data, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(serialized.encode('utf-8')).hexdigest()
    
    def hash_file(self, filepath: str, chunks: bool = True) -> dict:
        """为文件生成SHA-256指纹 (支持大文件分块)"""
        if not os.path.exists(filepath):
            return {"hash": "", "size": 0, "exists": False}
        
        sha = hashlib.sha256()
        size = os.path.getsize(filepath)
        
        if chunks:
            with open(filepath, 'rb') as f:
                while True:
                    chunk = f.read(65536)  # 64KB chunks
                    if not chunk:
                        break
                    sha.update(chunk)
        else:
            with open(filepath, 'rb') as f:
                sha.update(f.read())
        
        return {
            "hash": sha.hexdigest(),
            "size": size,
            "path": filepath,
            "name": os.path.basename(filepath),
            "exists": True,
        }
    
    def hash_chain(self, inputs: list) -> str:
        """为决策链生成哈希 (多级输入合并)"""
        combined = "||".join(
            json.dumps(i, sort_keys=True) if isinstance(i, dict) else str(i)
            for i in inputs
        )
        return hashlib.sha256(combined.encode('utf-8')).hexdigest()
    
    def prove(self, artifact_hash: str, original_data: dict) -> bool:
        """验证数据完整性: 重新计算哈希并比对"""
        expected = self.hash_data(original_data)
        return expected == artifact_hash
    
    def log(self, artifact_hash: str, metadata: dict) -> None:
        """记录哈希到账本"""
        self.ledger[artifact_hash] = {
            **metadata,
            "_timestamp": time.time(),
        }
    
    def find(self, artifact_hash: str) -> dict:
        """按哈希查找记录"""
        return self.ledger.get(artifact_hash, {})
    
    def get_stats(self) -> dict:
        return {
            "total_hashes": len(self.ledger),
            "unique_files": len(set(v.get("name", "") for v in self.ledger.values())),
        }


# === CLI测试 ===
if __name__ == "__main__":
    hasher = ArtifactHasher()
    
    # 测试1: 数据哈希
    quote_data = {
        "material": "铝合金6061",
        "surface": "阳极氧化",
        "quantity": 100,
        "price": 3250.00,
    }
    h = hasher.hash_data(quote_data)
    print(f"报价数据哈希: {h[:16]}...")
    assert hasher.prove(h, quote_data), "验签失败!"
    print(f"验签: ✅ 通过")
    
    # 测试2: 文件哈希
    test_file = "/media/timo/CE18065718063F49/图纸/20200000387_底座.STEP"
    if os.path.exists(test_file):
        fh = hasher.hash_file(test_file)
        print(f"STEP文件SHA-256: {fh['hash'][:16]}... ({fh['size']/1024:.0f}KB)")
    
    # 测试3: 决策链哈希
    chain_hash = hasher.hash_chain([
        quote_data,
        {"rule_check": {"status": "passed"}},
        {"artifact": "quote_result_v1"},
    ])
    print(f"决策链哈希: {chain_hash[:16]}...")
    print(f"哈希账本: {hasher.get_stats()}")
