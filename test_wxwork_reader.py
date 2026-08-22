#!/usr/bin/env python3
"""
Unit tests for WXWorkReader (企业微信数据读取与检索工具)
"""

import os
import shutil
import sqlite3
import tempfile
import unittest

from wxwork_reader import WXWorkReader, decode_content, conversation_kind, main


class TestWXWorkReader(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.user_db = os.path.join(self.test_dir, "user.db")
        self.session_db = os.path.join(self.test_dir, "session.db")
        self.message_db = os.path.join(self.test_dir, "message.db")

        self._create_mock_user_db()
        self._create_mock_session_db()
        self._create_mock_message_db()

        self.reader = WXWorkReader(decrypted_dir=self.test_dir, self_id=10001)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_mock_user_db(self):
        conn = sqlite3.connect(self.user_db)
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE user_table (
                id INTEGER PRIMARY KEY,
                name TEXT,
                real_name TEXT,
                account TEXT,
                external_corp_name TEXT,
                external_job TEXT
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE external_user_relation_v3 (
                user_id INTEGER PRIMARY KEY,
                remarks TEXT,
                real_remarks TEXT,
                corp_remark TEXT
            )
            """
        )
        # 插入模拟用户
        cursor.execute(
            "INSERT INTO user_table VALUES (?, ?, ?, ?, ?, ?)",
            (10001, "admin", "张三", "zhangsan_acc", "", "技术总监"),
        )
        cursor.execute(
            "INSERT INTO user_table VALUES (?, ?, ?, ?, ?, ?)",
            (10002, "lisi", "李四", "lisi_acc", "腾讯科技", "产品经理"),
        )
        cursor.execute(
            "INSERT INTO user_table VALUES (?, ?, ?, ?, ?, ?)",
            (10003, "wangwu", "王五", "wangwu_acc", "", "销售经理"),
        )
        cursor.execute(
            "INSERT INTO external_user_relation_v3 VALUES (?, ?, ?, ?)",
            (10002, "李四-VIP客户", "李四-VIP客户", "腾讯科技"),
        )
        cursor.execute(
            "INSERT INTO external_user_relation_v3 VALUES (?, ?, ?, ?)",
            (10004, "外部赵六", "外部赵六", "阿里巴巴"),
        )
        conn.commit()
        conn.close()

    def _create_mock_session_db(self):
        conn = sqlite3.connect(self.session_db)
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE conversation_table (
                id TEXT PRIMARY KEY,
                name TEXT,
                roomname_remark TEXT,
                last_message_time INTEGER,
                last_message_id INTEGER,
                con_numeric_id INTEGER
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE conversation_user_table (
                conversation_id TEXT,
                user_id INTEGER,
                nick_name TEXT
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE conversation_member_nickname_table (
                room_id INTEGER,
                userid INTEGER,
                nickname TEXT
            )
            """
        )

        cursor.execute(
            "INSERT INTO conversation_table VALUES (?, ?, ?, ?, ?, ?)",
            ("R:10000000000001", "核心研发项目组", "核心研发群(内部)", 1700000100, 10, 501),
        )
        cursor.execute(
            "INSERT INTO conversation_table VALUES (?, ?, ?, ?, ?, ?)",
            ("S:10001_10002", "", "", 1700000200, 20, 0),
        )
        cursor.execute(
            "INSERT INTO conversation_table VALUES (?, ?, ?, ?, ?, ?)",
            ("M:10004", "微信客户对接", "", 1700000050, 5, 0),
        )

        cursor.execute(
            "INSERT INTO conversation_user_table VALUES (?, ?, ?)",
            ("R:10000000000001", 10001, "群主-张三"),
        )
        cursor.execute(
            "INSERT INTO conversation_user_table VALUES (?, ?, ?)",
            ("R:10000000000001", 10003, "销售-王五"),
        )
        conn.commit()
        conn.close()

    def _create_mock_message_db(self):
        conn = sqlite3.connect(self.message_db)
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE message_table (
                message_id INTEGER PRIMARY KEY,
                server_id INTEGER,
                sequence INTEGER,
                sender_id INTEGER,
                conversation_id TEXT,
                content_type INTEGER,
                send_time INTEGER,
                flag INTEGER,
                content BLOB,
                extra_content BLOB,
                local_extra_content BLOB
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE message_small_table (
                message_id INTEGER PRIMARY KEY,
                server_id INTEGER,
                sequence INTEGER,
                sender_id INTEGER,
                conversation_id TEXT,
                content_type INTEGER,
                send_time INTEGER,
                flag INTEGER,
                content BLOB,
                extra_content BLOB,
                local_extra_content BLOB
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE kf_message_tableV1 (
                message_id INTEGER PRIMARY KEY,
                server_id INTEGER,
                sequence INTEGER,
                sender_id INTEGER,
                conversation_id TEXT,
                content_type INTEGER,
                send_time INTEGER,
                flag INTEGER,
                content BLOB,
                extra_content BLOB,
                local_extra_content BLOB
            )
            """
        )

        # 插入消息
        # 1. 群聊文本消息
        cursor.execute(
            "INSERT INTO message_table VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (1, 101, 1, 10003, "R:10000000000001", 0, 1700000010, 0, "王五发起的项目开工通知".encode("utf-8"), None, None),
        )
        # 2. 群聊张三回复 (我)
        cursor.execute(
            "INSERT INTO message_table VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (2, 102, 2, 10001, "R:10000000000001", 0, 1700000020, 0, "收到，已安排研发对接".encode("utf-8"), None, None),
        )
        # 3. 单聊消息
        cursor.execute(
            "INSERT INTO message_table VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (3, 103, 1, 10002, "S:10001_10002", 0, 1700000200, 0, "请问下周可以安排商务洽谈吗？".encode("utf-8"), None, None),
        )
        # 4. 微信联系人消息
        cursor.execute(
            "INSERT INTO message_table VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (4, 104, 1, 10004, "M:10004", 4, 1700000050, 0, None, None, None),
        )
        conn.commit()
        conn.close()

    def test_status(self):
        status = self.reader.status()
        self.assertTrue(status["is_ready"])
        self.assertEqual(status["self_id"], 10001)
        self.assertTrue(status["databases"]["user.db"]["exists"])
        self.assertEqual(status["databases"]["user.db"]["user_count"], 3)
        self.assertEqual(status["databases"]["session.db"]["conversation_count"], 3)
        self.assertEqual(status["databases"]["message.db"]["message_count"], 4)

    def test_contacts(self):
        contacts = self.reader.get_contacts()
        self.assertGreaterEqual(len(contacts), 3)

        contact_map = {c["user_id"]: c for c in contacts}
        self.assertIn(10001, contact_map)
        self.assertEqual(contact_map[10001]["real_name"], "张三")

        # 外部联系人备注覆盖
        self.assertIn(10002, contact_map)
        self.assertEqual(contact_map[10002]["display_name"], "李四-VIP客户")
        self.assertTrue(contact_map[10002]["is_external"])

        # 搜索联系人
        searched = self.reader.get_contacts(search="王五")
        self.assertEqual(len(searched), 1)
        self.assertEqual(searched[0]["user_id"], 10003)

        # 单个查询
        u = self.reader.get_contact(10001)
        self.assertIsNotNone(u)
        self.assertEqual(u["name"], "admin")

    def test_conversations(self):
        convs = self.reader.get_conversations()
        self.assertEqual(len(convs), 3)

        conv_map = {c["conversation_id"]: c for c in convs}
        # 群聊
        self.assertIn("R:10000000000001", conv_map)
        r_conv = conv_map["R:10000000000001"]
        self.assertEqual(r_conv["kind"], "群聊")
        self.assertEqual(r_conv["display_name"], "核心研发群(内部)")
        self.assertEqual(r_conv["message_count"], 2)

        # 单聊
        self.assertIn("S:10001_10002", conv_map)
        s_conv = conv_map["S:10001_10002"]
        self.assertEqual(s_conv["kind"], "单聊")
        self.assertEqual(s_conv["display_name"], "李四-VIP客户")

        # 模糊查找
        c = self.reader.get_conversation("核心研发")
        self.assertIsNotNone(c)
        self.assertEqual(c["conversation_id"], "R:10000000000001")

    def test_messages(self):
        msgs = self.reader.get_messages("R:10000000000001")
        self.assertEqual(len(msgs), 2)

        # 第一条: 王五群昵称
        self.assertEqual(msgs[0]["sender"], "销售-王五")
        self.assertIn("项目开工通知", msgs[0]["display_content"])
        self.assertFalse(msgs[0]["is_sent"])

        # 第二条: 张三 (我)
        self.assertEqual(msgs[1]["sender"], "我")
        self.assertTrue(msgs[1]["is_sent"])
        self.assertIn("已安排研发对接", msgs[1]["display_content"])

        # 时间过滤
        filtered = self.reader.get_messages("R:10000000000001", start_time=1700000015)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["message_id"], 2)

    def test_search_messages(self):
        # 全局搜索
        results = self.reader.search_messages("开工")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["conversation_id"], "R:10000000000001")

        results2 = self.reader.search_messages("商务洽谈")
        self.assertEqual(len(results2), 1)
        self.assertEqual(results2[0]["conversation_id"], "S:10001_10002")

        # 限定会话搜索
        results3 = self.reader.search_messages("开工", conversation_id="S:10001_10002")
        self.assertEqual(len(results3), 0)

    def test_statistics(self):
        stats = self.reader.get_statistics()
        self.assertEqual(stats["total_conversations"], 3)
        self.assertEqual(stats["total_messages"], 4)
        self.assertGreaterEqual(stats["total_contacts"], 3)
        self.assertEqual(stats["conversation_kinds"]["群聊"], 1)
        self.assertEqual(stats["conversation_kinds"]["单聊"], 1)

    def test_exports(self):
        # Markdown 导出
        md_file = os.path.join(self.test_dir, "export.md")
        self.reader.export_chat("R:10000000000001", output_path=md_file, format="markdown")
        self.assertTrue(os.path.exists(md_file))
        with open(md_file, "r", encoding="utf-8") as f:
            content = f.read()
            self.assertIn("# 会话: 核心研发群(内部)", content)
            self.assertIn("项目开工通知", content)

        # HTML 导出
        html_file = os.path.join(self.test_dir, "export.html")
        self.reader.export_chat("R:10000000000001", output_path=html_file, format="html")
        self.assertTrue(os.path.exists(html_file))
        with open(html_file, "r", encoding="utf-8") as f:
            content = f.read()
            self.assertIn("<title>核心研发群(内部)</title>", content)
            self.assertIn("bubble", content)

        # JSON 导出
        json_file = os.path.join(self.test_dir, "export.json")
        self.reader.export_chat("R:10000000000001", output_path=json_file, format="json")
        self.assertTrue(os.path.exists(json_file))

        # CSV 导出
        csv_file = os.path.join(self.test_dir, "export.csv")
        self.reader.export_chat("R:10000000000001", output_path=csv_file, format="csv")
        self.assertTrue(os.path.exists(csv_file))

    def test_cli_commands(self):
        # 测试 status 命令
        rc = main(["--db-dir", self.test_dir, "--self-id", "10001", "status"])
        self.assertEqual(rc, 0)

        # 测试 list 命令
        rc = main(["--db-dir", self.test_dir, "--self-id", "10001", "list"])
        self.assertEqual(rc, 0)

        # 测试 contacts 命令
        rc = main(["--db-dir", self.test_dir, "--self-id", "10001", "contacts"])
        self.assertEqual(rc, 0)

        # 测试 read 命令
        rc = main(["--db-dir", self.test_dir, "--self-id", "10001", "read", "核心研发"])
        self.assertEqual(rc, 0)

        # 测试 search 命令
        rc = main(["--db-dir", self.test_dir, "--self-id", "10001", "search", "开工"])
        self.assertEqual(rc, 0)

        # 测试 stats 命令
        rc = main(["--db-dir", self.test_dir, "--self-id", "10001", "stats"])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
