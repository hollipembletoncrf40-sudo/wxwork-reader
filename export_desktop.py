#!/usr/bin/env python3
"""
导出当前运行的企业微信活跃群聊记录到桌面文件夹 (深度净化版)
"""

import os
import re
import struct
import json
from datetime import datetime
from wxwork_reader import decode_content, _safe_dirname

def read_varint(b, p):
    val, shift = 0, 0
    while p < len(b) and shift < 64:
        byte = b[p]
        p += 1
        val |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            return val, p
        shift += 7
    return None, p

def parse_all_subfields(b):
    fields = {}
    p = 0
    while p < len(b):
        tag, p = read_varint(b, p)
        if tag is None or tag == 0:
            break
        wire = tag & 7
        fn = tag >> 3
        if wire == 0:
            val, p = read_varint(b, p)
            fields.setdefault(fn, []).append(("int", val))
        elif wire == 1:
            p += 8
        elif wire == 5:
            p += 4
        elif wire == 2:
            length, p = read_varint(b, p)
            if length is None or p + length > len(b):
                break
            sbytes = b[p : p + length]
            p += length
            fields.setdefault(fn, []).append(("bytes", sbytes))
        else:
            break
    return fields

def is_meaningful_text(line):
    if not line:
        return False
    line = line.strip()
    if line.startswith("CIGABB") or line.startswith("wework_") or line.startswith("wwt_"):
        return False
    if re.fullmatch(r"[0-9a-fA-F]{16,}", line) or re.fullmatch(r"[0-9a-zA-Z_-]{16,}", line):
        return False
    if line in ("wwwx", "openapi", "5.0.9.99905", "4e944e09cec95b5b"):
        return False
    if line.isdigit() and len(line) >= 10:
        return False
    if "当前版本不支持查看群公告" in line or "请升级版本" in line:
        return False
    # 检查有效中文字符或合法英文单词
    chinese_chars = sum(1 for ch in line if "\u4e00" <= ch <= "\u9fff")
    ascii_printable = sum(1 for ch in line if ch.isprintable() and ord(ch) < 128)
    
    # 过滤掉韩文/藏文/非标准乱码
    non_cjk_extended = sum(1 for ch in line if ord(ch) > 0x2e80 and not ("\u4e00" <= ch <= "\u9fff" or "\u3000" <= ch <= "\u303f" or "\uff00" <= ch <= "\uffef"))
    if non_cjk_extended > 5 and non_cjk_extended > chinese_chars:
        return False
        
    if chinese_chars >= 2:
        return True
    if line.startswith("http://") or line.startswith("https://"):
        return True
    if len(line.split()) >= 2 and ascii_printable >= 5:
        return True
    return False

def clean_text_block(text):
    if not text:
        return ""
    lines = []
    for line in text.splitlines():
        line = re.sub(r"^[\x00-\x1f\s]+", "", line)
        line = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]+", " ", line).strip()
        if is_meaningful_text(line):
            lines.append(line)
    return "\n".join(lines)

