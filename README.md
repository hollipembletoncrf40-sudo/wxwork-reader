# 🏢 WXWork Reader & Decryptor (企业微信数据提取与全量解密工具)

一款专为 macOS 与 Windows 设计的企业微信（WeCom / WXWork）本地数据库内存密钥嗅探、wxSQLite3 AES-128-CBC 数据库解密、Protobuf 消息解析、组织架构通讯录导出、各业务群对接责任人速查手册及全量群聊聊天记录导出工具。

---

## 📚 详细文档导航

| 文档名称 | 内容描述 | 快速链接 |
| :--- | :--- | :--- |
| **工作对接责任人与业务 SOP 手册** | 详细记录 17+ 业务群找谁、谁负责什么、以及问题提报规范 | [📘 查看责任人手册](docs/WORK_RESPONSIBILITY_AND_SOP_HANDBOOK.md) |
| **技术架构与逆向解密原理** | wxSQLite3 AES-128-CBC、Mach 内核内存扫描、Protobuf 反序列化 | [🔬 查看技术原理](docs/ARCHITECTURE_AND_CRYPTO.md) |
| **命令行与 Python API 使用指南** | 全指令参数详解、终端交互 REPL、Python 库调用示例 | [🛠️ 查看 API 指南](docs/CLI_AND_API_GUIDE.md) |

---

## ✨ 核心特性

- 🔑 **内存密钥嗅探 (macOS Native)**：利用 macOS Mach 内核 API 与 Apple 原生硬件加密引擎（`CommonCrypto`），毫秒级扫描运行中进程内存并提取真实数据库 AES 密钥。
- 🔓 **wxSQLite3 数据库解密**：原生还原 `wxSQLite3` AES-128-CBC 页面密钥推导与 IV 生成算法，直接解密 `Info.db` (消息)、`Session.db` (会话/通讯录)、`Contact.db` (企业信息) 等。
- 📦 **Protobuf 二进制解码**：深度解析企业微信消息内容、富文本卡片、图片引用与群设置。
- 👥 **全量通讯录导出**：支持一键将企业组织架构、员工姓名、岗位、工作邮箱、手机号导出为 UTF-8-BOM CSV (Excel兼容)、Markdown 文档及可视化检索单页 (HTML)。
- 💬 **全量群聊与私聊导出**：支持导出按日期时间归类的 Markdown 历史对话与交互式 Web 浏览面板。
- ⚡ **零第三方依赖**：纯 Python 标准库 + 原生 C 语言编写，不依赖任何第三方重量级外部库。

---

## 🏗️ 架构设计

```text
┌────────────────────────────────────────────────────────┐
│             运行中的企业微信 (WXWork Process)          │
│                      (PID / 堆内存)                    │
└───────────────────────────┬────────────────────────────┘
                            │ (mach_vm_read / task_for_pid)
                            ▼
┌────────────────────────────────────────────────────────┐
│     find_wxwork_keys_macos (C + CommonCrypto)          │
│      • 原始 16-Byte AES 密钥扫描与 Page1 特征匹配      │
│      • 毫秒级解密生成 wxwork_decrypted/ 数据库         │
└───────────────────────────┬────────────────────────────┘
                            ▼
┌────────────────────────────────────────────────────────┐
│             wxwork_reader.py / 核心解析库               │
│      • Protobuf Varint/Wire-Format 消息解码            │
│      • USER ↔ CONVERSATION ↔ MESSAGE 跨表映射关联      │
└─────────────┬───────────────────────────┬──────────────┘
              ▼                           ▼
┌───────────────────────────┐ ┌──────────────────────────┐
│   export_full_history.py  │ │    export_contacts.py    │
│  • 102+ 群聊 Markdown 记录│ │  • 3500+ 联系人 CSV 表格 │
│  • 2.5万+ 真实对话时间轴  │ │  • 部门组织架构 Markdown │
│  • index.html 检索单页    │ │  • 实时搜索面板 HTML     │
└───────────────────────────┘ └──────────────────────────┘
```

---

## 🚀 快速上手 (macOS)

### 1. 编译内存密钥扫描器

```bash
make
# 或者: clang -O3 -o find_wxwork_keys_macos find_wxwork_keys_macos.c -framework Foundation -Wno-deprecated-declarations
```

### 2. 嗅探密钥并自动解密数据库

确保企业微信处于登录运行状态，在终端中执行：

```bash
sudo ./find_wxwork_keys_macos $(pgrep -x 企业微信)
```

> **说明**：程序会在 1~2 秒内完成内存扫描，命中密钥后将自动解密生成 `wxwork_decrypted/` 目录中的 SQLite 数据库。

### 3. 一键导出全量聊天记录与通讯录

```bash
# 导出全量群聊历史记录 (Markdown / HTML) 至桌面
python3 export_full_history.py

# 导出企业通讯录 (CSV / Markdown / HTML) 至桌面
python3 export_contacts.py
```

---

## 🛠️ CLI 命令行工具常用示例

```bash
# 1. 查看数据库状态诊断
python3 wxwork_reader.py status

# 2. 列出最活跃的 30 个会话
python3 wxwork_reader.py chats --limit 30 --sort-by messages

# 3. 检索通讯录联系人
python3 wxwork_reader.py contacts --search "销售助理"

# 4. 读取指定群聊的详细对话
python3 wxwork_reader.py read "SMT工程 & 外贸" --limit 50

# 5. 全文检索关键词
python3 wxwork_reader.py search "发货"

# 6. 数据概览与统计
python3 wxwork_reader.py stats

# 7. 启动终端交互式浏览模式
python3 wxwork_reader.py interactive
```

---

## 🧪 单元测试

本项目自带完整的单元测试套件：

```bash
make test
# 或
python3 test_wxwork_reader.py
```

---

## ⚖️ 声明与协议

- 本项目仅供学习、数据备份及内部办公归档使用。
- 请遵守相关法律法规，请勿将本工具用于未经授权的数据抓取或侵犯隐私的行为。
- 基于 **MIT License** 开源。
