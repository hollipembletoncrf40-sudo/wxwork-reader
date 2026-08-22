#!/usr/bin/env python3
"""
企业微信全量已解密聊天记录导出工具 (包含 102 个会话、2.5 万余条真实对话)
"""

import os
import re
import sqlite3
import json
from datetime import datetime
from collections import defaultdict
from wxwork_reader import decode_content, _safe_dirname

def clean_chat_title(title):
    if not title:
        return "未命名会话"
    t = re.sub(r"^[【\(\{\/]+", "", title).strip()
    return t or "未命名会话"

def main():
    decrypted_dir = "/Users/josephine001/.gemini/antigravity-ide/scratch/wxwork-reader/wxwork_decrypted_user"
    export_dirs = [
        os.path.expanduser("~/Desktop/企业微信全量聊天记录"),
        os.path.expanduser("~/Desktop/企业微信活跃群聊聊天记录"),
    ]

    for d in export_dirs:
        os.makedirs(d, exist_ok=True)

    msg_db = os.path.join(decrypted_dir, "message.db")
    sess_db = os.path.join(decrypted_dir, "session.db")

    if not os.path.exists(msg_db) or not os.path.exists(sess_db):
        print("[!] 未找到解密后的 message.db 或 session.db")
        return 1

    conn_msg = sqlite3.connect(msg_db)
    conn_sess = sqlite3.connect(sess_db)

    # 1. 加载所有联系人
    users = {}
    for row in conn_sess.execute("SELECT RID, name, job, email, mobile, fullpath FROM USER"):
        rid, name, job, email, mobile, fullpath = row
        disp = name or f"用户_{rid}"
        users[rid] = {
            "name": name or f"用户_{rid}",
            "job": job or "",
            "email": email or "",
            "mobile": mobile or "",
            "dept": fullpath or "",
            "display_name": disp,
        }

    print(f"[+] 加载联系人档案: {len(users)} 位")

    # 2. 查询所有会话
    conv_rows = conn_msg.execute(
        "SELECT RID, name, conversationtype, create_time, modify_time FROM CONVERSATION"
    ).fetchall()

    conv_list = []
    total_msgs_all = 0

    for cid, raw_name, ctype, ctime, mtime in conv_rows:
        cnt = conn_msg.execute("SELECT count(*) FROM MESSAGE WHERE conv_id = ?", (cid,)).fetchone()[0]
        if cnt == 0:
            continue

        total_msgs_all += cnt
        name = raw_name
        if not name:
            if cid in users:
                name = users[cid]["name"]
            else:
                name = f"会话_{cid}"

        # 获取消息时间跨度
        min_ts = conn_msg.execute("SELECT min(send_time) FROM MESSAGE WHERE conv_id = ? AND send_time > 1000000000", (cid,)).fetchone()[0]
        max_ts = conn_msg.execute("SELECT max(send_time) FROM MESSAGE WHERE conv_id = ? AND send_time > 1000000000", (cid,)).fetchone()[0]

        conv_list.append({
            "cid": cid,
            "raw_name": name,
            "title": clean_chat_title(name),
            "type": ctype,
            "type_desc": "群聊" if ctype in (1, 2, 3) else ("单聊" if ctype == 0 else "应用/通知"),
            "msg_cnt": cnt,
            "modify_time": mtime or max_ts or 0,
            "min_time_str": datetime.fromtimestamp(min_ts).strftime("%Y-%m-%d %H:%M:%S") if min_ts else "未知",
            "max_time_str": datetime.fromtimestamp(max_ts).strftime("%Y-%m-%d %H:%M:%S") if max_ts else "未知",
        })

    # 按消息数量倒序排列
    conv_list.sort(key=lambda c: c["msg_cnt"], reverse=True)
    print(f"[+] 找到 {len(conv_list)} 个有消息的活跃会话，消息总数: {total_msgs_all:,} 条")

    # 3. 逐个会话导出完整记录
    exported_data = []

    for idx, conv in enumerate(conv_list, 1):
        cid = conv["cid"]
        # 读取该会话的所有消息 (按时间正序)
        msg_rows = conn_msg.execute(
            "SELECT RID, sender_id, send_time, content, message_type FROM MESSAGE "
            "WHERE conv_id = ? ORDER BY send_time ASC, RID ASC",
            (cid,),
        ).fetchall()

        messages = []
        for mid, sender_id, stime, raw_content, mtype in msg_rows:
            sender_info = users.get(sender_id, {})
            sname = sender_info.get("name", f"ID:{sender_id}")
            sjob = sender_info.get("job", "")

            sender_display = f"{sname} ({sjob})" if sjob else sname
            t_str = datetime.fromtimestamp(stime).strftime("%Y-%m-%d %H:%M:%S") if stime and stime > 1000000000 else ""
            txt = decode_content(raw_content)

            if not txt:
                continue

            messages.append({
                "mid": mid,
                "sender_id": sender_id,
                "sender_name": sname,
                "sender_display": sender_display,
                "time_str": t_str,
                "timestamp": stime,
                "content": txt,
            })

        safe_name = _safe_dirname(conv["title"])
        fname = f"{idx:02d}_{safe_name}.md"

        # 生成 Markdown 内容
        md_lines = [
            f"# 💬 {conv['title']}",
            "",
            f"- **会话类型**: `{conv['type_desc']}`",
            f"- **会话 ID**: `{cid}`",
            f"- **总消息数**: **{len(messages):,}** 条",
            f"- **时间跨度**: `{conv['min_time_str']}` 至 `{conv['max_time_str']}`",
            f"- **所属账号**: 邬广武 (嘉立创 · 销售助理 · 18127715604)",
            f"- **导出时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "---",
            "",
            "## 📝 完整历史聊天记录",
            "",
        ]

        current_day = ""
        for m in messages:
            day_str = m["time_str"][:10] if len(m["time_str"]) >= 10 else "历史消息"
            if day_str != current_day:
                current_day = day_str
                md_lines.append(f"### 📅 {current_day}")
                md_lines.append("")

            # 格式化消息体
            sender = m["sender_display"]
            t_clock = m["time_str"][11:] if len(m["time_str"]) >= 19 else m["time_str"]
            content = m["content"]

            content_lines = content.splitlines()
            if len(content_lines) == 1:
                if content.startswith("http://") or content.startswith("https://"):
                    md_lines.append(f"> `[{t_clock}]` **{sender}**: 🔗 [{content}]({content})")
                else:
                    md_lines.append(f"> `[{t_clock}]` **{sender}**: {content}")
            else:
                md_lines.append(f"> `[{t_clock}]` **{sender}**:")
                for cl in content_lines:
                    if cl.strip().startswith("http://") or cl.strip().startswith("https://"):
                        md_lines.append(f"> - 🔗 [{cl.strip()}]({cl.strip()})")
                    else:
                        md_lines.append(f"> {cl}")
            md_lines.append("")

        # 写入所有目标目录
        for d in export_dirs:
            fpath = os.path.join(d, fname)
            with open(fpath, "w", encoding="utf-8") as f:
                f.write("\n".join(md_lines))

        conv["valid_msg_cnt"] = len(messages)
        conv["sample_msgs"] = messages[-3:] if messages else []
        exported_data.append(conv)

    # 4. 生成 Master Index Markdown 文件
    for d in export_dirs:
        index_path = os.path.join(d, "00_企业微信全量聊天记录概览汇总.md")
        idx_lines = [
            "# 🏢 企业微信全量聊天记录概览汇总",
            "",
            f"> **导出时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ",
            "> **当前登录账号**: **邬广武** (WuGuangWu · 嘉立创 · 销售助理 · 18127715604)  ",
            f"> **包含会话总数**: **{len(exported_data)}** 个  ",
            f"> **包含消息总数**: **{total_msgs_all:,}** 条  ",
            f"> **数据来源**: 本地已解密主数据库 `message.db` (25MB) + `session.db` (2.8MB)  ",
            "",
            "---",
            "",
            "## 📋 全部活跃群聊与对话目录索引 (按消息量排序)",
            "",
            "| 序号 | 会话 / 群聊名称 | 类型 | 消息条数 | 时间跨度 | 完整记录文档 |",
            "| :--- | :--- | :--- | :--- | :--- | :--- |",
        ]

        for idx, conv in enumerate(exported_data, 1):
            safe_name = _safe_dirname(conv["title"])
            fname = f"{idx:02d}_{safe_name}.md"
            idx_lines.append(
                f"| {idx} | **{conv['title']}** | `{conv['type_desc']}` | **{conv['valid_msg_cnt']:,}** 条 | {conv['max_time_str']} | [{fname}](./{fname}) |"
            )

        idx_lines.append("")
        idx_lines.append("---")
        idx_lines.append("")
        idx_lines.append("## 🌟 核心业务群聊最近对话速览")
        idx_lines.append("")

        for idx, conv in enumerate(exported_data[:15], 1):
            idx_lines.append(f"### {idx}. {conv['title']} ({conv['valid_msg_cnt']:,} 条消息)")
            idx_lines.append(f"- **类型**: `{conv['type_desc']}` | **最后活跃**: `{conv['max_time_str']}`")
            if conv["sample_msgs"]:
                idx_lines.append("- **最新消息摘录**:")
                for sm in conv["sample_msgs"]:
                    first_l = sm["content"].splitlines()[0] if sm["content"] else ""
                    idx_lines.append(f"  - `[{sm['time_str']}]` **{sm['sender_name']}**: {first_l[:80]}")
            idx_lines.append("")

        with open(index_path, "w", encoding="utf-8") as f:
            f.write("\n".join(idx_lines))

    # 5. 生成交互式 HTML 可视化面板
    html_content = generate_full_html_viewer(exported_data, total_msgs_all)
    for d in export_dirs:
        html_path = os.path.join(d, "index.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)

    print(f"\n🎉 导出大功告成！")
    print(f"   导出目录 1: {export_dirs[0]}")
    print(f"   导出目录 2: {export_dirs[1]}")
    print(f"   共生成 {len(exported_data)} 份完整群聊记录文档，包含 {total_msgs_all:,} 条对话。")


def generate_full_html_viewer(chats, total_msgs):
    cards_html = []
    for idx, c in enumerate(chats, 1):
        safe_name = _safe_dirname(c["title"])
        fname = f"{idx:02d}_{safe_name}.md"

        sample_html = ""
        for sm in c["sample_msgs"]:
            first_l = sm["content"].splitlines()[0] if sm["content"] else ""
            sample_html += f"<div class='msg-item'><span class='msg-time'>[{sm['time_str']}]</span> <span class='msg-sender'>{sm['sender_name']}</span>: {first_l[:90]}</div>"

        cards_html.append(f"""
        <div class="chat-card" id="chat-{idx}">
            <div class="chat-header">
                <span class="chat-idx">#{idx}</span>
                <span class="chat-title">{c['title']}</span>
                <span class="chat-badge">{c['type_desc']}</span>
                <span class="chat-badge count-badge">{c['valid_msg_cnt']:,} 条消息</span>
                <a class="chat-link" href="./{fname}" target="_blank">打开 Markdown 完整文档 ↗</a>
            </div>
            <div class="chat-meta">时间跨度：{c['min_time_str']} 至 {c['max_time_str']}</div>
            <div class="chat-samples">
                <strong>最新对话摘录：</strong>
                {sample_html}
            </div>
        </div>
        """)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>企业微信全量聊天记录汇总与检索</title>
<style>
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: #f0f2f5; font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Segoe UI", Roboto, sans-serif; color: #1f2937; }}
.header {{ background: #0052d9; color: #fff; padding: 22px 28px; position: sticky; top: 0; z-index: 100; box-shadow: 0 2px 10px rgba(0,0,0,.15); }}
.header h1 {{ margin: 0; font-size: 22px; font-weight: 700; }}
.header p {{ margin: 6px 0 0; font-size: 13px; opacity: .9; }}
.stats-bar {{ display: flex; gap: 16px; margin-top: 12px; }}
.stat-pill {{ background: rgba(255,255,255,.15); padding: 4px 12px; border-radius: 20px; font-size: 12px; }}
.container {{ max-width: 1050px; margin: 24px auto; padding: 0 16px; }}
.search-box {{ width: 100%; padding: 12px 16px; font-size: 14px; border: 1px solid #d1d5db; border-radius: 8px; margin-bottom: 20px; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,.05); }}
.chat-card {{ background: #fff; border-radius: 10px; margin-bottom: 16px; padding: 18px 20px; box-shadow: 0 1px 4px rgba(0,0,0,.08); border: 1px solid #e5e7eb; transition: transform .15s ease; }}
.chat-card:hover {{ border-color: #0052d9; transform: translateY(-1px); }}
.chat-header {{ display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }}
.chat-idx {{ background: #0052d9; color: #fff; font-weight: 700; font-size: 12px; padding: 2px 8px; border-radius: 4px; }}
.chat-title {{ font-size: 16px; font-weight: 700; color: #111827; flex: 1; min-width: 200px; }}
.chat-badge {{ background: #e0f2fe; color: #0284c7; font-size: 12px; padding: 2px 8px; border-radius: 4px; font-weight: 500; }}
.count-badge {{ background: #dcfce7; color: #16a34a; font-weight: 700; }}
.chat-link {{ color: #0052d9; text-decoration: none; font-size: 13px; font-weight: 500; margin-left: auto; }}
.chat-link:hover {{ text-decoration: underline; }}
.chat-meta {{ font-size: 12px; color: #6b7280; margin: 8px 0 12px; }}
.chat-samples {{ background: #f8fafc; border-left: 4px solid #3b82f6; padding: 10px 14px; border-radius: 4px; font-size: 13px; line-height: 1.6; color: #334155; }}
.msg-item {{ margin-top: 4px; word-break: break-word; }}
.msg-time {{ color: #9ca3af; font-size: 11px; }}
.msg-sender {{ font-weight: 600; color: #1e293b; }}
</style>
</head>
<body>
<div class="header">
    <h1>🏢 企业微信全量聊天记录总览与检索</h1>
    <p>登录账号：邬广武（嘉立创 · 销售助理）</p>
    <div class="stats-bar">
        <div class="stat-pill">💬 活跃会话: {len(chats)} 个</div>
        <div class="stat-pill">📝 消息总数: {total_msgs:,} 条</div>
        <div class="stat-pill">👥 组织通讯录: 3,530 人</div>
    </div>
</div>
<div class="container">
    <input type="text" id="searchInput" class="search-box" placeholder="🔍 快速搜索群聊名称、关键词..." onkeyup="filterChats()">
    <div id="chatsContainer">
        {''.join(cards_html)}
    </div>
</div>
<script>
function filterChats() {{
    const val = document.getElementById('searchInput').value.toLowerCase();
    const cards = document.querySelectorAll('.chat-card');
    cards.forEach(c => {{
        const text = c.innerText.toLowerCase();
        c.style.display = text.includes(val) ? 'block' : 'none';
    }});
}}
</script>
</body>
</html>"""

if __name__ == "__main__":
    main()
