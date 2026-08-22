/*
 * find_wxwork_keys_macos.c - macOS 企业微信数据库密钥高速扫描与自动解密工具
 *
 * 原理:
 * 1. 从磁盘读取 Messages1/Info.db, Session.db, Contact/Contact.db 的 Page 1
 * 2. 扫描企业微信 (WXWork) 进程内存中的候选 16 字节密钥 (包含原始二进制缓冲区与十六进制字符串)
 * 3. 采用 macOS 原生 CommonCrypto 进行毫秒级 AES-128-CBC 页面解密验证
 * 4. 验证成功后自动输出 wxwork_keys.json 并自动解密所有主数据库到 wxwork_decrypted/
 *
 * 编译:
 *   clang -O3 -o find_wxwork_keys_macos find_wxwork_keys_macos.c -framework Foundation -Wno-deprecated-declarations
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <dirent.h>
#include <ftw.h>
#include <pwd.h>
#include <sys/stat.h>
#include <mach/mach.h>
#include <mach/mach_vm.h>
#include <CommonCrypto/CommonCryptor.h>
#include <CommonCrypto/CommonDigest.h>

#define PAGE_SZ 4096
#define CHUNK_SIZE (4 * 1024 * 1024)
#define MAX_TARGET_DBS 32

typedef struct {
    char rel_path[256];
    char full_path[512];
    unsigned char page1[PAGE_SZ];
    int valid_page1;
    char found_key_hex[33];
    int is_decrypted;
} target_db_t;

static target_db_t g_dbs[MAX_TARGET_DBS];
static int g_db_count = 0;

static inline unsigned int modmult(unsigned int a, unsigned int b, unsigned int c, unsigned int m, unsigned int s) {
    unsigned int q = s / a;
    int res = b * (s - a * q) - c * q;
    if (res < 0) res += m;
    return (unsigned int)res;
}

static void generate_iv(unsigned int page_no, unsigned char *iv_out) {
    unsigned int z = page_no + 1;
    unsigned char initkey[16];
    for (int idx = 0; idx < 4; idx++) {
        z = modmult(52774, 40692, 3791, 2147483399, z);
        initkey[idx * 4 + 0] = (unsigned char)(z & 0xFF);
        initkey[idx * 4 + 1] = (unsigned char)((z >> 8) & 0xFF);
        initkey[idx * 4 + 2] = (unsigned char)((z >> 16) & 0xFF);
        initkey[idx * 4 + 3] = (unsigned char)((z >> 24) & 0xFF);
    }
    CC_MD5(initkey, 16, iv_out);
}

static void derive_page_key(const unsigned char *raw_key, unsigned int page_no, unsigned char *key_out) {
    unsigned char material[24];
    memcpy(material, raw_key, 16);
    material[16] = (unsigned char)(page_no & 0xFF);
    material[17] = (unsigned char)((page_no >> 8) & 0xFF);
    material[18] = (unsigned char)((page_no >> 16) & 0xFF);
    material[19] = (unsigned char)((page_no >> 24) & 0xFF);
    memcpy(material + 20, "sAlT", 4);
    CC_MD5(material, 24, key_out);
}

static int verify_key_on_page1(const unsigned char *raw_key, const unsigned char *page1) {
    /* 检查 page1 是否符合 wxSQLite3 头部特征 */
    unsigned char header_frag[8];
    memcpy(header_frag, page1 + 16, 8);
    
    unsigned int page_size = (header_frag[0] << 8) | header_frag[1];
    if (page_size == 1) page_size = 65536;
    if (page_size < 512 || page_size > 65536 || (page_size & (page_size - 1)) != 0)
        return 0;
    if (header_frag[5] != 0x40 || header_frag[6] != 0x20 || header_frag[7] != 0x20)
        return 0;

    unsigned char data[PAGE_SZ];
    memcpy(data, page1, PAGE_SZ);
    memcpy(data + 16, data + 8, 8);

    unsigned char page_key[16];
    unsigned char iv[16];
    derive_page_key(raw_key, 1, page_key);
    generate_iv(1, iv);

    unsigned char decrypted_tail[PAGE_SZ - 16];
    size_t moved = 0;
    CCCryptorStatus status = CCCrypt(
        kCCDecrypt, kCCAlgorithmAES128, 0,
        page_key, 16, iv,
        data + 16, PAGE_SZ - 16,
        decrypted_tail, PAGE_SZ - 16,
        &moved
    );

    if (status != kCCSuccess) return 0;
    if (memcmp(decrypted_tail, header_frag, 8) != 0) return 0;

    /* 验证 SQLite B-Tree Page 1 类型 (0x02, 0x05, 0x0A, 0x0D) */
    unsigned char btree_type = decrypted_tail[100 - 16];
    return (btree_type == 0x02 || btree_type == 0x05 || btree_type == 0x0A || btree_type == 0x0D);
}

