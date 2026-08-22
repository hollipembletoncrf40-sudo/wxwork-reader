# 🏢 WXWork Reader & Decryptor · 技术实现与逆向解密原理

本文档详细记录了企业微信（WeCom / WXWork）在 macOS 与 Windows 平台上的本地数据存储架构、加密机制、内存密钥嗅探算法以及 Protobuf 二进制消息反序列化实现。

---

## 1. 企业微信本地存储架构 (macOS)

企业微信在 macOS 上的数据存储位于沙盒容器路径：
`~/Library/Containers/com.tencent.WeWorkMac/Data/Documents/Profiles/<Profile_Hex_ID>/`

### 核心数据库分布

| 数据库文件名 | 存储内容 | 加密方式 | 解密后映射 |
| :--- | :--- | :--- | :--- |
| `Messages1/Info.db` (25 MB) | 全部群聊与单聊消息明细、消息正文 Blob、富文本卡片、图片引用 | wxSQLite3 AES-128-CBC | `message.db` |
| `Messages1/Session.db` (2.8 MB) | 会话列表、组织架构用户表 (`USER`)、部门表 (`DEPARTMENT`) | wxSQLite3 AES-128-CBC | `session.db` |
| `Contact/Contact.db` (262 KB) | 外部企业联系人、企业主体列表 (`CORPINFO`) | wxSQLite3 AES-128-CBC | `user.db` |
| `Openapi/Openapi.db` (589 KB) | 自建应用、第三方应用与提醒通知 | wxSQLite3 AES-128-CBC | `Openapi.db` |
| `CustomerMessage/customer_message.db` | 外部微信客户对话消息 | wxSQLite3 AES-128-CBC | `customer_message.db` |
| `conv_snapshot` (360 KB) | 运行时的会话列表轻量级 Protobuf 二进制快照（未加密） | 裸 Protobuf Stream | - |

---

## 2. wxSQLite3 AES-128-CBC 加密算法原理

企业微信对 SQLite 数据库采用 `wxSQLite3` 标准的 AES-128-CBC 页面加密（每个页面 4096 字节）。

### 页面结构与密钥推导

1. **Page 1 特征**：
   - 字节 `16..23` 包含原始明文 SQLite Header 片段校验码（`PageSize` 高低字节、保留标志 `0x40 0x20 0x20`）；
   - 解密时将字节 `16..23` 替换为 `8..15`，对其余 4080 字节执行 AES-128-CBC 解密；
   - 解密后前 8 字节必须与备份的 Header 片段完全一致，否则判定密钥错误；
   - 验证通过后，将前 16 字节还原为标准的 `"SQLite format 3\x00"`。

2. **页面独立密钥推导**：
   每个页面使用独立的 16 字节派生密钥：
   $$\text{PageKey} = \text{MD5}(\text{RawKey} \,\|\, \text{PageNo}_{\text{LE32}} \,\|\, \text{"sAlT"})$$

3. **非线性同余 IV 发生器**：
   每个页面使用唯一的 16 字节初始向量 IV，基于页面号通过非线性同余算法计算后进行 MD5 哈希：
   $$\text{IV} = \text{MD5}(\text{InitKey}(z))$$

---

## 3. macOS 内存密钥嗅探算法 (`find_wxwork_keys_macos.c`)

在 macOS 上，企业微信运行时将 16 字节的原始 AES 密钥以结构体形式保存在堆内存中。

### 嗅探流程

```text
1. 获取 WXWork 进程 PID (pgrep -x 企业微信)
2. 调用 task_for_pid(mach_task_self(), pid, &task) 获取 Mach 任务端口
3. 循环遍历 mach_vm_region，过滤出可读写的堆内存区域 (VM_PROT_READ | VM_PROT_WRITE)
4. 调用 mach_vm_read 批量读取内存块 (4MB 分块)
5. 针对内存中每个 4 字节对齐的 16 字节候选缓冲：
   - 使用 Apple 原生硬件 CommonCrypto (CCCrypt) 尝试解密目标 DB Page 1
   - 校验 Header Fragment 与 B-Tree 节点类型 (0x02, 0x05, 0x0A, 0x0D)
6. 毫秒级命中真实密钥后，直接在底层完成全量数据库解密
```

---

## 4. Protobuf 二进制消息反序列化 (`wxwork_reader.py`)

企业微信的聊天消息、富文本卡片、图片引用与群设置采用 Protobuf 二进制流压缩存储：
- 通过递归解析 Varint (Tag / Length / WireFormat)；
- 提取 WireType=2 (Length-delimited) 的 UTF-8 字符串；
- 过滤乱码控制字符与系统 Token，提取真实人类可读的文字对话与协作文档 URL。
