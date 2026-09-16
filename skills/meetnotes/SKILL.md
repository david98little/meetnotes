---
name: meetnotes
description: 会议纪要 CLI（mn）— 转录音频生成整理稿/摘要/待办，全文检索与导出。当用户提到会议、录音、转录、纪要、摘要、待办提取、会议检索、导出纪要，或给出音频文件要处理时使用。
---

# MeetNotes 会议纪要（mn 命令）

本地会议纪要系统，与 Web UI（默认 http://localhost:8618）共享同一数据源。核心能力：音频转录 → 文稿整理 → 结构化摘要与待办。

## 命令一览

所有命令支持 `--json` 输出机器可读 JSON（解析时务必使用）。若直接调用 `mn` 报找不到命令，用 `cmd /c mn ...`。

| 命令 | 用途 |
|---|---|
| `mn transcribe <音频文件> [--title 标题]` | 转录并生成全套纪要（阻塞式，长音频需数分钟，进度在 stderr） |
| `mn list [--json]` | 会议列表（id/标题/状态/时长） |
| `mn show <id> [--part summary\|polished\|transcript]` | 查看摘要（默认）/整理稿/原始转写 |
| `mn search <关键词> [--json]` | 全文检索标题/转写/文稿，返回命中会议与片段 |
| `mn todo [id] [--json]` | 提取待办；不带 id 汇总全部已完成会议 |
| `mn export <id> [--out 路径.md]` | 导出 Markdown（摘要+文稿合一） |
| `mn rename <id> <新标题>` | 重命名 |
| `mn remove <id> [--yes]` | 删除会议及其音频 |

## 典型任务

**转录一段录音：**
```
mn transcribe /path/to/meeting.mp3 --title "项目周例会"
```
成功后输出 id 和摘要预览；用 `mn show <id> --part polished` 可取整理稿全文。

**跨会议汇总待办：**
```
mn todo --json
```
返回全部已完成会议的待办清单（task + meta 含负责人/截止），适合汇总成周报或写入任务系统。

**找内容：**
```
mn search 关键词 --json
```
返回命中会议列表与上下文片段，再用 `mn show <id>` 深入。

## 注意事项

- 支持格式：mp3/wav/m4a/aac/flac/ogg/opus/webm/wma/amr/mp4
- `transcribe` 是同步阻塞命令：15 分钟音频约 1~2 分钟，不要设过短超时
- 未启动 Web 服务时 CLI 独立可用（共享项目 `data/` 目录）
- Agent 生成的内容若需人工核对，引导用户在 Web 界面上听录音核对
