# -*- coding: utf-8 -*-
"""Skill 桥接层 — 将 skill.zip 中的 ClawHub 标准 skill 桥接到本项目。

每个 skill 结构:
    <skill_name>/SKILL.md      # YAML frontmatter: name, description
    <skill_name>/scripts/main.py  # run(request, **kwargs) -> dict

本模块:
  1. 扫描 skill 目录，解析 SKILL.md frontmatter
  2. 动态加载 scripts/main.py 的 run() 函数
  3. 注册到 SkillCaller，统一调度
  4. 提供 RAG 知识注入接口（将 skill 知识索引到 rag_engine）

使用:
    from src.core.skill_bridge import SkillBridge
    sb = SkillBridge()
    sb.scan()                    # 扫描所有 skill
    sb.register_all(skill_caller)  # 注册到 SkillCaller
    result = sb.call("cad-quote", "6061法兰 报价")
"""
import os, sys, json, re, importlib.util
from pathlib import Path
from typing import Dict, Any, List, Optional


def _project_root():
    return Path(__file__).resolve().parent.parent.parent


class SkillMeta:
    """skill 元信息"""
    def __init__(self, name: str, description: str = "", path: str = "",
                 has_run: bool = False):
        self.name = name
        self.description = description
        self.path = path
        self.has_run = has_run

    def to_dict(self) -> Dict:
        return {"name": self.name, "description": self.description[:100],
                "has_run": self.has_run}


