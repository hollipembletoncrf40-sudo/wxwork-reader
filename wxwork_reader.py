#!/usr/bin/env python3
"""
企业微信本地数据读取与检索工具 (Enterprise WeChat Data Reader)

功能特性:
1. Python API: 提供 WXWorkReader 类，支持联系人、会话、消息读取与全局检索。
2. 命令行工具 (CLI): 支持查看状态、列出会话、阅读聊天、全局全文搜索、数据统计、多格式导出。
3. 多格式导出: 支持 Markdown (.md)、HTML (.html)、JSON (.json)、CSV (.csv)。
4. 交互式终端: 支持交互式浏览与搜索会话。
"""

import argparse
import csv
import json
import os
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from html import escape
from typing import Any, Dict, Generator, Iterable, List, Optional, Set, Tuple, Union

# Windows 控制台 UTF-8 支持
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 消息类型对照表
MSG_TYPES = {
    0: "文本/混合",
    2: "文本",
    4: "图片",
    7: "语音",
    15: "图片/文件",
    38: "应用消息",
    40: "通话/音视频",
    503: "状态",
    1011: "会议通知",
}

_MESSAGE_TABLES = ("message_table", "message_small_table", "kf_message_tableV1")


# =====================================================================
# 辅助函数与解码逻辑
# =====================================================================

def _app_paths() -> Tuple[str, str]:
    """获取程序根目录与 config.json 路径"""
    try:
        from config import _app_base_dir, _config_file_path
        return _app_base_dir(), _config_file_path()
    except ImportError:
        base = os.path.dirname(os.path.abspath(__file__))
        return base, os.path.join(base, "config.json")


def _safe_dirname(name: str) -> str:
    """过滤文件名中的非法字符"""
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", str(name))
    name = re.sub(r"\s+", " ", name).strip(" .")
    return (name or "unknown")[:120]


def _open_db(path: str) -> sqlite3.Connection:
    """打开 SQLite 数据库并返回 Row 映射"""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    """判断数据库中是否存在某表"""
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _format_time(ts: Any) -> str:
    """时间戳格式化为 YYYY-MM-DD HH:MM:SS"""
    try:
        ts = int(ts or 0)
    except (TypeError, ValueError):
        ts = 0
    if ts <= 0:
        return ""
    if ts > 20_000_000_000:
        ts = ts / 1000
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ts)


def _parse_time_filter(val: Optional[Union[str, int, float]]) -> Optional[int]:
    """解析时间过滤参数为秒级时间戳"""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return int(val if val < 20_000_000_000 else val / 1000)
    val = str(val).strip()
    if not val:
        return None
    if val.isdigit():
        ts = int(val)
        return int(ts if ts < 20_000_000_000 else ts / 1000)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return int(datetime.strptime(val, fmt).timestamp())
        except ValueError:
            pass
    return None


def _read_varint(data: bytes, pos: int) -> Tuple[int, int]:
    """解析 Protobuf varint"""
    value = 0
    shift = 0
    while pos < len(data) and shift < 64:
        b = data[pos]
        pos += 1
        value |= (b & 0x7F) << shift
        if not (b & 0x80):
            return value, pos
        shift += 7
    raise ValueError("bad varint")


def _clean_text(text: str) -> str:
    """清理字符串中的不可见字符"""
    if not text:
        return ""
    text = "".join(
        ch if ch in "\n\t" or (ch.isprintable() and ch not in "\x0b\x0c") else " "
        for ch in text
    )
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _looks_like_plain_text(data: bytes, text: str) -> bool:
    """检测二进制串是否为纯文本"""
    if not text:
        return False
    control = sum(1 for b in data if b < 32 and b not in (9, 10, 13))
    if control / max(len(data), 1) > 0.08:
        return False
    printable = sum(1 for ch in text if ch.isprintable() or ch in "\n\t")
    return printable / max(len(text), 1) > 0.9


def _decode_text_segment(segment: bytes) -> Optional[str]:
    """提取有效的 UTF-8 文本片段"""
    if not segment or b"\x00" in segment:
        return None
    try:
        text = segment.decode("utf-8")
    except UnicodeDecodeError:
        return None
    text = _clean_text(text)
    if len(text) < 2:
        return None
    if re.fullmatch(r"[0-9a-fA-F]{32,}", text):
        return None
    printable = sum(1 for ch in text if ch.isprintable() or ch in "\n\t")
    if printable / max(len(text), 1) < 0.9:
        return None
    return text


def _parse_protobuf_strings(data: bytes, depth: int = 0) -> List[str]:
    """递归解析二进制数据中的 Protobuf 字符串片段"""
    if depth > 4 or not data:
        return []
    pos = 0
    out = []
    fields = 0
    try:
        while pos < len(data):
            tag, pos = _read_varint(data, pos)
            if tag == 0:
                return []
            wire = tag & 7
            fields += 1
            if wire == 0:
                _, pos = _read_varint(data, pos)
            elif wire == 1:
                pos += 8
            elif wire == 5:
                pos += 4
            elif wire == 2:
                length, pos = _read_varint(data, pos)
                if length < 0 or pos + length > len(data):
                    return []
                segment = data[pos : pos + length]
                pos += length
                text = _decode_text_segment(segment)
                if text:
                    out.append(text)
                else:
                    out.extend(_parse_protobuf_strings(segment, depth + 1))
            else:
                return []
            if pos > len(data):
                return []
    except Exception:
        return []
    return out if fields else []


def _dedupe_texts(values: Iterable[str]) -> List[str]:
    """去重文本列表"""
    seen = set()
    out = []
    for value in values:
        value = _clean_text(value)
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def decode_content(raw: Any) -> str:
    """通用消息二进制/字符串解码"""
    if raw is None:
        return ""
    if isinstance(raw, str):
        return _clean_text(raw)
    data = bytes(raw)
    if not data:
        return ""

    try:
        plain = data.decode("utf-8")
        if _looks_like_plain_text(data, plain):
            return _clean_text(plain)
    except UnicodeDecodeError:
        pass

    texts = _dedupe_texts(_parse_protobuf_strings(data))
    if texts:
        return "\n".join(texts[:12])

    for enc in ("utf-8", "gbk", "utf-16le"):
        try:
            text = _clean_text(data.decode(enc, errors="replace"))
            if text and "\ufffd" not in text[:20]:
                return text[:2000]
        except Exception:
            continue
    return f"[二进制内容 {len(data)} 字节]"


