# 🛠️ WXWork Reader & Decryptor · 命令行与 Python API 使用手册

---

## 1. CLI 命令行使用指南

### 1.1 数据状态诊断 (`status`)
查看解密目录路径、数据库存在性及消息与用户统计：
```bash
python3 wxwork_reader.py status
```

### 1.2 会话列表查询 (`chats` / `list`)
列出所有群聊与私聊会话（支持按消息量、活跃时间排序与关键词过滤）：
```bash
# 列出前 30 个最活跃的会话
python3 wxwork_reader.py chats --limit 30 --sort-by messages

# 筛选群聊
python3 wxwork_reader.py chats --type group

# 搜索包含 "SMT" 的群聊
python3 wxwork_reader.py chats --search "SMT"
```

### 1.3 通讯录联系人检索 (`contacts`)
```bash
# 搜索联系人（支持姓名、岗位、邮箱、手机）
python3 wxwork_reader.py contacts --search "销售助理"

# 查看详细联系人列表
python3 wxwork_reader.py contacts --limit 50
```

### 1.4 读取与查看聊天记录 (`read` / `show`)
```bash
# 读取指定群聊的最新 50 条消息
python3 wxwork_reader.py read "SMT工程 & 外贸" --limit 50

# 按时间倒序或正序查看
python3 wxwork_reader.py read "外贸发货&物流沟通" --order asc
```

### 1.5 全局消息全文搜索 (`search`)
```bash
# 跨所有群聊全文搜索 "加急发货"
python3 wxwork_reader.py search "加急发货" --limit 20
```

### 1.6 数据概览与统计 (`stats`)
```bash
# 查看会话类型分布与 Top 10 最活跃群聊
python3 wxwork_reader.py stats
```

### 1.7 终端交互式 REPL 模式 (`interactive` / `repl`)
```bash
# 启动类似终端面板的交互式浏览工具
python3 wxwork_reader.py interactive
```

---

## 2. 导出管道工具

### 2.1 全量群聊记录导出
```bash
python3 export_full_history.py
```
- 输出目录：`~/Desktop/企业微信全量聊天记录/`
- 输出格式：独立的 Markdown 群聊文档、总览索引 `00_概览汇总.md` 以及可视化检索单页 `index.html`。

### 2.2 全量通讯录导出
```bash
python3 export_contacts.py
```
- 输出目录：`~/Desktop/企业微信通讯录与联系人/`
- 输出格式：带 UTF-8-BOM 的 Excel CSV 表格、部门组织架构 Markdown 文档与可视化搜索面板。

---

## 3. Python API 编程调用示例

```python
from wxwork_reader import WXWorkReader

# 初始化解析器
reader = WXWorkReader(decrypted_dir="wxwork_decrypted_user")

# 1. 获取所有联系人
contacts = reader.get_contacts(search="销售")
for c in contacts:
    print(f"{c['name']} - {c['job']} - {c['email']}")

# 2. 获取所有会话列表
sessions = reader.get_sessions(sort_by="messages", limit=10)
for s in sessions:
    print(f"[{s.display_type}] {s.name} ({s.message_count} 条消息)")

# 3. 读取指定群聊的消息
messages = reader.get_messages(target="外贸发货&物流沟通", limit=30)
for m in messages:
    print(f"[{m.time_str}] {m.sender_name}: {m.content}")

# 4. 全局全文检索
results = reader.search_messages("极性修改", limit=10)
for r in results:
    print(f"[{r['session_name']}] {r['time_str']} {r['sender_name']}: {r['content']}")
```
