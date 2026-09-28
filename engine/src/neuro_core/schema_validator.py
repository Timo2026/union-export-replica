# -*- coding: utf-8 -*-
class SchemaValidator:
    def __init__(self, experts=None):
        self.experts = experts or {}

    def validate(self, name, result):
        """按专家 schema 校验结果字典，缺失的 required 字段补位为 None。

        当前实现最小 required 存在性校验（类型/枚举/取值范围校验为后续扩展点）。
        保持原有返回契约：非 dict 输入返回空字典，其余返回 dict，不破坏调用方。
        """
        if not isinstance(result, dict):
            return {}
        cfg = self.experts.get(name, {}) if isinstance(self.experts, dict) else {}
        schema = cfg.get("schema", {}) if isinstance(cfg, dict) else {}
        required = schema.get("required", []) if isinstance(schema, dict) else []
        if not isinstance(required, list):
            return result
        result = dict(result)
        for key in required:
            if result.get(key) in (None, ""):
                result[key] = None
        return result
