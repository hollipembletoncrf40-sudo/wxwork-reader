#!/usr/bin/env python3
"""
macOS 企业微信数据库解密与全量导出工具 (采用 macOS 原生 CommonCrypto，无需安装任何第三方库)
"""

import argparse
import ctypes
import glob
import json
import os
import shutil
import sqlite3
import struct
import sys

PAGE_SZ = 4096
SQLITE_HDR = b"SQLite format 3\x00"

# 加载 macOS 原生 CommonCrypto
_lib = ctypes.CDLL("/usr/lib/libSystem.B.dylib")

def _md5(b):
    out = (ctypes.c_uint8 * 16)()
    _lib.CC_MD5(b, len(b), out)
    return bytes(out)

def _aes_decrypt_cbc(key, iv, data):
    out = (ctypes.c_uint8 * len(data))()
    moved = ctypes.c_size_t(0)
    # kCCDecrypt = 1, kCCAlgorithmAES128 = 0, kCCOptionPKCS7Padding = 0
    res = _lib.CCCrypt(1, 0, 0, key, len(key), iv, data, len(data), out, len(out), ctypes.byref(moved))
    if res != 0:
        raise ValueError(f"CCCrypt failed: {res}")
    return bytes(out)[: moved.value]

def _modmult(a, b, c, m, s):
    q = s // a
    s = b * (s - a * q) - c * q
    if s < 0:
        s += m
    return s

def generate_initial_vector(page_no):
    z = page_no + 1
    initkey = bytearray(16)
    for idx in range(4):
        z = _modmult(52774, 40692, 3791, 2147483399, z)
        initkey[idx * 4 : idx * 4 + 4] = struct.pack("<I", z & 0xFFFFFFFF)
    return _md5(bytes(initkey))

def derive_wxsqlite3_aes128_page_key(raw_key, page_no):
    if len(raw_key) != 16:
        raise ValueError("wxSQLite3 AES-128 raw key must be 16 bytes")
    material = raw_key + struct.pack("<I", page_no) + b"sAlT"
    return _md5(material)

def is_plain_sqlite_page(page):
    return page[: len(SQLITE_HDR)] == SQLITE_HDR

def has_wxsqlite3_plain_header_fragment(page):
    if len(page) < 24:
        return False
    header = page[16:24]
    page_size = (header[0] << 8) | header[1]
    if page_size == 1:
        page_size = 65536
    return (
        page_size >= 512
        and page_size <= 65536
        and (page_size & (page_size - 1)) == 0
        and header[5] == 0x40
        and header[6] == 0x20
        and header[7] == 0x20
    )

def decrypt_wxsqlite3_aes128_page(raw_key, page_data, page_no):
    if len(page_data) != PAGE_SZ:
        raise ValueError(f"page must be exactly {PAGE_SZ} bytes")
    data = bytearray(page_data)
    page_key = derive_wxsqlite3_aes128_page_key(raw_key, page_no)
    iv = generate_initial_vector(page_no)
    if page_no == 1 and has_wxsqlite3_plain_header_fragment(data):
        db_header_fragment = bytes(data[16:24])
        data[16:24] = data[8:16]
        decrypted_tail = _aes_decrypt_cbc(page_key, iv, bytes(data[16:]))
        data[16:] = decrypted_tail
        if bytes(data[16:24]) != db_header_fragment:
            raise ValueError("wxSQLite3 AES-128 key validation failed")
        data[:16] = SQLITE_HDR
        return bytes(data)
    return _aes_decrypt_cbc(page_key, iv, bytes(data))

def looks_like_sqlite_page1(page):
    if page[: len(SQLITE_HDR)] != SQLITE_HDR:
        return False
    if len(page) < 108:
        return False
    btree_page_type = page[100]
    return btree_page_type in (0x02, 0x05, 0x0A, 0x0D)

def verify_wxsqlite3_aes128_key(raw_key, page1):
    if len(raw_key) != 16 or len(page1) < PAGE_SZ:
        return False
    try:
        decrypted = decrypt_wxsqlite3_aes128_page(raw_key, page1[:PAGE_SZ], 1)
    except (ValueError, KeyError):
        return False
    return looks_like_sqlite_page1(decrypted)

def decrypt_wxwork_database(db_path, out_path, raw_key):
    size = os.path.getsize(db_path)
    total_pages = (size + PAGE_SZ - 1) // PAGE_SZ
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(db_path, "rb") as fin, open(out_path, "wb") as fout:
        for page_no in range(1, total_pages + 1):
            page = fin.read(PAGE_SZ)
            if not page:
                break
            if len(page) < PAGE_SZ:
                page += b"\x00" * (PAGE_SZ - len(page))
            fout.write(decrypt_wxsqlite3_aes128_page(raw_key, page, page_no))

