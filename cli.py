#!/usr/bin/env python
"""mn — MeetNotes 会议纪要 CLI

供本地 Agent / 脚本 / 人三类用户调用，与 Web UI 共享同一数据源。
所有子命令支持 --json 输出机器可读结果。
"""
import argparse
import json
import os
import re
import shutil
import sys
import uuid
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from server import db, pipeline                       # noqa: E402
from server.config import AUDIO_DIR, DATA_DIR, load_all  # noqa: E402

ALLOWED_EXT = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus",
               ".webm", ".wma", ".amr", ".mp4"}


# ---------------- 基础设施 ----------------

def bootstrap():
    load_all()
    db.init(os.path.join(DATA_DIR, "meet.db"))


def die(msg: str, code: int = 1):
    print(f"mn: 错误: {msg}", file=sys.stderr)
    sys.exit(code)


def emit(args, data, human_fn=None):
    """--json 输出结构化 JSON；否则走人类可读渲染"""
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    elif human_fn:
        human_fn(data)
    sys.exit(0)


def progress(msg: str, args):
    if not args.json:
        print(f"[mn] {msg}", file=sys.stderr)


# ---------------- 子命令 ----------------

def cmd_transcribe(args):
    src = os.path.abspath(args.file)
    if not os.path.exists(src):
        die(f"文件不存在: {src}")
    ext = os.path.splitext(src)[1].lower()
    if ext not in ALLOWED_EXT:
        die(f"不支持的音频格式 {ext}，可选: {', '.join(sorted(ALLOWED_EXT))}")

    mid = uuid.uuid4().hex[:12]
    title = (args.title or os.path.splitext(os.path.basename(src))[0])[:80]
    dst = os.path.join(AUDIO_DIR, f"{mid}_orig{ext}")
    shutil.copyfile(src, dst)
    db.create_meeting(mid, title, datetime.now().strftime("%Y-%m-%d %H:%M"))

    steps = [("预处理音频", pipeline._normalize),
             ("语音转写", pipeline._transcribe),
             ("文稿整理", pipeline._polish),
             ("生成摘要", pipeline._summarize)]
    try:
        for name, fn in steps:
            progress(f"{name}…", args)
            fn(mid)
    except Exception as e:
        db.update_meeting(mid, status="failed", error=str(e)[:800])
        die(f"处理失败: {e}")

    m = db.get_meeting(mid)
    summary = db.get_artifact(mid, "summary")
    data = {
        "id": mid, "title": m["title"], "duration": m["duration"],
        "summary": summary["content"] if summary else "",
        "web_url": "http://localhost:8618/#/m/" + mid,
    }
    emit(args, data, lambda d: (
        print(f"✅ 完成: {d['title']}"),
        print(f"   id:      {d['id']}"),
        print(f"   时长:    {d['duration']:.0f} 秒"),
        print(f"   Web查看:  {d['web_url']}"),
        print(),
        print(d["summary"] or "(无摘要)"),
    ))


def _meeting_brief(m):
    return {"id": m["id"], "title": m["title"], "status": m["status"],
            "step": m["step"], "duration": m["duration"], "created_at": m["created_at"],
            "error": m.get("error")}


def cmd_list(args):
    rows = db.list_meetings()
    data = [_meeting_brief(m) for m in rows]
    emit(args, data, lambda d: (
        [print(f"{m['id']}  {m['created_at']}  {m['status']:<10} "
               f"{(str(round(m['duration']))+'s' if m['duration'] else '  -  '):>6}  {m['title']}")
         for m in d],
        print(f"\n共 {len(d)} 场会议") if d else print("（空）"),
    ))


def _transcript_lines(mid):
    segs = db.list_segments(mid)
    from server import audio_utils
    return [f"[{audio_utils.fmt_ts(s['t_start'])}] {s['text']}" for s in segs]


def cmd_show(args):
    m = db.get_meeting(args.id)
    if not m:
        die(f"会议不存在: {args.id}")
    part = args.part
    if part == "summary":
        content = (db.get_artifact(args.id, "summary") or {}).get("content", "")
    elif part == "polished":
        content = (db.get_artifact(args.id, "polished") or {}).get("content", "")
    else:
        content = "\n".join(_transcript_lines(args.id))
    data = {"id": args.id, "title": m["title"], "part": part, "content": content}
    emit(args, data, lambda d: print(d["content"] or "(无内容)"))


def cmd_search(args):
    kw = f"%{args.keyword}%"
    con = db.connect()
    hits = {}
    for row in con.execute(
            "SELECT meeting_id,text FROM segments WHERE text LIKE ?", (kw,)):
        hits.setdefault(row["meeting_id"], {"transcript_hits": 0, "snippets": []})
        hits[row["meeting_id"]]["transcript_hits"] += 1
        if len(hits[row["meeting_id"]]["snippets"]) < 2:
            idx = row["text"].lower().find(args.keyword.lower())
            snippet = row["text"][max(0, idx - 20):idx + 40]
            hits[row["meeting_id"]]["snippets"].append(snippet)
    for row in con.execute(
            "SELECT meeting_id,kind,content FROM artifacts WHERE content LIKE ?", (kw,)):
        hits.setdefault(row["meeting_id"], {"transcript_hits": 0, "snippets": []})
        hits[row["meeting_id"]].setdefault("doc_hits", 0)
        hits[row["meeting_id"]]["doc_hits"] += 1
    for row in con.execute("SELECT id,title FROM meetings WHERE title LIKE ?", (kw,)):
        hits.setdefault(row["id"], {"transcript_hits": 0, "snippets": []})
        hits[row["id"]]["title_match"] = True
    con.close()

    data = []
    for mid, h in hits.items():
        m = db.get_meeting(mid)
        if m:
            data.append({**_meeting_brief(m), **h})
    data.sort(key=lambda x: x["created_at"], reverse=True)
    emit(args, data, lambda d: (
        [print(f"{x['id']}  {x['title']}  (转写命中:{x['transcript_hits']})") for x in d],
        print(f"\n命中 {len(d)} 场会议") if d else print("（无匹配）"),
    ))


