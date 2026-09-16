PROMPT_POLISH = """你是专业的会议记录员。下面是一段会议录音的原始转写稿，每行以 [MM:SS] 时间戳开头。
请整理成书面化会议文档，要求：
1. 修正明显的语音识别错别字（对照下方术语/专名表）
2. 去除口头语、无意义的重复
3. 按讨论主题重新组织，用 Markdown 的 ## 小标题分节
4. 每个主题小节标题后保留该节起始时间戳，格式保持 [MM:SS]
5. 忠实于原意，不编造内容；听不清/不确定的地方以 (?) 标注
只输出 Markdown 文档本身，不要解释。

{hint}
原始转写稿：
{transcript}
"""

PROMPT_SUMMARY = """你是会议纪要助手。请基于以下会议文稿生成结构化摘要，
严格输出如下 JSON（不要输出其他任何内容）：
{{
  "overview": "一句话概括本次会议",
  "key_points": ["讨论要点1", "要点2"],
  "decisions": ["达成的决议1", "决议2"],
  "todos": [{{"task":"待办事项","owner":"负责人，无法判断填空字符串","due":"截止时间，如 2026-09-01 或 周五"}}]
}}

{hint}
会议文稿：
{doc}
"""

SUMMARY_FALLBACK_MD = """## 会议摘要

> 结构化解析失败，以下为模型原始输出：

{raw}
"""


def summary_json_to_md(data: dict) -> str:
    lines = [f"## 会议摘要", "", data.get("overview", ""), ""]
    pts = data.get("key_points") or []
    if pts:
        lines += ["### 讨论要点", *[f"- {p}" for p in pts], ""]
    dec = data.get("decisions") or []
    if dec:
        lines += ["### 决议", *[f"- ✅ {p}" for p in dec], ""]
    todos = data.get("todos") or []
    if todos:
        lines += ["### 待办事项"]
        for t in todos:
            owner = t.get("owner") or ""
            due = t.get("due") or ""
            meta = " ".join(x for x in (f"@{owner}" if owner else "", due) if x)
            lines.append(f"- [ ] **{t.get('task','')}**" + (f"　{meta}" if meta else ""))
        lines.append("")
    if not pts and not dec and not todos and not data.get("overview"):
        return None
    return "\n".join(lines)
