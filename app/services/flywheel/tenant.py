"""flywheel.tenant — 双层沙箱 tenant 解析.

决策锁定 (2026-09-19): 双层都支持
  - 默认: tenant = customer_id (最细粒度, 客户间绝对隔离)
  - 集团: tenant = group_id (集团内子公司共享记忆)

隔离规则:
  - tenant_id 是所有私有查询的强制过滤键
  - 公共 KB (工艺/材料/汇率) 不分租户, 全局共享
  - 跨租户聚合只在匿名脱敏后写入 analytics 表
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

# 公共 KB 前缀: 不分租户的全局知识
PUBLIC_PREFIXES = ("kb_process", "kb_market", "kb_material")


class TenantScope:
    """租户作用域 — 封装 tenant_id + 是否集团模式."""

    __slots__ = ("tenant_id", "customer_id", "group_id", "is_group")

    def __init__(self, tenant_id: str, customer_id: Optional[str] = None,
                 group_id: Optional[str] = None):
        self.tenant_id = tenant_id
        self.customer_id = customer_id
        self.group_id = group_id
        self.is_group = group_id is not None

    def collection_for(self, kind: str) -> str:
        """租户私有向量集合名. kind ∈ {quotes, reactions, postmortems}."""
        return f"tenant_{self.tenant_id}_{kind}"

    def is_public(self, collection: str) -> bool:
        """是否公共 KB 集合 (不分租户)."""
        return any(collection.startswith(p) for p in PUBLIC_PREFIXES)

    def __repr__(self) -> str:
        mode = "group" if self.is_group else "single"
        return f"TenantScope({self.tenant_id}, {mode})"


def resolve_tenant(ctx_or_customer: Dict[str, Any],
                   customer_store: Optional[Any] = None) -> TenantScope:
    """从 Context 或 customer dict 解析租户作用域.

    优先级:
      1. ctx["customer"]["group_id"] 存在 → 集团模式, tenant = group_id
      2. 否则 → 单客户模式, tenant = customer_id
      3. customer_id 缺失 → 生成确定性匿名 tenant (基于 name/email hash)

    Args:
        ctx_or_customer: Context dict (含 "customer" 键) 或 customer dict
        customer_store: 可选, 用于查 group_id (若 ctx 不直接带)
    """
    cust = ctx_or_customer.get("customer", ctx_or_customer) if isinstance(ctx_or_customer, dict) else {}
    cust = cust or {}

    # 1. 集团模式: 显式 group_id
    group_id = cust.get("group_id")
    if group_id:
        return TenantScope(tenant_id=str(group_id),
                           customer_id=cust.get("customer_id"),
                           group_id=str(group_id))

    # 2. 单客户模式: customer_id
    cid = cust.get("customer_id")
    if not cid:
        # 3. 匿名: 基于 name/email 确定性 hash
        seed = cust.get("name") or cust.get("email") or "anonymous"
        cid = f"ANON-{hashlib.md5(seed.encode('utf-8')).hexdigest()[:8]}"
        log.debug("[tenant] 匿名租户: %s (seed=%r)", cid, seed)

    # 可选: 从 customer_store 补查 group_id
    if customer_store is not None and cid:
        try:
            row = customer_store.load_customer(cid)
            if row and row.get("group_id"):
                return TenantScope(tenant_id=str(row["group_id"]),
                                   customer_id=cid,
                                   group_id=str(row["group_id"]))
        except Exception as e:
            log.debug("[tenant] customer_store 查 group_id 失败: %r", e)

    return TenantScope(tenant_id=str(cid), customer_id=cid)
