"""tests/test_novastudio.py — T14-T17: NovaStudio 4 工具接入验证 (4 用例).

每个工具 1 用例:
  1. MinerU: health() 返 False (未启动), parse_pdf() 返 None (离线降级)
  2. ragflow: health() 返 False, search() fallback mock KB
  3. OmniVoice: health() 返 False, asr() 返 None
  4. SearXNG: health() 返 False, search() 返 empty + warning

+ 1 用例: 工具文件物理存在 (tools/{mineru,ragflow,omnivoice,searxng})
"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


# ---- 1. MinerU ----
def test_mineru_health_and_offline() -> None:
    """MinerU 未启动时 health() 返 False; parse_pdf 返 None."""
    from services import intake_pdf
    # 未启动服务 → health False
    assert intake_pdf.health(base_url="http://127.0.0.1:1", timeout_s=0.5) is False
    # 不存在的 PDF 文件 → None
    result = intake_pdf.parse_pdf("/nonexistent.pdf", base_url="http://127.0.0.1:1")
    assert result is None


# ---- 2. ragflow fallback ----
def test_ragflow_fallback_to_mock_kb() -> None:
    """ragflow 不可达 → fallback 到 mock KB 返 hits."""
    from services import rag_search
    # 未启动 → 返 mock
    result = rag_search.search("6061 阳极氧化", top_k=3, base_url="http://127.0.0.1:1")
    assert result["mock"] is True
    assert len(result["hits"]) >= 1
    # 至少含一个 KB-6061 案例
    case_ids = [h["case_id"] for h in result["hits"]]
    assert any("6061" in cid for cid in case_ids)


# ---- 3. OmniVoice ----
def test_omnivoice_health_and_asr_offline() -> None:
    """OmniVoice 未启动 → health False; asr 不存在的文件 → None."""
    from services import asr_engine
    assert asr_engine.health(base_url="http://127.0.0.1:1", timeout_s=0.5) is False
    result = asr_engine.asr("/nonexistent.wav", base_url="http://127.0.0.1:1")
    assert result is None


# ---- 4. SearXNG ----
def test_searxng_health_and_search_offline() -> None:
    """SearXNG 未启动 → health False; search 返 empty + warning."""
    from services import web_search
    assert web_search.health(base_url="http://127.0.0.1:1", timeout_s=0.5) is False
    result = web_search.search("6061 aluminum anodizing", num=5, base_url="http://127.0.0.1:1")
    assert result["hits"] == []
    assert "warning" in result


# ---- 5. 工具文件物理存在 ----
# tools/ 是 4 个 NovaStudio 外部工具 (mineru/ragflow/omnivoice/searxng), 共 ~6.4G,
# README 已声明"有意排除, 不随仓库/交付包分发"。故: 目录在场则真校验, 不在场则 skip
# (不造 6.4G 空目录来骗过断言)。
_TOOLS_PRESENT = (ROOT / "tools").is_dir()


@pytest.mark.skipif(not _TOOLS_PRESENT,
                    reason="tools/ 外部工具 (~6.4G) 按 README 有意排除, 未随仓库分发; "
                           "装入后本用例自动生效")
def test_tools_physically_exist() -> None:
    """4 个 NovaStudio 工具已直接复制到 tools/."""
    expected = {
        "tools/mineru": ["README.md", "app_config.json", "docker"],
        "tools/ragflow": ["README_zh.md", "docker"],
        "tools/omnivoice": ["engine"],
        "tools/searxng": ["SearXNG.exe"],
    }
    for tool_dir, files in expected.items():
        p = ROOT / tool_dir
        assert p.exists() and p.is_dir(), f"{tool_dir} 缺失"
        for f in files:
            assert (p / f).exists(), f"{tool_dir}/{f} 缺失"


# ---- 6. 启动脚本存在 ----
def test_start_novastudio_bat_exists() -> None:
    """scripts/start_novastudio.bat 一键启动 4 工具."""
    p = ROOT / "scripts" / "start_novastudio.bat"
    assert p.exists()
    content = p.read_text(encoding="utf-8")
    # 含 4 个工具启动命令
    for tool in ["SearXNG", "OmniVoice", "ragflow", "MinerU"]:
        assert tool in content, f"start_novastudio.bat 缺 {tool} 启动"


# ---- 7. 集成: ragflow mock 与 services/rag.py 一致 ----
def test_ragflow_mock_consistent_with_legacy_rag() -> None:
    """新版 ragflow.search 返 hits 字段名兼容旧 services.rag.search."""
    from services import rag_search
    result = rag_search.search("6061 anodizing", base_url="http://127.0.0.1:1")
    # 旧 RAGEvidence.search 返 {hits, _mock, _source}; 新版同构
    assert "hits" in result
    assert "_mock" in result or "mock" in result
    if result["hits"]:
        h = result["hits"][0]
        assert "case_id" in h or "title" in h
