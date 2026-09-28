#!/usr/bin/env python3
"""
interaction_matrix.py — 工序间交互效应修正表
==============================================
制造工艺不是纯加法。前后工序相互影响（变形、装夹、应力释放等），
需要乘性修正因子来反映真实成本。
"""

# ── 工序交互效应修正表 ──
# (前工序, 后工序, 原因, 工时修正因子, 夹具费修正因子)
INTERACTION_MATRIX = [
    # 热处理变形系列
    ("淬火",      "磨削",    "热处理变形→余量增加",     1.3,  1.0),
    ("淬火",      "CNC",     "淬火后硬度高→刀具磨损",    1.2,  1.0),
    ("回火",      "磨削",    "回火后应力释放→微量变形",  1.15, 1.0),
    ("渗碳淬火",  "磨削",    "渗碳层变形→磨削量增加",   1.35, 1.0),
    
    # 焊接应力
    ("焊接",      "CNC",     "焊后应力释放→变形",       1.25, 1.0),
    ("焊接",      "钻孔",    "焊后变形→孔位偏移",       1.15, 1.0),
    
    # 线切割后续
    ("线切割",    "CNC",     "线割后需清根/修边",       1.10, 1.0),
    ("线切割",    "磨削",    "线割面粗糙→需磨平",       1.15, 1.0),
    
    # 粗精关系
    ("粗车",      "精车",    "粗车预留余量→精车耗时少", 0.7,  1.0),
    ("粗铣",      "精铣",    "粗铣预留余量",            0.7,  1.0),
    
    # 装夹共享（省钱！）
    ("CNC",       "钻孔",    "同次装夹→省夹具",         1.0,  0.8),
    ("CNC",       "攻牙",    "同次装夹→省夹具",         1.0,  0.8),
    ("车削",      "钻孔",    "同轴装夹→省夹具",         1.0,  0.85),
]

# ── 互斥工序（取贵的，不做两个） ──
MUTUALLY_EXCLUSIVE = [
    ("磨削",     "抛光"),    # 磨削已经够了，不需要再抛光
    ("精磨",     "研磨"),    # 精度重叠
    ("喷砂",     "抛光"),    # 表面处理冲突
]

# ── 表面处理必须在最后的工序 ──
FINAL_ONLY = ["阳极氧化", "发黑", "镀锌", "镀镍", "镀铬", "PVD", "喷漆", "喷塑",
              "钝化", "普痒", "导电氧化", "硬质氧化", "喷油", "粉", "电镀"]


def find_interaction(prev_process: str, next_process: str) -> dict:
    """
    查找两个工序间的交互修正因子。
    返回 {"time_factor": 1.0, "jig_factor": 1.0, "reason": ""}
    """
    for prev_kw, next_kw, reason, time_f, jig_f in INTERACTION_MATRIX:
        if prev_kw in prev_process and next_kw in next_process:
            return {"time_factor": time_f, "jig_factor": jig_f, "reason": reason}
    return {"time_factor": 1.0, "jig_factor": 1.0, "reason": ""}


def check_exclusive(process_a: str, process_b: str) -> str:
    """
    检查两个工序是否互斥。如果互斥，返回'应该保留的那个'；
    如果不互斥，返回空字符串。
    """
    for a_kw, b_kw in MUTUALLY_EXCLUSIVE:
        if a_kw in process_a and b_kw in process_b:
            return b_kw  # 保留后一个（更精的那个）
    return ""


def is_final_only(process: str) -> bool:
    """该工序是否只能在所有机械加工之后做"""
    return any(fo in process for fo in FINAL_ONLY)