def main():
    profile_dir = "/Users/josephine001/Library/Containers/com.tencent.WeWorkMac/Data/Documents/Profiles/65196B406683200E24F20354A21E3605"
    snap_path = os.path.join(profile_dir, "conv_snapshot")
    export_dir = os.path.expanduser("~/Desktop/企业微信活跃群聊聊天记录")
    os.makedirs(export_dir, exist_ok=True)

    with open(snap_path, "rb") as f:
        data = f.read()

    pos = 4 + struct.unpack("<I", data[:4])[0]
    proto_len = struct.unpack("<I", data[pos : pos + 4])[0]
    pos += 4
    proto_data = data[pos : pos + proto_len]

    p = 0
    conv_list = []
    user_list = []

    while p < len(proto_data):
        tag, p = read_varint(proto_data, p)
        if tag is None:
            break
        wire = tag & 7
        fn = tag >> 3
        if wire == 2:
            length, p = read_varint(proto_data, p)
            if length is None or p + length > len(proto_data):
                break
            sub = proto_data[p : p + length]
            p += length
            if fn == 1:
                conv_list.append(parse_all_subfields(sub))
            elif fn == 2:
                user_list.append(parse_all_subfields(sub))
        elif wire == 0:
            _, p = read_varint(proto_data, p)
        else:
            break

    print(f"读取到 {len(conv_list)} 个会话对象，{len(user_list)} 位联系人档案。")

    exported_chats = []

    for idx, it in enumerate(conv_list, 1):
        raw_title = ""
        if 3 in it:
            for t_type, t_val in it[3]:
                if t_type == "bytes":
                    raw_title = t_val.decode("utf-8", errors="ignore").strip()
                    break

        title = raw_title or f"会话_{idx}"
        title = re.sub(r"^[【\(\{\/]+", "", title).strip()

        # 时间戳解析
        ts_list = [
            v
            for fn in (6, 7, 17, 18)
            if fn in it
            for t, v in it[fn]
            if t == "int" and 1600000000 < v < 2000000000
        ]
        last_time = max(ts_list) if ts_list else 0
        time_str = (
            datetime.fromtimestamp(last_time).strftime("%Y-%m-%d %H:%M:%S")
            if last_time
            else "未知时间"
        )

        # 群公告 / 业务规则 (Field 11)
        notices = []
        if 11 in it:
            for _, b in it[11]:
                if isinstance(b, bytes):
                    txt = decode_content(b).strip()
                    cleaned = clean_text_block(txt)
                    if cleaned and len(cleaned) > 5 and not cleaned.startswith("[二进制"):
                        notices.append(cleaned)

        # 成员状态与最新消息 (Field 10)
        messages_f10 = []
        if 10 in it:
            for _, b in it[10]:
                if isinstance(b, bytes):
                    txt = decode_content(b).strip()
                    cleaned = clean_text_block(txt)
                    if cleaned and len(cleaned) > 2 and not cleaned.startswith("[二进制"):
                        messages_f10.append(cleaned)

        # 沟通记录与交接 (Field 15)
        messages_f15 = []
        if 15 in it:
            for _, b in it[15]:
                if isinstance(b, bytes):
                    txt = decode_content(b).strip()
                    cleaned = clean_text_block(txt)
                    if cleaned and len(cleaned) > 2 and not cleaned.startswith("[二进制"):
                        messages_f15.append(cleaned)

        # 合并并去重所有沟通记录
        all_msgs = []
        for m in messages_f10:
            if m not in all_msgs:
                all_msgs.append(m)
        for m in messages_f15:
            if m not in all_msgs:
                all_msgs.append(m)

        exported_chats.append({
            "index": idx,
            "title": title,
            "last_time": last_time,
            "time_str": time_str,
            "notices": notices,
            "messages": all_msgs,
        })

    # 按最后活跃时间倒序排列
    exported_chats.sort(key=lambda c: c["last_time"], reverse=True)

    # 导出各个群聊的独立 Markdown 文件
    for idx, chat in enumerate(exported_chats, 1):
        safe_name = _safe_dirname(chat["title"])
        fname = f"{idx:02d}_{safe_name}.md"
        fpath = os.path.join(export_dir, fname)

        lines = [
            f"# 💬 {chat['title']}",
            "",
            f"- **最后活跃时间**: `{chat['time_str']}`",
            f"- **所属账号**: 邬广武 (嘉立创 · 销售助理 · 18127715604)",
            f"- **导出时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "---",
            "",
        ]

        if chat["notices"]:
            lines.append("## 📌 群公告 / 业务规则 / SOP 规范")
            lines.append("")
            for n in chat["notices"]:
                for nl in n.splitlines():
                    lines.append(f"> {nl}")
                lines.append("")
            lines.append("---")
            lines.append("")

        if chat["messages"]:
            lines.append("## 📝 聊天记录 / 业务沟通与交接详情")
            lines.append("")
            for msg in chat["messages"]:
                lines.append("### 🔹 记录详情")
                for ml in msg.splitlines():
                    ml_s = ml.strip()
                    if ml_s.startswith("http://") or ml_s.startswith("https://"):
                        lines.append(f"- 🔗 协作文档: [{ml_s}]({ml_s})")
                    elif ml_s:
                        lines.append(f"- {ml_s}")
                lines.append("")
        else:
            lines.append("## 📝 聊天记录状态说明")
            lines.append("")
            lines.append("> 💡 **说明**：该会话当前处于后台挂起状态，快照中未包含临时文字缓存。完整全量历史聊天记录（含数千条消息记录与附件）存储在已加密的本地主数据库 `Messages1/Info.db` (25MB) 中。")
            lines.append("")

        with open(fpath, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    # 生成总览索引汇总文件
    index_path = os.path.join(export_dir, "00_企业微信活跃群聊概览汇总.md")
    idx_lines = [
        "# 🏢 企业微信活跃群聊与业务会话概览汇总",
        "",
        f"> **导出时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ",
        "> **当前登录账号**: **邬广武** (WuGuangWu · 嘉立创 · 销售助理 · 18127715604)  ",
        f"> **共导出活跃群聊/会话**: **{len(exported_chats)}** 个  ",
        f"> **导出目录**: `{export_dir}`  ",
        "",
        "---",
        "",
        "## 📋 活跃群聊与会话目录索引",
        "",
        "| 序号 | 群聊 / 会话名称 | 最后活跃时间 | 包含内容 | 详情文档 |",
        "| :--- | :--- | :--- | :--- | :--- |",
    ]

    for idx, chat in enumerate(exported_chats, 1):
        safe_name = _safe_dirname(chat["title"])
        fname = f"{idx:02d}_{safe_name}.md"
        content_tags = []
        if chat["notices"]:
            content_tags.append("📌群公告/SOP")
        if chat["messages"]:
            content_tags.append(f"💬沟通记录({len(chat['messages'])}条)")
        tag_str = " / ".join(content_tags) or "基础会话"

        idx_lines.append(
            f"| {idx} | **{chat['title']}** | {chat['time_str']} | {tag_str} | [{fname}](./{fname}) |"
        )

    idx_lines.append("")
    idx_lines.append("---")
    idx_lines.append("")
    idx_lines.append("## 🌟 核心业务群聊内容速览")
    idx_lines.append("")

    for idx, chat in enumerate(exported_chats[:20], 1):
        if chat["notices"] or chat["messages"]:
            idx_lines.append(f"### {idx}. {chat['title']}")
            idx_lines.append(f"- **最后活跃时间**: `{chat['time_str']}`")
            if chat["notices"]:
                first_notice = chat["notices"][0].replace("\n", " ")[:140]
                idx_lines.append(f"- **群公告/规则**: {first_notice}...")
            if chat["messages"]:
                first_msg = chat["messages"][0].replace("\n", " ")[:140]
                idx_lines.append(f"- **沟通记录**: {first_msg}...")
            idx_lines.append("")

    with open(index_path, "w", encoding="utf-8") as f:
        f.write("\n".join(idx_lines))

    # 生成 HTML 浏览页面
    html_path = os.path.join(export_dir, "index.html")
    html_content = generate_html_viewer(exported_chats)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"\n[+] 重新导出完成！")