def _todos_from_md(md: str):
    out = []
    for m in re.finditer(r"^\s*-\s*\[\s\]\s*\*\*(.+?)\*\*\s*(.*)$", md or "", re.M):
        task, meta = m.group(1).strip(), m.group(2).strip()
        out.append({"task": task, "meta": meta})
    return out


def cmd_todo(args):
    if args.id:
        ids = [args.id]
        arts = {args.id: db.get_artifact(args.id, "summary")}
    else:
        ids = [m["id"] for m in db.list_meetings() if m["status"] == "done"]
        arts = {i: db.get_artifact(i, "summary") for i in ids}
    data = []
    for mid in ids:
        m = db.get_meeting(mid)
        if not m:
            continue
        todos = _todos_from_md((arts[mid] or {}).get("content", ""))
        if todos:
            data.append({"meeting_id": mid, "title": m["title"], "todos": todos})
    total = sum(len(x["todos"]) for x in data)
    emit(args, data, lambda d: (
        [print(f"\n◆ {x['title']} ({x['meeting_id']})") or
         [print(f"   □ {t['task']}" + (f"　[{t['meta']}]" if t['meta'] else "")) for t in x["todos"]]
         for x in d],
        print(f"\n共 {len(d)} 场会议 / {total} 项待办") if d else print("（无待办）"),
    ))


def cmd_export(args):
    m = db.get_meeting(args.id)
    if not m:
        die(f"会议不存在: {args.id}")
    parts = [f"# {m['title']}\n"]
    summary = db.get_artifact(args.id, "summary")
    polished = db.get_artifact(args.id, "polished")
    if summary:
        parts.append("---\n\n" + summary["content"] + "\n")
    if polished:
        parts.append("---\n\n## 会议文稿\n\n" + polished["content"] + "\n")
    content = "\n".join(parts)
    out = os.path.abspath(args.out) if args.out else os.path.abspath(f"{m['title']}.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(content)
    emit(args, {"ok": True, "path": out, "bytes": len(content.encode("utf-8"))},
         lambda d: print(f"✅ 已导出: {d['path']} ({d['bytes']} 字节)"))


def cmd_rename(args):
    m = db.get_meeting(args.id)
    if not m:
        die(f"会议不存在: {args.id}")
    db.update_meeting(args.id, title=args.title[:80])
    emit(args, {"ok": True, "id": args.id, "title": args.title[:80]},
         lambda d: print(f"✅ 已重命名: {d['title']}"))


def cmd_remove(args):
    m = db.get_meeting(args.id)
    if not m:
        die(f"会议不存在: {args.id}")
    if not args.yes and not args.json:
        confirm = input(f"确认删除「{m['title']}」？(y/N) ").strip().lower()
        if confirm not in ("y", "yes"):
            print("已取消")
            sys.exit(0)
    db.delete_meeting(args.id)
    for f in os.listdir(AUDIO_DIR):
        if f.startswith(args.id):
            try:
                os.remove(os.path.join(AUDIO_DIR, f))
            except OSError:
                pass
    emit(args, {"ok": True, "id": args.id}, lambda d: print(f"✅ 已删除 {d['id']}"))


# ---------------- 入口 ----------------

def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="输出机器可读 JSON（供 Agent/脚本解析）")
    p = argparse.ArgumentParser(prog="mn", description="MeetNotes 会议纪要 CLI — 转录/检索/摘要/待办",
                                parents=[common])
    sub = p.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("transcribe", help="转录音频并生成整理稿+摘要", parents=[common])
    t.add_argument("file", help="音频文件路径")
    t.add_argument("--title", help="会议标题（默认取文件名）")
    t.set_defaults(fn=cmd_transcribe)

    p.add_subparser = sub.add_parser("list", help="会议列表", parents=[common])
    p.add_subparser.set_defaults(fn=cmd_list)

    s = sub.add_parser("show", help="查看会议内容", parents=[common])
    s.add_argument("id")
    s.add_argument("--part", choices=["summary", "polished", "transcript"], default="summary")
    s.set_defaults(fn=cmd_show)

    se = sub.add_parser("search", help="全文检索（标题/转写/文稿）", parents=[common])
    se.add_argument("keyword")
    se.set_defaults(fn=cmd_search)

    td = sub.add_parser("todo", help="提取待办（不带 id 则汇总全部已完成会议）", parents=[common])
    td.add_argument("id", nargs="?")
    td.set_defaults(fn=cmd_todo)

    e = sub.add_parser("export", help="导出会议纪要 Markdown", parents=[common])
    e.add_argument("id")
    e.add_argument("--out", help="输出路径（默认当前目录 <标题>.md）")
    e.set_defaults(fn=cmd_export)

    r = sub.add_parser("rename", help="重命名会议", parents=[common])
    r.add_argument("id")
    r.add_argument("title")
    r.set_defaults(fn=cmd_rename)

    rm = sub.add_parser("remove", help="删除会议", parents=[common])
    rm.add_argument("id")
    rm.add_argument("--yes", action="store_true", help="跳过确认")
    rm.set_defaults(fn=cmd_remove)
    return p


def main():
    args = build_parser().parse_args()
    bootstrap()
    try:
        args.fn(args)
    except SystemExit:
        raise
    except Exception as e:
        die(str(e))


if __name__ == "__main__":
    main()