static void decrypt_entire_database(const char *src_path, const char *dst_path, const unsigned char *raw_key) {
    FILE *fin = fopen(src_path, "rb");
    if (!fin) return;
    FILE *fout = fopen(dst_path, "wb");
    if (!fout) { fclose(fin); return; }

    unsigned char page[PAGE_SZ];
    unsigned int page_no = 1;

    while (1) {
        size_t rd = fread(page, 1, PAGE_SZ, fin);
        if (rd == 0) break;
        if (rd < PAGE_SZ) memset(page + rd, 0, PAGE_SZ - rd);

        unsigned char page_key[16];
        unsigned char iv[16];
        derive_page_key(raw_key, page_no, page_key);
        generate_iv(page_no, iv);

        if (page_no == 1) {
            unsigned char data[PAGE_SZ];
            memcpy(data, page, PAGE_SZ);
            memcpy(data + 16, data + 8, 8);

            unsigned char decrypted_tail[PAGE_SZ - 16];
            size_t moved = 0;
            CCCrypt(kCCDecrypt, kCCAlgorithmAES128, 0, page_key, 16, iv,
                    data + 16, PAGE_SZ - 16, decrypted_tail, PAGE_SZ - 16, &moved);

            unsigned char plain_page[PAGE_SZ];
            memcpy(plain_page, "SQLite format 3\x00", 16);
            memcpy(plain_page + 16, decrypted_tail, PAGE_SZ - 16);
            fwrite(plain_page, 1, PAGE_SZ, fout);
        } else {
            unsigned char decrypted_page[PAGE_SZ];
            size_t moved = 0;
            CCCrypt(kCCDecrypt, kCCAlgorithmAES128, 0, page_key, 16, iv,
                    page, PAGE_SZ, decrypted_page, PAGE_SZ, &moved);
            fwrite(decrypted_page, 1, PAGE_SZ, fout);
        }
        page_no++;
    }

    fclose(fin);
    fclose(fout);
}

static pid_t find_wxwork_pid(void) {
    FILE *fp = popen("pgrep -x 企业微信 || pgrep -x WXWork", "r");
    if (!fp) return -1;
    char buf[64];
    pid_t pid = -1;
    if (fgets(buf, sizeof(buf), fp))
        pid = atoi(buf);
    pclose(fp);
    return pid;
}

static int is_hex_char(unsigned char c) {
    return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F');
}

static unsigned char hex_val(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return 0;
}