def conversation_kind(conversation_id: str) -> str:
    """根据会话 ID 前缀判断会话类型"""
    if not conversation_id:
        return "未知"
    if conversation_id.startswith("R:"):
        return "群聊"
    if conversation_id.startswith("S:"):
        return "单聊"
    if conversation_id.startswith("M:"):
        return "微信联系人"
    if conversation_id.startswith("O:"):
        return "应用/公众号"
    if conversation_id.startswith("Y:"):
        return "系统会话"
    return "其他"


# =====================================================================
# 核心读取器类: WXWorkReader
# =====================================================================

class WXWorkReader:
    """企业微信已解密数据库读取器"""

    def __init__(self, decrypted_dir: Optional[str] = None, self_id: Optional[int] = None):
        base, config_file = _app_paths()
        cfg = {}
        if os.path.exists(config_file):
            try:
                with open(config_file, encoding="utf-8") as f:
                    cfg = json.load(f)
            except Exception:
                cfg = {}

        if decrypted_dir is None:
            decrypted_dir = cfg.get("wxwork_decrypted_dir", "wxwork_decrypted")
            if not os.path.isabs(decrypted_dir):
                decrypted_dir = os.path.join(base, decrypted_dir)

        self.decrypted_dir = os.path.abspath(decrypted_dir)
        self.self_id = self_id or self._infer_self_id(cfg.get("wxwork_db_dir", ""))

        self.user_db_path = os.path.join(self.decrypted_dir, "user.db")
        self.session_db_path = os.path.join(self.decrypted_dir, "session.db")
        self.message_db_path = os.path.join(self.decrypted_dir, "message.db")

        # 缓存
        self._user_map: Optional[Dict[int, Dict[str, Any]]] = None
        self._group_members: Optional[Dict[str, Dict[int, str]]] = None
        self._conversations: Optional[Dict[str, Dict[str, Any]]] = None

    @staticmethod
    def _infer_self_id(db_dir: str) -> Optional[int]:
        """从数据目录推断当前登录账号的用户 ID"""
        if not db_dir:
            return None
        parts = os.path.normpath(db_dir).split(os.sep)
        for part in reversed(parts):
            if part.isdigit() and len(part) >= 10:
                return int(part)
        return None

    def status(self) -> Dict[str, Any]:
        """检查数据库状态及数据概览"""
        exists_user = os.path.exists(self.user_db_path)
        exists_session = os.path.exists(self.session_db_path)
        exists_message = os.path.exists(self.message_db_path)

        user_count = 0
        if exists_user:
            try:
                conn = _open_db(self.user_db_path)
                if _table_exists(conn, "user_table"):
                    row = conn.execute("SELECT COUNT(*) FROM user_table").fetchone()
                    user_count = row[0] if row else 0
                conn.close()
            except Exception:
                pass

        conv_count = 0
        if exists_session:
            try:
                conn = _open_db(self.session_db_path)
                if _table_exists(conn, "conversation_table"):
                    row = conn.execute("SELECT COUNT(*) FROM conversation_table").fetchone()
                    conv_count = row[0] if row else 0
                conn.close()
            except Exception:
                pass

        msg_count = 0
        if exists_message:
            try:
                conn = _open_db(self.message_db_path)
                for tbl in _MESSAGE_TABLES:
                    if _table_exists(conn, tbl):
                        row = conn.execute(f'SELECT COUNT(*) FROM "{tbl}"').fetchone()
                        msg_count += row[0] if row else 0
                conn.close()
            except Exception:
                pass

        return {
            "decrypted_dir": self.decrypted_dir,
            "is_ready": exists_user or exists_session or exists_message,
            "databases": {
                "user.db": {"path": self.user_db_path, "exists": exists_user, "user_count": user_count},
                "session.db": {"path": self.session_db_path, "exists": exists_session, "conversation_count": conv_count},
                "message.db": {"path": self.message_db_path, "exists": exists_message, "message_count": msg_count},
            },
            "self_id": self.self_id,
        }

    # ─────────────────────────────────────────────────────────────
    # 联系人相关方法
    # ─────────────────────────────────────────────────────────────

    def load_user_map(self, force_reload: bool = False) -> Dict[int, Dict[str, Any]]:
        """加载联系人详情映射表: user_id -> 用户信息字典"""
        if self._user_map is not None and not force_reload:
            return self._user_map

        users: Dict[int, Dict[str, Any]] = {}
        if not os.path.exists(self.user_db_path):
            self._user_map = users
            return users

        conn = _open_db(self.user_db_path)
        try:
            if _table_exists(conn, "user_table"):
                for row in conn.execute(
                    "SELECT id, name, real_name, account, external_corp_name, external_job "
                    "FROM user_table"
                ):
                    uid = int(row["id"])
                    name = row["name"] or ""
                    real_name = row["real_name"] or ""
                    account = row["account"] or ""
                    corp = row["external_corp_name"] or ""
                    job = row["external_job"] or ""

                    disp = real_name or name or account or f"用户_{uid}"
                    if corp and corp not in disp:
                        disp = f"{disp} ({corp})"

                    users[uid] = {
                        "user_id": uid,
                        "name": name,
                        "real_name": real_name,
                        "account": account,
                        "external_corp_name": corp,
                        "external_job": job,
                        "display_name": disp,
                        "is_external": bool(corp or "wxid" in account.lower()),
                        "remarks": "",
                    }

            if _table_exists(conn, "external_user_relation_v3"):
                for row in conn.execute(
                    "SELECT user_id, remarks, real_remarks, corp_remark FROM external_user_relation_v3"
                ):
                    uid = int(row["user_id"])
                    rem = row["real_remarks"] or row["remarks"] or row["corp_remark"] or ""
                    if rem:
                        if uid in users:
                            users[uid]["remarks"] = rem
                            users[uid]["display_name"] = rem
                        else:
                            users[uid] = {
                                "user_id": uid,
                                "name": rem,
                                "real_name": rem,
                                "account": "",
                                "external_corp_name": row["corp_remark"] or "",
                                "external_job": "",
                                "display_name": rem,
                                "is_external": True,
                                "remarks": rem,
                            }
        finally:
            conn.close()

        self._user_map = users
        return users

    def get_contacts(
        self,
        search: Optional[str] = None,
        is_external: Optional[bool] = None,
    ) -> List[Dict[str, Any]]:
        """获取联系人列表，支持关键词过滤与内外联系人筛选"""
        users = self.load_user_map()
        results = list(users.values())

        if is_external is not None:
            results = [u for u in results if u["is_external"] == is_external]

        if search:
            kw = search.lower().strip()
            results = [
                u
                for u in results
                if kw in str(u["user_id"])
                or kw in u["name"].lower()
                or kw in u["real_name"].lower()
                or kw in u["account"].lower()
                or kw in u["external_corp_name"].lower()
                or kw in u["remarks"].lower()
                or kw in u["display_name"].lower()
            ]

        results.sort(key=lambda u: u["display_name"])
        return results

    def get_contact(self, user_id: int) -> Optional[Dict[str, Any]]:
        """根据 user_id 获取单个联系人信息"""
        users = self.load_user_map()
        return users.get(int(user_id))

    # ─────────────────────────────────────────────────────────────
    # 会话相关方法
    # ─────────────────────────────────────────────────────────────

    def load_group_member_names(self, force_reload: bool = False) -> Dict[str, Dict[int, str]]:
        """加载群成员群昵称映射: conversation_id -> {user_id -> 群昵称}"""
        if self._group_members is not None and not force_reload:
            return self._group_members

        members: Dict[str, Dict[int, str]] = defaultdict(dict)
        if not os.path.exists(self.session_db_path):
            self._group_members = members
            return members

        conn = _open_db(self.session_db_path)
        try:
            if _table_exists(conn, "conversation_user_table"):
                for row in conn.execute(
                    "SELECT conversation_id, user_id, nick_name FROM conversation_user_table"
                ):
                    if row["nick_name"]:
                        members[row["conversation_id"]][int(row["user_id"])] = row["nick_name"]

            if _table_exists(conn, "conversation_member_nickname_table"):
                room_map = {}
                if _table_exists(conn, "conversation_table"):
                    for row in conn.execute("SELECT con_numeric_id, id FROM conversation_table"):
                        if row["con_numeric_id"] and row["id"]:
                            room_map[int(row["con_numeric_id"])] = row["id"]
                for row in conn.execute(
                    "SELECT room_id, userid, nickname FROM conversation_member_nickname_table"
                ):
                    cid = room_map.get(int(row["room_id"]))
                    if cid and row["nickname"]:
                        members[cid][int(row["userid"])] = row["nickname"]
        finally:
            conn.close()

        self._group_members = members
        return members

    def _resolve_conv_name(self, conversation_id: str, raw_name: str) -> str:
        """解析会话名称"""
        if raw_name:
            return raw_name

        user_map = self.load_user_map()

        # 单聊会话解析
        if conversation_id.startswith("S:"):
            ids = [int(v) for v in conversation_id[2:].split("_") if v.isdigit()]
            other_ids = [uid for uid in ids if self.self_id is None or uid != self.self_id]
            for uid in other_ids or ids:
                if uid in user_map:
                    return user_map[uid]["display_name"]

        # 单 ID 后缀
        if ":" in conversation_id:
            tail = conversation_id.split(":", 1)[1]
            if tail.isdigit() and int(tail) in user_map:
                return user_map[int(tail)]["display_name"]

        return conversation_id

    def load_message_stats(self) -> Tuple[Dict[str, int], Dict[str, int]]:
        """从 message.db 中统计各会话的消息总数与最后消息时间戳"""
        counts: Dict[str, int] = defaultdict(int)
        last_times: Dict[str, int] = defaultdict(int)
        if not os.path.exists(self.message_db_path):
            return counts, last_times

        conn = _open_db(self.message_db_path)
        try:
            for table in _MESSAGE_TABLES:
                if not _table_exists(conn, table):
                    continue
                for row in conn.execute(
                    f'SELECT conversation_id, COUNT(*) AS c, MAX(send_time) AS t '
                    f'FROM "{table}" GROUP BY conversation_id'
                ):
                    cid = row["conversation_id"]
                    if not cid:
                        continue
                    counts[cid] += int(row["c"] or 0)
                    last_times[cid] = max(last_times[cid], int(row["t"] or 0))
        finally:
            conn.close()

        return counts, last_times

    def get_conversations(
        self,
        kind: Optional[str] = None,
        search: Optional[str] = None,
        sort_by: str = "last_time",
        reverse: bool = True,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """获取所有会话列表"""
        user_map = self.load_user_map()
        counts, msg_last_times = self.load_message_stats()
        group_members = self.load_group_member_names()
        conv_dict: Dict[str, Dict[str, Any]] = {}

        if os.path.exists(self.session_db_path):
            conn = _open_db(self.session_db_path)
            try:
                if _table_exists(conn, "conversation_table"):
                    for row in conn.execute(
                        "SELECT id, name, roomname_remark, last_message_time, last_message_id "
                        "FROM conversation_table"
                    ):
                        cid = row["id"]
                        if not cid:
                            continue
                        raw_name = row["roomname_remark"] or row["name"] or ""
                        disp = self._resolve_conv_name(cid, raw_name)
                        last_t = max(
                            int(row["last_message_time"] or 0),
                            msg_last_times.get(cid, 0),
                        )
                        conv_dict[cid] = {
                            "conversation_id": cid,
                            "display_name": disp,
                            "raw_name": raw_name,
                            "kind": conversation_kind(cid),
                            "message_count": counts.get(cid, 0),
                            "last_time": last_t,
                            "last_time_str": _format_time(last_t),
                            "last_message_id": int(row["last_message_id"] or 0),
                            "member_count": len(group_members.get(cid, {})),
                        }
            finally:
                conn.close()

        # 补全 message.db 中存在但在 session.db 中未记录的会话
        for cid, count in counts.items():
            if cid in conv_dict:
                conv_dict[cid]["message_count"] = count
                conv_dict[cid]["last_time"] = max(
                    conv_dict[cid]["last_time"], msg_last_times.get(cid, 0)
                )
                conv_dict[cid]["last_time_str"] = _format_time(conv_dict[cid]["last_time"])
                continue
            disp = self._resolve_conv_name(cid, "")
            last_t = msg_last_times.get(cid, 0)
            conv_dict[cid] = {
                "conversation_id": cid,
                "display_name": disp,
                "raw_name": "",
                "kind": conversation_kind(cid),
                "message_count": count,
                "last_time": last_t,
                "last_time_str": _format_time(last_t),
                "last_message_id": 0,
                "member_count": len(group_members.get(cid, {})),
            }

        conversations = list(conv_dict.values())

        # 过滤
        if kind:
            conversations = [c for c in conversations if c["kind"] == kind]

        if search:
            kw = search.lower().strip()
            conversations = [
                c
                for c in conversations
                if kw in c["conversation_id"].lower()
                or kw in c["display_name"].lower()
                or kw in c["kind"].lower()
            ]

        # 排序
        if sort_by == "message_count":
            conversations.sort(key=lambda c: (c["message_count"], c["last_time"]), reverse=reverse)
        elif sort_by == "name":
            conversations.sort(key=lambda c: c["display_name"], reverse=reverse)
        else:  # last_time
            conversations.sort(key=lambda c: (c["last_time"], c["message_count"]), reverse=reverse)

        if limit is not None and limit > 0:
            conversations = conversations[:limit]

        return conversations

    def get_conversation(self, conv_id_or_name: str) -> Optional[Dict[str, Any]]:
        """通过精确 ID 或模糊名称查找单个会话"""
        convs = self.get_conversations()
        for c in convs:
            if c["conversation_id"] == conv_id_or_name:
                return c

        kw = conv_id_or_name.lower().strip()
        matched = [c for c in convs if kw in c["display_name"].lower()]
        if matched:
            return matched[0]
        return None

    # ─────────────────────────────────────────────────────────────
    # 消息相关方法
    # ─────────────────────────────────────────────────────────────

    def _build_message_dict(
        self,
        row: sqlite3.Row,
        conv_map: Dict[str, Dict[str, Any]],
        user_map: Dict[int, Dict[str, Any]],
        member_names: Dict[str, Dict[int, str]],
    ) -> Dict[str, Any]:
        """将原始数据库行组装为规范化消息对象"""
        cid = row["conversation_id"]
        sender_id = int(row["sender_id"] or 0)

        # 发送者名称解析
        sender = member_names.get(cid, {}).get(sender_id)
        if not sender and sender_id in user_map:
            sender = user_map[sender_id]["display_name"]
        if self.self_id is not None and sender_id == self.self_id:
            sender = "我"
        if not sender:
            sender = str(sender_id) if sender_id else "系统"

        content = decode_content(row["content"])
        extra_content = decode_content(row["extra_content"])
        local_extra_content = decode_content(row["local_extra_content"])
        content_type = int(row["content_type"] or 0)
        conv = conv_map.get(cid, {})

        display_content = content or extra_content or local_extra_content
        if not display_content:
            type_label = MSG_TYPES.get(content_type, f"类型{content_type}")
            display_content = f"[{type_label}]"

        send_time = int(row["send_time"] or 0)

        return {
            "source_table": row["source_table"],
            "message_id": int(row["message_id"] or 0),
            "server_id": int(row["server_id"] or 0),
            "sequence": int(row["sequence"] or 0),
            "conversation_id": cid,
            "conversation_name": conv.get("display_name") or cid,
            "conversation_kind": conv.get("kind") or conversation_kind(cid),
            "sender_id": sender_id,
            "sender": sender,
            "content_type": content_type,
            "type_name": MSG_TYPES.get(content_type, f"未知({content_type})"),
            "send_time": send_time,
            "time": _format_time(send_time),
            "flag": int(row["flag"] or 0),
            "content": content,
            "extra_content": extra_content,
            "local_extra_content": local_extra_content,
            "display_content": display_content,
            "is_sent": self.self_id is not None and sender_id == self.self_id,
        }

    def get_messages(
        self,
        conversation_id: str,
        start_time: Optional[Union[str, int]] = None,
        end_time: Optional[Union[str, int]] = None,
        limit: Optional[int] = None,
        offset: int = 0,
        reverse: bool = False,
        keyword: Optional[str] = None,
        sender_id: Optional[int] = None,
        content_types: Optional[List[int]] = None,
    ) -> List[Dict[str, Any]]:
        """获取指定会话的历史消息"""
        if not os.path.exists(self.message_db_path):
            return []

        user_map = self.load_user_map()
        member_names = self.load_group_member_names()
        conv_info = self.get_conversation(conversation_id)
        conv_map = {conversation_id: conv_info} if conv_info else {}

        start_ts = _parse_time_filter(start_time)
        end_ts = _parse_time_filter(end_time)

        conn = _open_db(self.message_db_path)
        messages: List[Dict[str, Any]] = []
        seen_keys: Set[Tuple[Any, ...]] = set()

        try:
            for table in _MESSAGE_TABLES:
                if not _table_exists(conn, table):
                    continue

                clauses = ["conversation_id = ?"]
                params: List[Any] = [conversation_id]

                if start_ts is not None:
                    clauses.append("send_time >= ?")
                    params.append(start_ts)
                if end_ts is not None:
                    clauses.append("send_time <= ?")
                    params.append(end_ts)
                if sender_id is not None:
                    clauses.append("sender_id = ?")
                    params.append(sender_id)
                if content_types:
                    placeholders = ",".join("?" for _ in content_types)
                    clauses.append(f"content_type IN ({placeholders})")
                    params.extend(content_types)

                where_sql = " AND ".join(clauses)
                sql = (
                    f'SELECT "{table}" AS source_table, message_id, server_id, sequence, '
                    f"sender_id, conversation_id, content_type, send_time, flag, "
                    f"content, extra_content, local_extra_content "
                    f'FROM "{table}" WHERE {where_sql} '
                    f"ORDER BY send_time ASC, sequence ASC, message_id ASC"
                )

                for row in conn.execute(sql, params):
                    key = (row["conversation_id"], row["message_id"], row["server_id"], row["sequence"])
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    msg = self._build_message_dict(row, conv_map, user_map, member_names)

                    if keyword:
                        kw = keyword.lower()
                        if kw not in msg["display_content"].lower() and kw not in msg["sender"].lower():
                            continue

                    messages.append(msg)
        finally:
            conn.close()

        # 全局去重并按时间排序
        messages.sort(key=lambda m: (m["send_time"], m["sequence"], m["message_id"]))

        if reverse:
            messages.reverse()

        if offset > 0:
            messages = messages[offset:]
        if limit is not None and limit > 0:
            messages = messages[:limit]

        return messages

    def search_messages(
        self,
        keyword: str,
        conversation_id: Optional[str] = None,
        start_time: Optional[Union[str, int]] = None,
        end_time: Optional[Union[str, int]] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """全局或会话内搜索消息"""
        if not keyword or not os.path.exists(self.message_db_path):
            return []

        user_map = self.load_user_map()
        member_names = self.load_group_member_names()
        convs = self.get_conversations()
        conv_map = {c["conversation_id"]: c for c in convs}

        start_ts = _parse_time_filter(start_time)
        end_ts = _parse_time_filter(end_time)
        kw = keyword.strip().lower()

        conn = _open_db(self.message_db_path)
        matches: List[Dict[str, Any]] = []
        seen_keys: Set[Tuple[Any, ...]] = set()

        try:
            for table in _MESSAGE_TABLES:
                if not _table_exists(conn, table):
                    continue

                clauses = []
                params: List[Any] = []

                if conversation_id:
                    clauses.append("conversation_id = ?")
                    params.append(conversation_id)
                if start_ts is not None:
                    clauses.append("send_time >= ?")
                    params.append(start_ts)
                if end_ts is not None:
                    clauses.append("send_time <= ?")
                    params.append(end_ts)

                where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
                sql = (
                    f'SELECT "{table}" AS source_table, message_id, server_id, sequence, '
                    f"sender_id, conversation_id, content_type, send_time, flag, "
                    f"content, extra_content, local_extra_content "
                    f'FROM "{table}" {where_sql} '
                    f"ORDER BY send_time DESC"
                )

                for row in conn.execute(sql, params):
                    key = (row["conversation_id"], row["message_id"], row["server_id"], row["sequence"])
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)

                    msg = self._build_message_dict(row, conv_map, user_map, member_names)
                    if kw in msg["display_content"].lower() or kw in msg["sender"].lower():
                        matches.append(msg)
                        if len(matches) >= (limit + offset) * 2:
                            break
        finally:
            conn.close()

        matches.sort(key=lambda m: m["send_time"], reverse=True)
        return matches[offset : offset + limit]

    # ─────────────────────────────────────────────────────────────
    # 数据统计与总结
    # ─────────────────────────────────────────────────────────────

    def get_statistics(self) -> Dict[str, Any]:
        """获取企业微信整体数据分析与活跃排行"""
        convs = self.get_conversations(sort_by="message_count", reverse=True)
        users = self.load_user_map()

        total_messages = sum(c["message_count"] for c in convs)
        kind_dist = defaultdict(int)
        for c in convs:
            kind_dist[c["kind"]] += 1

        top_convs = convs[:10]

        return {
            "total_conversations": len(convs),
            "total_contacts": len(users),
            "internal_contacts": sum(1 for u in users.values() if not u["is_external"]),
            "external_contacts": sum(1 for u in users.values() if u["is_external"]),
            "total_messages": total_messages,
            "conversation_kinds": dict(kind_dist),
            "top_conversations": [
                {
                    "conversation_id": c["conversation_id"],
                    "name": c["display_name"],
                    "kind": c["kind"],
                    "message_count": c["message_count"],
                    "last_time": c["last_time_str"],
                }
                for c in top_convs
            ],
        }

    # ─────────────────────────────────────────────────────────────
    # 多格式导出
    # ─────────────────────────────────────────────────────────────

    def export_chat(
        self,
        conversation_id: str,
        output_path: Optional[str] = None,
        format: str = "markdown",
    ) -> str:
        """导出单个会话聊天记录到指定格式文件"""
        conv = self.get_conversation(conversation_id) or {
            "conversation_id": conversation_id,
            "display_name": conversation_id,
            "kind": conversation_kind(conversation_id),
        }
        messages = self.get_messages(conversation_id)

        format = format.lower().strip()
        if not output_path:
            ext_map = {"markdown": ".md", "md": ".md", "html": ".html", "json": ".json", "csv": ".csv", "txt": ".txt"}
            ext = ext_map.get(format, ".txt")
            safe_name = _safe_dirname(conv["display_name"])
            output_path = f"{safe_name}_{conversation_id[:8]}{ext}"

        output_dir = os.path.dirname(os.path.abspath(output_path))
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        if format in ("markdown", "md"):
            self._write_markdown(output_path, conv, messages)
        elif format == "html":
            self._write_html(output_path, conv, messages)
        elif format == "json":
            self._write_json(output_path, conv, messages)
        elif format == "csv":
            self._write_csv(output_path, messages)
        else:
            self._write_plain_text(output_path, conv, messages)

        return os.path.abspath(output_path)

    @staticmethod
    def _write_markdown(path: str, conv: Dict[str, Any], messages: List[Dict[str, Any]]) -> None:
        lines = [
            f"# 会话: {conv['display_name']}",
            "",
            f"- **类型**: {conv.get('kind', '未知')}",
            f"- **会话 ID**: `{conv['conversation_id']}`",
            f"- **消息总数**: {len(messages)} 条",
            f"- **导出时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "---",
            "",
        ]

        last_day = None
        for m in messages:
            day = m["time"][:10] if m["time"] else ""
            if day and day != last_day:
                lines.append(f"\n### 📅 {day}\n")
                last_day = day

            sender_badge = f"**{m['sender']}**" if not m["is_sent"] else "**我**"
            time_badge = f"`{m['time'][11:]}`" if len(m["time"]) >= 16 else f"`{m['time']}`"
            type_info = f" *({m['type_name']})*" if m["content_type"] not in (0, 2) else ""

            lines.append(f"{sender_badge} {time_badge}{type_info}")
            content_text = m["display_content"] or ""
            # 引述格式输出
            quoted = "\n".join(f"> {line}" for line in content_text.splitlines()) if content_text else "> *(空内容)*"
            lines.append(quoted)
            lines.append("")

        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    @staticmethod
    def _write_html(path: str, conv: Dict[str, Any], messages: List[Dict[str, Any]]) -> None:
        template = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;background:#f3f4f6;color:#1f2937;font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;font-size:14px}}
.header{{position:sticky;top:0;z-index:10;background:#0052d9;color:#fff;padding:14px 20px;font-weight:700;box-shadow:0 2px 8px rgba(0,0,0,.15)}}
.header h1{{margin:0;font-size:17px;letter-spacing:0.5px}}
.meta{{font-weight:400;font-size:12px;opacity:.88;margin-top:4px}}
.chat{{max-width:860px;margin:0 auto;padding:16px 12px 32px}}
.day{{text-align:center;color:#6b7280;font-size:12px;margin:18px 0 10px}}
.day span{{background:#e5e7eb;border-radius:12px;padding:3px 12px;font-weight:500}}
.msg{{display:flex;align-items:flex-start;gap:10px;margin:12px 0}}
.msg.sent{{flex-direction:row-reverse}}
.avatar{{width:38px;height:38px;border-radius:8px;background:#3b82f6;color:#fff;display:flex;align-items:center;justify-content:center;font-weight:700;flex:0 0 38px;font-size:15px;box-shadow:0 1px 3px rgba(0,0,0,.1)}}
.msg.sent .avatar{{background:#0052d9}}
.body{{max-width:72%}}
.sender{{font-size:12px;color:#4b5563;margin:0 0 4px 2px}}
.msg.sent .sender{{text-align:right;margin-right:2px}}
.bubble{{white-space:pre-wrap;word-break:break-word;line-height:1.6;background:#fff;border-radius:8px;padding:10px 14px;box-shadow:0 1px 3px rgba(0,0,0,.06);border:1px solid #e5e7eb}}
.msg.sent .bubble{{background:#c8e6c9;border-color:#a5d6a7;color:#1b5e20}}
.type{{font-size:11px;color:#9ca3af;margin-top:3px}}
.msg.sent .type{{text-align:right}}
</style>
</head>
<body>
<div class="header">
  <h1>{title}</h1>
  <div class="meta">{meta}</div>
</div>
<div class="chat">
{body}
</div>
</body>
</html>"""
        parts = []
        last_day = None
        is_group = conv.get("kind") == "群聊"
        for msg in messages:
            day = msg["time"][:10] if msg["time"] else ""
            if day and day != last_day:
                parts.append(f'<div class="day"><span>{escape(day)}</span></div>')
                last_day = day

            side = "sent" if msg["is_sent"] else "received"
            sender_label = ""
            if is_group or not msg["is_sent"]:
                sender_label = f'<div class="sender">{escape(msg["sender"])}</div>'
            initial = escape((msg["sender"] or "?")[0].upper())
            content = escape(msg["display_content"] or "")
            type_line = escape(f'{msg["type_name"]} · {msg["time"]}')
            parts.append(
                f'<div class="msg {side}">'
                f'<div class="avatar">{initial}</div>'
                f'<div class="body">{sender_label}'
                f'<div class="bubble">{content}</div>'
                f'<div class="type">{type_line}</div>'
                f'</div></div>'
            )

        meta = f'{conv.get("kind", "")} · {len(messages)} 条消息 · {conv["conversation_id"]}'
        with open(path, "w", encoding="utf-8") as f:
            f.write(
                template.format(
                    title=escape(conv["display_name"]),
                    meta=escape(meta),
                    body="\n".join(parts),
                )
            )

    @staticmethod
    def _write_json(path: str, conv: Dict[str, Any], messages: List[Dict[str, Any]]) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "conversation": conv,
                    "message_count": len(messages),
                    "exported_at": datetime.now().isoformat(),
                    "messages": messages,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )

    @staticmethod
    def _write_csv(path: str, messages: List[Dict[str, Any]]) -> None:
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow([
                "时间", "会话", "会话ID", "发送者", "发送者ID", "消息类型",
                "内容", "message_id", "server_id", "sequence", "flag",
            ])
            for msg in messages:
                writer.writerow([
                    msg["time"],
                    msg["conversation_name"],
                    msg["conversation_id"],
                    msg["sender"],
                    msg["sender_id"],
                    msg["type_name"],
                    msg["display_content"],
                    msg["message_id"],
                    msg["server_id"],
                    msg["sequence"],
                    msg["flag"],
                ])

    @staticmethod
    def _write_plain_text(path: str, conv: Dict[str, Any], messages: List[Dict[str, Any]]) -> None:
        lines = [
            f"会话: {conv['display_name']} ({conv.get('kind', '')})",
            f"会话ID: {conv['conversation_id']}",
            f"消息数: {len(messages)}",
            "=" * 60,
            "",
        ]
        for m in messages:
            lines.append(f"[{m['time']}] {m['sender']} ({m['type_name']}):")
            lines.append(f"  {m['display_content']}")
            lines.append("")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))


# =====================================================================
# 终端格式化输出与交互式 CLI
# =====================================================================

class Colors:
    """ANSI 颜色样式控制"""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    UNDERLINE = "\033[4m"

    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"

    BG_BLUE = "\033[44m"
    BG_GREEN = "\033[42m"


def _supports_color() -> bool:
    """检测终端是否支持颜色输出"""
    if os.environ.get("NO_COLOR"):
        return False
    if sys.platform == "win32":
        return os.environ.get("WT_SESSION") is not None or "ANSICON" in os.environ
    return sys.stdout.isatty()


def _color(text: str, color_code: str) -> str:
    if not _supports_color():
        return text
    return f"{color_code}{text}{Colors.RESET}"


def cmd_status(reader: WXWorkReader, args: argparse.Namespace) -> int:
    """CLI: 查看数据库状态"""
    info = reader.status()
    print("=" * 60)
    print(_color("  🏢 企业微信数据状态诊断 (WXWork Status)", Colors.BOLD + Colors.CYAN))
    print("=" * 60)
    print(f"解密目录: {_color(info['decrypted_dir'], Colors.GREEN)}")
    print(f"登录账号 ID: {info['self_id'] or '未检测到'}")
    print("\n数据库文件状态:")

    for db_name, item in info["databases"].items():
        status_str = _color("[存在]", Colors.GREEN) if item["exists"] else _color("[缺失]", Colors.RED)
        details = ""
        if item["exists"]:
            if "user_count" in item:
                details = f"({item['user_count']} 位联系人)"
            elif "conversation_count" in item:
                details = f"({item['conversation_count']} 个会话)"
            elif "message_count" in item:
                details = f"({item['message_count']} 条消息)"
        print(f"  • {db_name:<12} {status_str} {details}")
        print(f"    路径: {item['path']}")

    if not info["is_ready"]:
        print(_color("\n[!] 提示: 未检测到解密的数据库文件。", Colors.YELLOW))
        print("    请确保在 Windows 上运行企业微信后，使用 decrypt_wxwork_db.py 完成解密。")
        return 1
    return 0


def cmd_list_chats(reader: WXWorkReader, args: argparse.Namespace) -> int:
    """CLI: 列出会话"""
    convs = reader.get_conversations(
        kind=args.kind,
        search=args.search,
        sort_by=args.sort,
        limit=args.limit,
    )

    if not convs:
        print("未找到匹配的企业微信会话。")
        return 0

    print("=" * 85)
    print(_color(f"  🏢 企业微信会话列表 (共 {len(convs)} 个)", Colors.BOLD + Colors.CYAN))
    print("=" * 85)
    print(f"{'序号':<4} {'类型':<8} {'消息数':<8} {'最后活跃时间':<20} {'会话名称/ID'}")
    print("-" * 85)

    for idx, c in enumerate(convs, 1):
        kind_color = Colors.BLUE if c["kind"] == "群聊" else Colors.GREEN
        kind_tag = _color(f"[{c['kind']}]", kind_color)
        count_str = _color(f"{c['message_count']:>5}", Colors.YELLOW)
        time_str = c["last_time_str"] or "-"
        name_str = _color(c["display_name"], Colors.BOLD)
        cid_str = _color(f"({c['conversation_id']})", Colors.DIM)
        print(f"{idx:<4} {kind_tag:<14} {count_str:<14} {time_str:<20} {name_str} {cid_str}")

    return 0


def cmd_contacts(reader: WXWorkReader, args: argparse.Namespace) -> int:
    """CLI: 查看/搜索联系人"""
    contacts = reader.get_contacts(search=args.search)
    if not contacts:
        print("未找到联系人。")
        return 0

    print("=" * 85)
    print(_color(f"  👥 企业微信联系人列表 (共 {len(contacts)} 位)", Colors.BOLD + Colors.CYAN))
    print("=" * 85)
    print(f"{'用户 ID':<15} {'姓名/备注':<20} {'所属企业/职位':<25} {'账号'}")
    print("-" * 85)

    for u in contacts[: args.limit]:
        uid_str = str(u["user_id"])
        name_str = _color(u["display_name"], Colors.BOLD)
        corp = u["external_corp_name"]
        if u["external_job"]:
            corp = f"{corp} · {u['external_job']}" if corp else u["external_job"]
        corp_str = corp or "(内部员工)"
        acc_str = u["account"] or "-"
        print(f"{uid_str:<15} {name_str:<25} {corp_str:<25} {acc_str}")

    if len(contacts) > args.limit:
        print(_color(f"\n... 仅展示前 {args.limit} 位，使用 --limit 查看更多", Colors.DIM))
    return 0


def cmd_read(reader: WXWorkReader, args: argparse.Namespace) -> int:
    """CLI: 阅读会话聊天记录"""
    conv = reader.get_conversation(args.chat)
    if not conv:
        print(_color(f"[!] 找不到会话: {args.chat}", Colors.RED))
        return 1

    messages = reader.get_messages(
        conv["conversation_id"],
        start_time=args.since,
        end_time=args.until,
        limit=args.limit,
        reverse=args.reverse,
    )

    print("=" * 80)
    print(_color(f"  💬 会话: {conv['display_name']} [{conv['kind']}]", Colors.BOLD + Colors.CYAN))
    print(f"  会话 ID: {conv['conversation_id']} | 消息总数: {len(messages)}")
    print("=" * 80)

    last_day = None
    for m in messages:
        day = m["time"][:10] if m["time"] else ""
        if day and day != last_day:
            print(_color(f"\n  ──────── 📅 {day} ────────", Colors.DIM + Colors.YELLOW))
            last_day = day

        sender_color = Colors.GREEN if m["is_sent"] else Colors.BLUE
        sender_name = _color(f"[{m['sender']}]", sender_color + Colors.BOLD)
        time_tag = _color(m["time"][11:] if len(m["time"]) >= 16 else m["time"], Colors.DIM)
        type_tag = _color(f"({m['type_name']})", Colors.MAGENTA) if m["content_type"] not in (0, 2) else ""

        print(f"\n{sender_name} {time_tag} {type_tag}")
        for line in m["display_content"].splitlines():
            print(f"  {line}")

    if args.export:
        out_file = reader.export_chat(conv["conversation_id"], format=args.export)
        print(_color(f"\n[+] 聊天记录已导出至: {out_file}", Colors.GREEN))

    return 0


def cmd_search(reader: WXWorkReader, args: argparse.Namespace) -> int:
    """CLI: 全局搜索消息"""
    results = reader.search_messages(
        keyword=args.keyword,
        conversation_id=args.chat,
        start_time=args.since,
        end_time=args.until,
        limit=args.limit,
    )

    if not results:
        print(_color(f"未找到包含关键词 '{args.keyword}' 的消息。", Colors.YELLOW))
        return 0

    print("=" * 85)
    print(_color(f"  🔍 关键词 '{args.keyword}' 搜索结果 (共 {len(results)} 条)", Colors.BOLD + Colors.CYAN))
    print("=" * 85)

    for idx, m in enumerate(results, 1):
        conv_tag = _color(f"[{m['conversation_name']}]", Colors.CYAN)
        sender_tag = _color(m["sender"], Colors.BOLD)
        time_tag = _color(m["time"], Colors.DIM)
        print(f"\n{idx}. {conv_tag} {sender_tag} · {time_tag}")

        content = m["display_content"]
        # 关键词高亮
        if _supports_color():
            pattern = re.compile(re.escape(args.keyword), re.IGNORECASE)
            content = pattern.sub(lambda match: _color(match.group(0), Colors.BG_GREEN + Colors.BOLD), content)
        for line in content.splitlines():
            print(f"   {line}")

    return 0


def cmd_stats(reader: WXWorkReader, args: argparse.Namespace) -> int:
    """CLI: 数据统计"""
    stats = reader.get_statistics()
    print("=" * 60)
    print(_color("  📊 企业微信数据概览与统计", Colors.BOLD + Colors.CYAN))
    print("=" * 60)
    print(f"会话总数:     {_color(str(stats['total_conversations']), Colors.BOLD + Colors.GREEN)}")
    print(f"消息总数:     {_color(str(stats['total_messages']), Colors.BOLD + Colors.YELLOW)}")
    print(f"联系人总数:   {stats['total_contacts']} (内部: {stats['internal_contacts']}, 外部: {stats['external_contacts']})")

    print("\n会话类型分布:")
    for kind, count in stats["conversation_kinds"].items():
        print(f"  • {kind:<10}: {count:>5} 个")

    print("\n🔥 最活跃会话 Top 10:")
    for idx, c in enumerate(stats["top_conversations"], 1):
        print(f"  {idx:>2}. {c['name']:<25} ({c['kind']}) - {c['message_count']} 条消息")

    return 0


def cmd_export(reader: WXWorkReader, args: argparse.Namespace) -> int:
    """CLI: 导出数据"""
    if args.all:
        convs = reader.get_conversations()
        out_dir = args.out_dir or "wxwork_export"
        os.makedirs(out_dir, exist_ok=True)
        print(f"正在导出全部 {len(convs)} 个会话至 {out_dir} ...")
        formats = [f.strip() for f in args.format.split(",") if f.strip()]
        for c in convs:
            for fmt in formats:
                reader.export_chat(c["conversation_id"], format=fmt)
        print(_color("[+] 导出完成！", Colors.GREEN))
        return 0

    if not args.chat:
        print(_color("[!] 请指定会话 --chat <ID/名称> 或使用 --all 导出全部", Colors.RED))
        return 1

    conv = reader.get_conversation(args.chat)
    if not conv:
        print(_color(f"[!] 找不到会话: {args.chat}", Colors.RED))
        return 1

    formats = [f.strip() for f in args.format.split(",") if f.strip()]
    for fmt in formats:
        out_file = reader.export_chat(conv["conversation_id"], output_path=args.output, format=fmt)
        print(_color(f"[+] 已导出 ({fmt}): {out_file}", Colors.GREEN))
    return 0


def cmd_interactive(reader: WXWorkReader, args: argparse.Namespace) -> int:
    """CLI: 交互式浏览控制台"""
    print("=" * 60)
    print(_color("  🏢 企业微信交互式控制台", Colors.BOLD + Colors.CYAN))
    print("=" * 60)

    while True:
        print("\n请选择操作:")
        print("  1. 浏览会话列表 (list)")
        print("  2. 查看联系人 (contacts)")
        print("  3. 阅读指定会话 (read)")
        print("  4. 全局搜索关键词 (search)")
        print("  5. 查看数据统计看板 (stats)")
        print("  0. 退出 (quit)")

        try:
            choice = input("\n请输入选项 [0-5]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if choice in ("0", "q", "quit", "exit"):
            break
        elif choice == "1":
            ns = argparse.Namespace(kind=None, search=None, sort="last_time", limit=20)
            cmd_list_chats(reader, ns)
        elif choice == "2":
            kw = input("输入联系人过滤词 (直接回车查看全部): ").strip()
            ns = argparse.Namespace(search=kw or None, limit=30)
            cmd_contacts(reader, ns)
        elif choice == "3":
            chat_kw = input("输入会话名称或会话 ID: ").strip()
            if chat_kw:
                ns = argparse.Namespace(
                    chat=chat_kw, since=None, until=None, limit=50, reverse=False, export=None
                )
                cmd_read(reader, ns)
        elif choice == "4":
            kw = input("输入要搜索的关键词: ").strip()
            if kw:
                ns = argparse.Namespace(keyword=kw, chat=None, since=None, until=None, limit=20)
                cmd_search(reader, ns)
        elif choice == "5":
            cmd_stats(reader, argparse.Namespace())
        else:
            print("无效输入，请重新选择。")

    print("已退出企业微信控制台。")
    return 0


# =====================================================================
# CLI 命令行入口解析
# =====================================================================

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="企业微信已解密数据库读取与检索工具 (Enterprise WeChat Reader)",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--db-dir", help="指定已解密的数据库目录 (包含 user.db, session.db, message.db)")
    parser.add_argument("--self-id", type=int, help="指定当前账号的用户 ID (用于标识'我')")

    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # status
    p_status = subparsers.add_parser("status", help="检查已解密数据库状态与数据量")

    # list / chats
    p_list = subparsers.add_parser("list", aliases=["chats"], help="列出会话列表")
    p_list.add_argument("--kind", help="按类型筛选: 群聊 / 单聊 / 微信联系人 / 应用/公众号")
    p_list.add_argument("--search", "-s", help="按会话名或 ID 搜索")
    p_list.add_argument("--sort", choices=["last_time", "message_count", "name"], default="last_time", help="排序方式")
    p_list.add_argument("--limit", "-n", type=int, default=30, help="最多显示条数 (默认 30)")

    # contacts
    p_contacts = subparsers.add_parser("contacts", help="列出/搜索联系人")
    p_contacts.add_argument("--search", "-s", help="联系人搜索关键词")
    p_contacts.add_argument("--limit", "-n", type=int, default=50, help="最多显示条数 (默认 50)")

    # read
    p_read = subparsers.add_parser("read", aliases=["show"], help="阅读会话聊天记录")
    p_read.add_argument("chat", help="会话 ID 或会话名称关键词")
    p_read.add_argument("--limit", "-n", type=int, default=100, help="读取消息条数 (默认 100)")
    p_read.add_argument("--since", help="起始时间 (YYYY-MM-DD 或 YYYY-MM-DD HH:MM:SS)")
    p_read.add_argument("--until", help="截止时间")
    p_read.add_argument("--reverse", action="store_true", help="倒序排列")
    p_read.add_argument("--export", choices=["md", "html", "json", "csv", "txt"], help="阅读同时导出到文件")

    # search
    p_search = subparsers.add_parser("search", help="全局消息全文检索")
    p_search.add_argument("keyword", help="搜索关键词")
    p_search.add_argument("--chat", help="限制在指定会话内搜索")
    p_search.add_argument("--since", help="起始时间")
    p_search.add_argument("--until", help="截止时间")
    p_search.add_argument("--limit", "-n", type=int, default=50, help="最多返回条数 (默认 50)")

    # stats
    p_stats = subparsers.add_parser("stats", help="数据统计看板与活跃排行")

    # export
    p_export = subparsers.add_parser("export", help="导出聊天记录")
    p_export.add_argument("--chat", help="指定导出的会话 ID 或名称")
    p_export.add_argument("--all", action="store_true", help="导出全部会话")
    p_export.add_argument("--format", default="markdown", help="导出格式: markdown,html,json,csv (逗号分隔)")
    p_export.add_argument("--output", "-o", help="输出文件路径 (仅用于单会话)")
    p_export.add_argument("--out-dir", help="批量导出时的输出文件夹")

    # interactive
    p_inter = subparsers.add_parser("interactive", aliases=["ui", "repl"], help="交互式控制台")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    reader = WXWorkReader(decrypted_dir=args.db_dir, self_id=args.self_id)

    if not args.command or args.command == "interactive":
        return cmd_interactive(reader, args)

    handlers = {
        "status": cmd_status,
        "list": cmd_list_chats,
        "chats": cmd_list_chats,
        "contacts": cmd_contacts,
        "read": cmd_read,
        "show": cmd_read,
        "search": cmd_search,
        "stats": cmd_stats,
        "export": cmd_export,
    }

    handler = handlers.get(args.command)
    if handler:
        return handler(reader, args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"执行出错: {exc}", file=sys.stderr)
        sys.exit(1)