def find_default_profile_dir():
    base = os.path.expanduser("~/Library/Containers/com.tencent.WeWorkMac/Data/Documents/Profiles")
    if not os.path.isdir(base):
        return None
    setting_file = os.path.join(base, "setting.json")
    if os.path.exists(setting_file):
        try:
            with open(setting_file, "r", encoding="utf-8") as f:
                d = json.load(f)
            prof = d.get("CurrentProfile")
            if prof and os.path.isdir(os.path.join(base, prof)):
                return os.path.join(base, prof)
        except Exception:
            pass
    dirs = [os.path.join(base, d) for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))]
    return dirs[0] if dirs else None

def parse_key_hex(value):
    value = (value or "").strip()
    if value.startswith("x'") and value.endswith("'"):
        value = value[2:-1]
    if len(value) != 32:
        raise ValueError("WXWork 密钥必须为 32 位十六进制字符 (16 字节)")
    return bytes.fromhex(value)

def main():
    parser = argparse.ArgumentParser(description="macOS 企业微信数据库解密工具")
    parser.add_argument("--key", help="32 位十六进制 AES-128 密钥")
    parser.add_argument("--keys-file", default="wxwork_keys.json", help="密钥文件路径")
    parser.add_argument("--profile-dir", help="企业微信 Profile 数据目录")
    parser.add_argument("--out-dir", default="wxwork_decrypted", help="解密后数据库输出目录")
    args = parser.parse_args()

    profile_dir = args.profile_dir or find_default_profile_dir()
    if not profile_dir or not os.path.isdir(profile_dir):
        print(f"[!] 未找到企业微信 Profile 目录: {profile_dir}")
        return 1

    out_dir = os.path.abspath(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)

    print("=" * 60)
    print("  🏢 macOS 企业微信数据库解密工具 (CommonCrypto)")
    print("=" * 60)
    print(f"数据源目录: {profile_dir}")
    print(f"解密输出目录: {out_dir}")

    # 收集候选密钥
    candidate_keys = []
    if args.key:
        try:
            candidate_keys.append(parse_key_hex(args.key))
        except Exception as e:
            print(f"[!] 密钥格式错误: {e}")
            return 1
    elif os.path.exists(args.keys_file):
        try:
            with open(args.keys_file, "r", encoding="utf-8") as f:
                kd = json.load(f)
            for v in kd.values():
                k_hex = v.get("enc_key") if isinstance(v, dict) else v
                if k_hex and len(k_hex) == 32:
                    candidate_keys.append(parse_key_hex(k_hex))
        except Exception as e:
            print(f"[!] 读取密钥文件失败: {e}")

    targets = [
        ("Messages1/Info.db", "message.db"),
        ("Messages1/Session.db", "session.db"),
        ("Contact/Contact.db", "user.db"),
    ]

    for root, dirs, files in os.walk(profile_dir):
        for f in files:
            if f.endswith(".db") and not f.endswith("-wal") and not f.endswith("-shm"):
                rel = os.path.relpath(os.path.join(root, f), profile_dir)
                if not any(rel == t[0] for t in targets):
                    targets.append((rel, rel))

    print(f"\n找到 {len(targets)} 个数据库文件待处理...")

    if not candidate_keys:
        print("\n[!] 尚未提供解密密钥。")
        print("    请在终端中使用 sudo 运行提取器：")
        print("    sudo ./find_wxwork_keys_macos $(pgrep -x 企业微信)")
        print("    或通过参数传入: python3 decrypt_wxwork_macos.py --key <32位KEY>\n")
        return 1

    success_count = 0
    for rel_src, rel_dst in targets:
        src_path = os.path.join(profile_dir, rel_src)
        if not os.path.exists(src_path):
            continue
        dst_path = os.path.join(out_dir, rel_dst)

        with open(src_path, "rb") as f:
            page1 = f.read(PAGE_SZ)

        if is_plain_sqlite_page(page1):
            os.makedirs(os.path.dirname(dst_path), exist_ok=True)
            shutil.copy2(src_path, dst_path)
            print(f"[COPY] {rel_src} (明文 SQLite)")
            success_count += 1
            continue

        matched_key = None
        for k in candidate_keys:
            if verify_wxsqlite3_aes128_key(k, page1):
                matched_key = k
                break

        if matched_key:
            try:
                decrypt_wxwork_database(src_path, dst_path, matched_key)
                conn = sqlite3.connect(dst_path)
                tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
                conn.close()
                print(f"[OK]   {rel_src} -> {rel_dst} (成功解密, 表数: {len(tables)})")
                success_count += 1
            except Exception as e:
                print(f"[FAIL] {rel_src} 解密失败: {e}")
        else:
            print(f"[SKIP] {rel_src} (候选密钥不匹配)")

    print(f"\n解密完成: 成功 {success_count} 个数据库")
    return 0

if __name__ == "__main__":
    sys.exit(main())