def generate_html_viewer(chats):
    cards_html = []
    for idx, chat in enumerate(chats, 1):
        notices_html = "".join(
            f"<div class='notice-box'><strong>📌 群公告 / 规则：</strong><br>{n.replace(chr(10), '<br>')}</div>"
            for n in chat["notices"]
        )
        msgs_html = "".join(
            f"<div class='msg-box'><strong>💬 沟通详情：</strong><br>{m.replace(chr(10), '<br>')}</div>"
            for m in chat["messages"]
        )
        if not notices_html and not msgs_html:
            msgs_html = "<div class='empty-box'>完整全量历史聊天记录存储于已加密的 Info.db (25MB) 主数据库中</div>"

        cards_html.append(f"""
        <div class="chat-card" id="chat-{idx}">
            <div class="chat-header">
                <span class="chat-idx">#{idx}</span>
                <span class="chat-title">{chat['title']}</span>
                <span class="chat-time">{chat['time_str']}</span>
            </div>
            <div class="chat-body">
                {notices_html}
                {msgs_html}
            </div>
        </div>
        """)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>企业微信活跃群聊聊天记录汇总</title>
<style>
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: #f0f2f5; font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif; color: #1f2937; }}
.header {{ background: #0052d9; color: #fff; padding: 20px 24px; position: sticky; top: 0; z-index: 100; box-shadow: 0 2px 8px rgba(0,0,0,.15); }}
.header h1 {{ margin: 0; font-size: 20px; }}
.header p {{ margin: 6px 0 0; font-size: 13px; opacity: .9; }}
.container {{ max-width: 1000px; margin: 20px auto; padding: 0 16px; }}
.chat-card {{ background: #fff; border-radius: 10px; margin-bottom: 16px; padding: 18px 20px; box-shadow: 0 1px 4px rgba(0,0,0,.08); border: 1px solid #e5e7eb; }}
.chat-header {{ display: flex; align-items: center; gap: 10px; border-bottom: 1px solid #f3f4f6; padding-bottom: 10px; margin-bottom: 12px; }}
.chat-idx {{ background: #0052d9; color: #fff; font-weight: 700; font-size: 12px; padding: 2px 8px; border-radius: 4px; }}
.chat-title {{ font-size: 16px; font-weight: 700; color: #111827; flex: 1; }}
.chat-time {{ font-size: 12px; color: #6b7280; }}
.notice-box {{ background: #fefce8; border-left: 4px solid #eab308; padding: 10px 14px; border-radius: 4px; margin-bottom: 10px; font-size: 13px; line-height: 1.6; color: #854d0e; word-break: break-word; }}
.msg-box {{ background: #f8fafc; border-left: 4px solid #3b82f6; padding: 10px 14px; border-radius: 4px; margin-bottom: 10px; font-size: 13px; line-height: 1.6; color: #334155; word-break: break-word; }}
.empty-box {{ color: #9ca3af; font-size: 13px; font-style: italic; padding: 8px 0; }}
a {{ color: #0052d9; text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
</style>
</head>
<body>
<div class="header">
    <h1>🏢 企业微信活跃群聊与业务会话概览</h1>
    <p>登录账号：邬广武（嘉立创 · 销售助理） | 共 {len(chats)} 个会话</p>
</div>
<div class="container">
    {''.join(cards_html)}
</div>
</body>
</html>"""

if __name__ == "__main__":
    main()