class SkillBridge:
    """Skill 桥接器 — 扫描、加载、注册、调用 zip skill"""

    def __init__(self, skill_dir: str = None):
        if skill_dir is None:
            # 默认 skill 目录：环境变量 SKILL_DIR > 项目内 _skill_extract
            skill_dir = os.environ.get(
                "SKILL_DIR",
                str(_project_root() / "_skill_extract"),
            )
        self.skill_dir = skill_dir
        self._skills: Dict[str, SkillMeta] = {}
        self._run_funcs: Dict[str, Any] = {}  # name -> run 函数

    def scan(self) -> List[SkillMeta]:
        """扫描 skill 目录，解析所有 skill 的 SKILL.md frontmatter。"""
        self._skills.clear()
        self._run_funcs.clear()
        if not os.path.isdir(self.skill_dir):
            return []
        for entry in os.listdir(self.skill_dir):
            skill_path = os.path.join(self.skill_dir, entry)
            skill_md = os.path.join(skill_path, "SKILL.md")
            if not os.path.isfile(skill_md):
                continue
            meta = self._parse_skill_md(skill_md, skill_path)
            if meta:
                # 仅检查 main.py 是否存在（不 exec，避免 scan 批量加载超时）
                main_py = os.path.join(skill_path, "scripts", "main.py")
                meta.has_run = os.path.isfile(main_py)
                self._skills[meta.name] = meta
        return list(self._skills.values())

    def _ensure_run_loaded(self, skill_name: str):
        """按需加载某个 skill 的 run() 函数（懒加载，避免 scan 时批量 exec）。"""
        if skill_name in self._run_funcs:
            return self._run_funcs[skill_name]
        meta = self._skills.get(skill_name)
        if not meta:
            return None
        fn = self._load_run(skill_name, meta.path)
        if fn:
            self._run_funcs[skill_name] = fn
        return fn

    def _parse_skill_md(self, path: str, skill_path: str) -> Optional[SkillMeta]:
        """解析 SKILL.md 的 YAML frontmatter（轻量手写解析，不强制依赖 pyyaml）。"""
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except Exception:
            return None
        # 提取 frontmatter --- ... ---
        m = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
        if not m:
            # 无 frontmatter，用目录名
            return SkillMeta(name=os.path.basename(skill_path), path=skill_path)
        fm = m.group(1)
        name = self._extract_yaml_field(fm, "name") or os.path.basename(skill_path)
        desc = self._extract_yaml_field(fm, "description") or ""
        return SkillMeta(name=name, description=desc, path=skill_path)

    @staticmethod
    def _extract_yaml_field(fm: str, field: str) -> Optional[str]:
        """从 frontmatter 文本提取简单标量字段（支持引号包裹）。"""
        m = re.search(rf"^{field}:\s*['\"]?(.*?)['\"]?\s*$", fm, re.MULTILINE)
        return m.group(1).strip() if m else None

    def _load_run(self, skill_name: str, skill_path: str):
        """动态加载 skill 的 scripts/main.py 的 run() 函数。"""
        main_py = os.path.join(skill_path, "scripts", "main.py")
        if not os.path.isfile(main_py):
            return None
        try:
            mod_name = f"_skill_{skill_name.replace('-', '_')}"
            spec = importlib.util.spec_from_file_location(mod_name, main_py)
            if spec is None or spec.loader is None:
                return None
            mod = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = mod
            spec.loader.exec_module(mod)
            run_fn = getattr(mod, "run", None)
            if callable(run_fn):
                return run_fn
        except Exception:
            return None
        return None

    def list_skills(self) -> List[Dict]:
        """列出所有已扫描 skill。"""
        return [s.to_dict() for s in self._skills.values()]

    def list_runnable(self) -> List[str]:
        """列出所有可调用（有 run 函数）的 skill。"""
        return [name for name, m in self._skills.items() if m.has_run]

    def call(self, skill_name: str, request: str = "", **kwargs) -> Dict[str, Any]:
        """直接调用某个 skill 的 run()（懒加载）。"""
        fn = self._ensure_run_loaded(skill_name)
        if fn is None:
            return {"status": "error", "message": f"skill not found or not runnable: {skill_name}"}
        try:
            return fn(request, **kwargs)
        except Exception as e:
            return {"status": "error", "message": str(e), "skill": skill_name}

    def register_all(self, skill_caller, names: List[str] = None) -> int:
        """将可调用 skill 注册到 SkillCaller（懒加载 run 函数）。

        Args:
            skill_caller: SkillCaller 实例
            names: 指定注册的 skill 名列表，None 则注册全部 has_run 的
        """
        count = 0
        targets = names if names is not None else self.list_runnable()
        for name in targets:
            fn = self._ensure_run_loaded(name)
            if fn is None:
                continue
            try:
                skill_caller.register(name, fn, meta={"source": "skill_bridge"})
                count += 1
            except Exception:
                continue
        return count

    def inject_knowledge_to_rag(self, top_n: int = 50) -> int:
        """将 skill 的描述索引到 rag_engine，增强知识检索。返回索引条数。"""
        try:
            from src.data.rag_engine import index_document
        except Exception:
            return 0
        count = 0
        for name, meta in self._skills.items():
            if count >= top_n:
                break
            try:
                index_document(f"skill-{name}", name, meta.description, "skill", ["skill"])
                count += 1
            except Exception:
                continue
        return count

    # ── skill 知识注入 LLM system prompt ──
    # 类别优先级关键词（按重要性排序，越靠前优先级越高）
    _SKILL_PRIORITY_KEYWORDS = (
        "dfm", "manufacturability", "可制造",
        "cnc-milling", "cnc-turning", "cnc-drilling", "cnc-boring",
        "cnc-grinding", "milling", "turning",
        "material", "aluminum", "steel", "stainless", "titanium", "copper",
        "cast-iron", "alloy",
        "tolerance", "gd-t", "gdt",
        "tool", "fixture", "coolant", "speed-feed",
        "surface", "anodizing", "heat-treatment", "electroplating",
        "deformation", "quality", "measurement",
    )

    # 知识摘要原始缓存（避免每次扫描文件系统）
    _knowledge_cache: List[Dict[str, str]] = []
    _knowledge_cache_dir: str = ""

    def _scan_skill_knowledge(self) -> List[Dict[str, str]]:
        """扫描所有 SKILL.md，提取 (name, description, body_summary)。
        结果缓存到类变量，仅当 skill_dir 变化时重新扫描。
        """
        # 缓存命中：skill_dir 未变且已有缓存
        if self._knowledge_cache and self._knowledge_cache_dir == self.skill_dir:
            return self._knowledge_cache

        results: List[Dict[str, str]] = []
        if not os.path.isdir(self.skill_dir):
            SkillBridge._knowledge_cache = results
            SkillBridge._knowledge_cache_dir = self.skill_dir
            return results

        for entry in os.listdir(self.skill_dir):
            skill_path = os.path.join(self.skill_dir, entry)
            skill_md = os.path.join(skill_path, "SKILL.md")
            if not os.path.isfile(skill_md):
                continue
            try:
                with open(skill_md, "r", encoding="utf-8") as f:
                    text = f.read()
            except Exception:
                continue

            # 解析 frontmatter（--- 包裹的 YAML）+ 正文
            name = entry  # 默认用目录名
            description = ""
            body = text
            m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)", text, re.DOTALL)
            if m:
                fm = m.group(1)
                body = m.group(2)
                _n = self._extract_yaml_field(fm, "name")
                _d = self._extract_yaml_field(fm, "description")
                if _n:
                    name = _n
                if _d:
                    description = _d

            # 正文摘要：去除 markdown 标题符号和多余空白，取前 200 字符
            body_clean = re.sub(r"^#+\s*", "", body, flags=re.MULTILINE)
            body_clean = re.sub(r"\s+", " ", body_clean).strip()
            body_summary = body_clean[:200]

            results.append({
                "name": name,
                "description": description.strip() if description else "",
                "body_summary": body_summary,
            })

        # 按类别优先级排序：含优先级关键词的 skill 排前面
        def _priority_key(item: Dict[str, str]) -> int:
            blob = (item["name"] + " " + item["description"]).lower()
            for idx, kw in enumerate(self._SKILL_PRIORITY_KEYWORDS):
                if kw in blob:
                    return idx
            return len(self._SKILL_PRIORITY_KEYWORDS)

        results.sort(key=_priority_key)

        # 写入类级缓存（所有实例共享，因为 skill_dir 通常固定）
        SkillBridge._knowledge_cache = results
        SkillBridge._knowledge_cache_dir = self.skill_dir
        return results

    def get_skill_knowledge_summary(self, max_skills: int = 30,
                                     max_chars_per_skill: int = 200) -> str:
        """扫描 _skill_extract/ 中所有 skill 的 SKILL.md，提取知识摘要。
        返回拼接后的知识文本，用于注入 LLM system prompt。

        - 读取每个 SKILL.md 的 frontmatter description + 正文前 N 字符
        - 按类别优先级排序：DFM > CNC工艺 > 材料 > 其他
        - 限制总长度避免 prompt 过长（上限 8000 字符）

        Returns:
            拼接后的知识文本，形如:
            "\\n\\n## 已注入的专业知识 skill:\\n- **dfm-analysis**: 可制造性分析...\\n..."
            若无 skill 则返回空字符串。
        """
        all_skills = self._scan_skill_knowledge()
        if not all_skills:
            return ""

        # 总字符上限（避免 prompt 过长）
        TOTAL_CHAR_LIMIT = 8000
        header = "\n\n## 已注入的专业知识 skill:\n"
        lines: List[str] = []
        total_len = len(header)

        for item in all_skills[:max_skills]:
            name = item["name"]
            desc = item["description"]
            body_sum = item["body_summary"][:max_chars_per_skill]
            # 组装一行：优先用 description，正文摘要作为补充
            if desc and body_sum and desc != body_sum[:len(desc)]:
                summary = f"{desc} | {body_sum}"
            elif desc:
                summary = desc
            else:
                summary = body_sum
            # 单行截断保护
            summary = summary[:max_chars_per_skill * 2]
            line = f"- **{name}**: {summary}"
            # 检查总长度上限
            if total_len + len(line) + 1 > TOTAL_CHAR_LIMIT:
                break
            lines.append(line)
            total_len += len(line) + 1

        if not lines:
            return ""
        return header + "\n".join(lines)