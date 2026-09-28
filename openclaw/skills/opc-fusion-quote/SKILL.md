---
name: opc-fusion-quote
description: 四层融合CNC报价引擎(体积法+工序表法) - 按尺寸/材料/工序/公差自动估算单价与总价, 支持STEP包围盒解析与真实报价校准校准层。需CNC零件报价、快速估价或工艺链建议时使用。
---

# OPC Fusion Quote Engine v2.0

体积法(物理) + 工序表法(精度) 三层融合报价引擎

## 架构
- L1: 体积法自动估算 (包围盒→体积→重量→材料费)
- L2: 形状推测工艺链 (包围盒比例→板/轴/箱体→建议工序)
- L3: 工序法精算 (每道工序×材料系数×尺寸×公差)
- L4: 校准层 (按品类存储校准因子，喂真实报价就准)

## 用法
```bash
# 自动模式（体积法）
python3 scripts/fusion_engine.py -m AL6061 -l 100 -w 50 --height 20 -q 10

# 融合模式（体积+工序）
python3 scripts/fusion_engine.py -m 45钢 -l 200 -w 50 --height 50 -p "车削,铣削,钻孔"

# 校准模式（真实报价校准）
python3 scripts/fusion_engine.py -m 45钢 -l 200 -w 50 --height 50 -p "车削,铣削,钻孔" --calibrate 5800

# JSON输出
python3 scripts/fusion_engine.py -m DC53 -l 260 -w 200 --height 55 --json
```

## 关键参数
- --material/-m: 材料（支持别名如 304, TC4, 45钢）
- --length/-l, --width/-w, --height: 尺寸mm
- --quantity/-q: 数量
- --processes/-p: 工序链，逗号分隔
- --tolerance/-t: 公差等级(IT5-IT12, 自由公差)
- --surface/-s: 表面处理
- --step: STEP文件路径（自动解析包围盒）
- --calibrate: 用真实报价校准
- --category: 品类分类
