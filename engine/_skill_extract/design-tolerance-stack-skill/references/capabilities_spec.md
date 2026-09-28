# design-tolerance-stack-skill Capabilities

**能力名称**: query  
**描述**: 知识查询  
**类型**: knowledge

## 参数说明

- `request` (string): 用户请求/关键词
- `limit` (integer, 可选): 返回数量，默认10

## 返回值

```json
{
  "status": "success|error",
  "skill": "design-tolerance-stack-skill",
  "count": 0,
  "results": []
}
```