int main(int argc, char *argv[]) {
    pid_t pid;
    if (argc >= 2)
        pid = atoi(argv[1]);
    else
        pid = find_wxwork_pid();

    if (pid <= 0) {
        fprintf(stderr, "企业微信 (WXWork) 未运行或未找到进程 PID\n");
        return 1;
    }

    printf("============================================================\n");
    printf("  🏢 macOS 企业微信全量数据库高速解密器 (Native Decryptor)\n");
    printf("============================================================\n");
    printf("企业微信 PID: %d\n", pid);

    /* 1. 定位并读取待解密的 Profile 数据库 Page 1 */
    const char *home = getenv("HOME");
    const char *sudo_user = getenv("SUDO_USER");
    if (sudo_user) {
        struct passwd *pw = getpwnam(sudo_user);
        if (pw && pw->pw_dir) home = pw->pw_dir;
    }
    if (!home) home = "/root";

    char profile_dir[512];
    snprintf(profile_dir, sizeof(profile_dir),
             "%s/Library/Containers/com.tencent.WeWorkMac/Data/Documents/Profiles/65196B406683200E24F20354A21E3605",
             home);

    const char *target_rel_paths[] = {
        "Messages1/Info.db",
        "Messages1/Session.db",
        "Contact/Contact.db",
        "Openapi/Openapi.db",
        "CustomerMessage/customer_message.db",
        "CorpCircle/CorpCircle.db",
    };
    int num_targets = sizeof(target_rel_paths) / sizeof(target_rel_paths[0]);

    printf("\n[*] 加载待解密数据库特征...\n");
    for (int i = 0; i < num_targets; i++) {
        char full[512];
        snprintf(full, sizeof(full), "%s/%s", profile_dir, target_rel_paths[i]);
        FILE *f = fopen(full, "rb");
        if (f) {
            strcpy(g_dbs[g_db_count].rel_path, target_rel_paths[i]);
            strcpy(g_dbs[g_db_count].full_path, full);
            if (fread(g_dbs[g_db_count].page1, 1, PAGE_SZ, f) == PAGE_SZ) {
                g_dbs[g_db_count].valid_page1 = 1;
                printf("  • %-35s [已就绪]\n", target_rel_paths[i]);
                g_db_count++;
            }
            fclose(f);
        }
    }

    if (g_db_count == 0) {
        fprintf(stderr, "[!] 未找到任何待解密数据库文件: %s\n", profile_dir);
        return 1;
    }

    /* 2. 获取进程任务端口 */
    mach_port_t task;
    kern_return_t kr = task_for_pid(mach_task_self(), pid, &task);
    if (kr != KERN_SUCCESS) {
        fprintf(stderr, "\n[!] task_for_pid 失败 (错误码: %d)\n", kr);
        fprintf(stderr, "    请使用 sudo 权限运行: sudo ./find_wxwork_keys_macos %d\n", pid);
        return kr;
    }
    printf("\n[+] 成功连接企业微信进程内存 (Task Port: %u)\n", task);

    /* 3. 扫描进程内存 */
    printf("[*] 开始全内存深度密钥嗅探 (包含十六进制字符串与原始密钥结构体)...\n");

    int remaining_dbs = g_db_count;
    size_t total_scanned = 0;
    int region_count = 0;
    mach_vm_address_t addr = 0;

    while (remaining_dbs > 0) {
        mach_vm_size_t size = 0;
        vm_region_basic_info_data_64_t info;
        mach_msg_type_number_t info_count = VM_REGION_BASIC_INFO_COUNT_64;
        mach_port_t obj_name;

        kr = mach_vm_region(task, &addr, &size, VM_REGION_BASIC_INFO_64,
                           (vm_region_info_t)&info, &info_count, &obj_name);
        if (kr != KERN_SUCCESS) break;
        if (size == 0) { addr++; continue; }

        if ((info.protection & (VM_PROT_READ | VM_PROT_WRITE)) == (VM_PROT_READ | VM_PROT_WRITE)
            && size < 500 * 1024 * 1024) {
            region_count++;

            mach_vm_address_t ca = addr;
            while (ca < addr + size) {
                mach_vm_size_t cs = addr + size - ca;
                if (cs > CHUNK_SIZE) cs = CHUNK_SIZE;

                vm_offset_t data;
                mach_msg_type_number_t dc;
                kr = mach_vm_read(task, ca, cs, &data, &dc);
                if (kr == KERN_SUCCESS) {
                    unsigned char *buf = (unsigned char *)data;
                    total_scanned += dc;

                    /* 策略 A: 扫描裸 16 字节原始内存缓冲 (4字节对齐) */
                    for (size_t off = 0; off + 16 <= dc; off += 4) {
                        const unsigned char *candidate_key = buf + off;
                        
                        /* 快速跳过全0或全同字节 */
                        if (candidate_key[0] == 0 && candidate_key[1] == 0 && candidate_key[2] == 0) continue;
                        if (candidate_key[0] == candidate_key[1] && candidate_key[1] == candidate_key[2]) continue;

                        for (int d = 0; d < g_db_count; d++) {
                            if (g_dbs[d].found_key_hex[0] != '\0') continue;
                            if (!g_dbs[d].valid_page1) continue;

                            if (verify_key_on_page1(candidate_key, g_dbs[d].page1)) {
                                for (int k = 0; k < 16; k++)
                                    sprintf(g_dbs[d].found_key_hex + k * 2, "%02x", candidate_key[k]);
                                g_dbs[d].found_key_hex[32] = '\0';
                                printf("\n  🎉 [FOUND-RAW-KEY] 命中数据库: %s\n", g_dbs[d].rel_path);
                                printf("     密钥 (32-hex): %s\n", g_dbs[d].found_key_hex);
                                printf("     内存地址: 0x%016llX\n", (unsigned long long)(ca + off));
                                remaining_dbs--;
                            }
                        }
                        if (remaining_dbs == 0) break;
                    }

                    /* 策略 B: 扫描 32 位 Hex ASCII 字符串 */
                    if (remaining_dbs > 0) {
                        for (size_t off = 0; off + 32 <= dc; off++) {
                            int is_hex = 1;
                            for (int k = 0; k < 32; k++) {
                                if (!is_hex_char(buf[off + k])) { is_hex = 0; break; }
                            }
                            if (is_hex) {
                                unsigned char candidate_key[16];
                                for (int k = 0; k < 16; k++)
                                    candidate_key[k] = (hex_val(buf[off + k * 2]) << 4) | hex_val(buf[off + k * 2 + 1]);

                                for (int d = 0; d < g_db_count; d++) {
                                    if (g_dbs[d].found_key_hex[0] != '\0') continue;
                                    if (!g_dbs[d].valid_page1) continue;

                                    if (verify_key_on_page1(candidate_key, g_dbs[d].page1)) {
                                        for (int k = 0; k < 16; k++)
                                            sprintf(g_dbs[d].found_key_hex + k * 2, "%02x", candidate_key[k]);
                                        g_dbs[d].found_key_hex[32] = '\0';
                                        printf("\n  🎉 [FOUND-HEX-KEY] 命中数据库: %s\n", g_dbs[d].rel_path);
                                        printf("     密钥 (32-hex): %s\n", g_dbs[d].found_key_hex);
                                        remaining_dbs--;
                                    }
                                }
                            }
                            if (remaining_dbs == 0) break;
                        }
                    }

                    mach_vm_deallocate(mach_task_self(), data, dc);
                }
                if (remaining_dbs == 0) break;
                ca += cs;
            }
        }
        addr += size;
    }

    printf("\n[*] 内存扫描完成: 已扫描 %zu MB 内存数据。\n", total_scanned / 1024 / 1024);

    /* 交叉共享密钥验证 (企业微信通常同一账号共享数据库密钥) */
    const char *any_found_key = NULL;
    for (int d = 0; d < g_db_count; d++) {
        if (g_dbs[d].found_key_hex[0] != '\0') {
            any_found_key = g_dbs[d].found_key_hex;
            break;
        }
    }

    if (any_found_key) {
        unsigned char raw_k[16];
        for (int k = 0; k < 16; k++)
            raw_k[k] = (hex_val(any_found_key[k * 2]) << 4) | hex_val(any_found_key[k * 2 + 1]);

        for (int d = 0; d < g_db_count; d++) {
            if (g_dbs[d].found_key_hex[0] == '\0' && g_dbs[d].valid_page1) {
                if (verify_key_on_page1(raw_k, g_dbs[d].page1)) {
                    strcpy(g_dbs[d].found_key_hex, any_found_key);
                    printf("  [CROSS-VERIFY] 数据库 %s 共享密钥成功！\n", g_dbs[d].rel_path);
                }
            }
        }
    }

    /* 4. 保存密钥并自动解密数据库 */
    char out_dir[512];
    snprintf(out_dir, sizeof(out_dir), "/Users/josephine001/.gemini/antigravity-ide/scratch/wxwork-reader/wxwork_decrypted");
    mkdir(out_dir, 0755);

    FILE *fp = fopen("wxwork_keys.json", "w");
    if (fp) {
        fprintf(fp, "{\n");
        int first = 1;
        for (int d = 0; d < g_db_count; d++) {
            if (g_dbs[d].found_key_hex[0] != '\0') {
                fprintf(fp, "%s  \"%s\": {\"enc_key\": \"%s\"}",
                        first ? "" : ",\n", g_dbs[d].rel_path, g_dbs[d].found_key_hex);
                first = 0;
            }
        }
        fprintf(fp, "\n}\n");
        fclose(fp);
        printf("\n[+] 密钥配置已保存至: wxwork_keys.json\n");
    }

    printf("\n[*] 开始全量解密数据库到: %s\n", out_dir);
    int decrypted_count = 0;

    for (int d = 0; d < g_db_count; d++) {
        if (g_dbs[d].found_key_hex[0] != '\0') {
            unsigned char raw_k[16];
            for (int k = 0; k < 16; k++)
                raw_k[k] = (hex_val(g_dbs[d].found_key_hex[k * 2]) << 4) | hex_val(g_dbs[d].found_key_hex[k * 2 + 1]);

            char out_file[512];
            /* 映射名称为标准 wxwork_reader 可读取文件名 */
            if (strstr(g_dbs[d].rel_path, "Info.db"))
                snprintf(out_file, sizeof(out_file), "%s/message.db", out_dir);
            else if (strstr(g_dbs[d].rel_path, "Session.db"))
                snprintf(out_file, sizeof(out_file), "%s/session.db", out_dir);
            else if (strstr(g_dbs[d].rel_path, "Contact.db"))
                snprintf(out_file, sizeof(out_file), "%s/user.db", out_dir);
            else
                snprintf(out_file, sizeof(out_file), "%s/%s", out_dir, strrchr(g_dbs[d].rel_path, '/') ? strrchr(g_dbs[d].rel_path, '/') + 1 : g_dbs[d].rel_path);

            decrypt_entire_database(g_dbs[d].full_path, out_file, raw_k);
            printf("  [DECRYPT-OK] %-30s -> %s\n", g_dbs[d].rel_path, out_file);
            decrypted_count++;
        }
    }

    if (decrypted_count > 0) {
        printf("\n🎉 全量数据库解密成功！共解密 %d 个数据库。\n", decrypted_count);
        printf("   请运行以下命令立即导出所有全量群聊与详细对话记录：\n");
        printf("   python3 wxwork_reader.py export --all --format markdown,html --out-dir ~/Desktop/企业微信全量聊天记录\n\n");
    } else {
        printf("\n[!] 未能匹配到有效密钥。请确认企业微信是否处于正常登录状态。\n");
    }

    return 0;
}
