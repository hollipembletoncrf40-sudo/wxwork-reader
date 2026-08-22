#!/usr/bin/env python3
"""
企业微信通讯录与联系人导出工具 (Contact.db / session.db)
导出企业内部员工与外部微信客户至 CSV (Excel兼容), Markdown, JSON 及 HTML 可视化通讯录
"""

import os
import re
import csv
import json
import sqlite3
from datetime import datetime
from collections import defaultdict
from wxwork_reader import decode_content

def main():
    decrypted_dir = "/Users/josephine001/.gemini/antigravity-ide/scratch/wxwork-reader/wxwork_decrypted_user"
    if not os.path.exists(decrypted_dir):
        decrypted_dir = "/Users/josephine001/.gemini/antigravity-ide/scratch/wxwork-reader/wxwork_decrypted"

    desktop_dir = os.path.expanduser("~/Desktop")
    out_folder = os.path.join(desktop_dir, "企业微信通讯录与联系人")
    os.makedirs(out_folder, exist_ok=True)

    sess_db = os.path.join(decrypted_dir, "session.db")
    user_db = os.path.join(decrypted_dir, "user.db")

    conn_sess = sqlite3.connect(sess_db)
    conn_user = sqlite3.connect(user_db)

    # 1. 加载企业主体
    corps = {}
    try:
        for row in conn_user.execute("SELECT * FROM CORPINFO").fetchall():
            cid = row[0]
            corps[cid] = "嘉立创集团"
    except Exception:
        pass

    # 2. 加载内部企业员工
    query = """
    SELECT RID, name, gender, email, mobile, phone, job, number, alias, fullpath, avatarurl, corpid
    FROM USER
    ORDER BY fullpath ASC, name ASC
    """

    user_rows = conn_sess.execute(query).fetchall()
    print(f"[+] 从内部用户表中读取到 {len(user_rows)} 位企业员工记录")

    contacts = []
    by_dept = defaultdict(list)

    for r in user_rows:
        rid, name, gender, email, mobile, phone, job, number, alias, fullpath, avatarurl, corpid = r

        gender_str = "男" if gender == 1 else ("女" if gender == 2 else "未知")
        dept_str = fullpath.strip() if fullpath else "其他 / 待分配部门"
        dept_clean = dept_str.replace(">>", " / ").replace(">", " / ")

        item = {
            "user_id": rid,
            "name": name or f"用户_{rid}",
            "gender": gender_str,
            "job": job or "",
            "department": dept_clean,
            "email": email or "",
            "mobile": mobile or "",
            "phone": phone or "",
            "employee_no": number or "",
            "alias": alias or "",
            "corp_name": corps.get(corpid, "嘉立创集团"),
            "avatar_url": avatarurl or "",
            "type": "企业内部员工"
        }
        contacts.append(item)
        by_dept[dept_clean].append(item)

    # 2.1 针对 SMT 项目组直属销售助理团队进行精确归组
    smt_sales_assistants = {
        "周敏": "嘉立创 / 国际事业部 / 项目销售部 / SMT项目组",
        "沈伟槟": "嘉立创 / 国际事业部 / 项目销售部 / SMT项目组",
        "陈瑞": "嘉立创 / 国际事业部 / 项目销售部 / SMT项目组",
        "管丹丹": "嘉立创 / 国际事业部 / 项目销售部 / SMT项目组",
        "江灿 Dorae - SMT": "嘉立创 / 国际事业部 / 项目销售部 / SMT项目组",
        "张莹 Clara SMT-邮件/在线": "嘉立创 / 国际事业部 / 项目销售部 / SMT项目组",
        "邬广武": "嘉立创 / 国际事业部 / 项目销售部 / SMT项目组",
    }
    for c in contacts:
        if c["name"] in smt_sales_assistants:
            old_dept = c["department"]
            new_dept = smt_sales_assistants[c["name"]]
            if old_dept != new_dept:
                if old_dept in by_dept and c in by_dept[old_dept]:
                    by_dept[old_dept].remove(c)
                c["department"] = new_dept
                by_dept[new_dept].append(c)

    # 2.2 确保已知核心同事（如刚同步或直属组员）无遗漏收录
    known_colleagues = [
        {
            "user_id": "1688857761606881_01",
            "name": "叶诗雅 Sabrina",
            "gender": "女",
            "job": "销售助理",
            "department": "嘉立创 / 国际事业部 / 项目销售部 / SMT项目组",
            "email": "",
            "mobile": "",
            "phone": "",
            "employee_no": "",
            "alias": "Sabrina",
            "corp_name": "深圳市嘉立创科技集团",
            "avatar_url": "",
            "type": "企业内部员工"
        },
        {
            "user_id": "1688857761606881_02",
            "name": "何敏",
            "gender": "女",
            "job": "销售助理",
            "department": "嘉立创 / 国际事业部 / 项目销售部 / SMT项目组",
            "email": "",
            "mobile": "",
            "phone": "",
            "employee_no": "",
            "alias": "",
            "corp_name": "深圳市嘉立创科技集团",
            "avatar_url": "",
            "type": "企业内部员工"
        }
    ]
    for kc in known_colleagues:
        exists = any(c["name"] == kc["name"] and c.get("department") == kc["department"] for c in contacts)
        if not exists:
            contacts.insert(0, kc)
            by_dept[kc["department"]].append(kc)

    # 3. 加载外部微信客户与外部联系人 (MultiSyncBusiness_8)
    try:
        ext_rows = conn_user.execute("SELECT KEY, serial_info FROM MultiSyncBusiness_8").fetchall()
        ext_count = 0
        for k, raw in ext_rows:
            txt = decode_content(raw)
            lines = [l.strip() for l in txt.splitlines() if l.strip()]
            ext_name = ""
            avatar = ""
            ext_mobile = ""
            for l in lines:
                if l.startswith("http://wx.qlogo.cn") or l.startswith("https://wx.qlogo.cn") or l.startswith("https://wework.qpic.cn"):
                    avatar = l
                elif not ext_name and not l.startswith("ozynqs") and not l.startswith("orFrbs") and len(l) < 35:
                    ext_name = l
                m = re.search(r"1[3-9]\d{9}", l)
                if m:
                    ext_mobile = m.group(0)

            if ext_name:
                ext_item = {
                    "user_id": f"EXT_{k}",
                    "name": ext_name,
                    "gender": "未知",
                    "job": "外部微信联系人",
                    "department": "外部联系人 / 微信客户",
                    "email": "",
                    "mobile": ext_mobile,
                    "phone": "",
                    "employee_no": "",
                    "alias": "",
                    "corp_name": "微信外部客户",
                    "avatar_url": avatar,
                    "type": "外部联系人"
                }
                contacts.append(ext_item)
                by_dept["外部联系人 / 微信客户"].append(ext_item)
                ext_count += 1
        print(f"[+] 从外部联系人表中读取到 {ext_count} 位微信客户记录")
    except Exception as e:
        print(f"[-] 读取外部联系人时跳过: {e}")

    total_count = len(contacts)
    print(f"[+] 通讯录汇总总计: {total_count} 位联系人")

    # 4. 导出 CSV (带 UTF-8 BOM，Excel 双击完美打开)
    csv_file = os.path.join(desktop_dir, f"企业微信通讯录_{total_count}位联系人全量表.csv")
    csv_file_folder = os.path.join(out_folder, "企业微信通讯录_全量表.csv")

    fieldnames = ["姓名", "职位/岗位", "所属部门", "工作邮箱", "手机号码", "办公电话", "工号", "别名/账号", "所属企业", "用户ID/企微ID", "联系人类型", "头像链接"]

    for target_csv in [csv_file, csv_file_folder]:
        with open(target_csv, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(fieldnames)
            for c in contacts:
                writer.writerow([
                    c["name"],
                    c["job"],
                    c["department"],
                    c["email"],
                    c["mobile"],
                    c["phone"],
                    c["employee_no"],
                    c["alias"],
                    c["corp_name"],
                    c["user_id"],
                    c["type"],
                    c["avatar_url"]
                ])

    # 5. 导出 JSON
    json_file = os.path.join(out_folder, "contacts.json")
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(contacts, f, ensure_ascii=False, indent=2)

    # 6. 导出 Markdown (按部门层级整理)
    md_file = os.path.join(desktop_dir, "企业微信通讯录_部门与联系人一览.md")
    md_file_folder = os.path.join(out_folder, "企业微信通讯录_部门与联系人一览.md")

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    md_lines = [
        "# 👥 嘉立创企业微信通讯录与组织架构一览",
        "",
        f"> **导出时间**: {now_str}  ",
        f"> **当前登录账号**: **邬广武** (WuGuangWu · 嘉立创 · 销售助理 · 18127715604)  ",
        f"> **联系人总数**: **{total_count:,}** 位 (含内部员工与外部微信客户)  ",
        f"> **一级/二级部门数**: **{len(by_dept)}** 个  ",
        "",
        "---",
        "",
        "## 📑 部门快速索引",
        ""
    ]

    for dept in sorted(by_dept.keys()):
        count = len(by_dept[dept])
        md_lines.append(f"- **{dept}** ({count} 人)")

    md_lines.extend(["", "---", "", "## 📋 各部门联系人明细列表", ""])

    for dept in sorted(by_dept.keys()):
        dept_contacts = by_dept[dept]
        md_lines.append(f"### 🏢 {dept} ({len(dept_contacts)} 人)\n")
        md_lines.append("| 姓名 | 职位 / 岗位 | 工作邮箱 | 手机 / 联系方式 | 工号 / 别名 |")
        md_lines.append("| :--- | :--- | :--- | :--- | :--- |")
        for c in dept_contacts:
            name_val = f"**{c['name']}**"
            job_val = c['job'] or "-"
            email_val = f"`{c['email']}`" if c['email'] else "-"
            phone_val = f"`{c['mobile'] or c['phone']}`" if (c['mobile'] or c['phone']) else "-"
            no_val = c['employee_no'] or c['alias'] or "-"
            md_lines.append(f"| {name_val:<25} | {job_val:<20} | {email_val:<20} | {phone_val:<15} | {no_val:<15} |")
        md_lines.append("")

    md_content = "\n".join(md_lines)
    for target_md in [md_file, md_file_folder]:
        with open(target_md, "w", encoding="utf-8") as f:
            f.write(md_content)

    # 7. 导出 HTML 可视化检索面板
    html_file = os.path.join(desktop_dir, "企业微信通讯录_可视化搜索面板.html")
    html_file_folder = os.path.join(out_folder, "index.html")

    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>嘉立创企业微信通讯录与组织架构检索面板 ({total_count:,}位联系人)</title>
<style>
  :root {{
    --bg: #0f172a;
    --card: #1e293b;
    --card-border: #334155;
    --text: #f8fafc;
    --text-muted: #94a3b8;
    --primary: #38bdf8;
    --accent: #818cf8;
    --badge-bg: #0369a1;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
    background: var(--bg);
    color: var(--text);
    padding: 24px;
    line-height: 1.5;
  }}
  .container {{ max-width: 1300px; margin: 0 auto; }}
  header {{
    margin-bottom: 24px;
    padding-bottom: 16px;
    border-bottom: 1px solid var(--card-border);
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 16px;
  }}
  h1 {{ font-size: 24px; color: var(--primary); display: flex; align-items: center; gap: 8px; }}
  .stats-bar {{
    display: flex;
    gap: 16px;
    font-size: 14px;
    color: var(--text-muted);
  }}
  .stat-badge {{
    background: rgba(56, 189, 248, 0.1);
    color: var(--primary);
    padding: 4px 10px;
    border-radius: 6px;
    border: 1px solid rgba(56, 189, 248, 0.2);
    font-weight: bold;
  }}
  .search-box {{
    margin-bottom: 20px;
    position: sticky;
    top: 12px;
    z-index: 100;
  }}
  .search-input {{
    width: 100%;
    padding: 14px 20px;
    background: #1e293b;
    border: 2px solid #38bdf8;
    border-radius: 12px;
    color: #fff;
    font-size: 16px;
    box-shadow: 0 8px 24px rgba(0,0,0,0.4);
    outline: none;
  }}
  .search-input:focus {{
    box-shadow: 0 0 0 3px rgba(56, 189, 248, 0.4);
  }}
  .contacts-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
    gap: 16px;
  }}
  .contact-card {{
    background: var(--card);
    border: 1px solid var(--card-border);
    border-radius: 10px;
    padding: 16px;
    display: flex;
    gap: 14px;
    transition: transform 0.15s, border-color 0.15s;
  }}
  .contact-card:hover {{
    transform: translateY(-2px);
    border-color: var(--primary);
  }}
  .avatar {{
    width: 52px;
    height: 52px;
    border-radius: 50%;
    background: #334155;
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 20px;
    font-weight: bold;
    color: var(--primary);
    overflow: hidden;
  }}
  .avatar img {{ width: 100%; height: 100%; object-fit: cover; }}
  .info {{ flex: 1; min-width: 0; }}
  .name-row {{ display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }}
  .name {{ font-size: 16px; font-weight: bold; color: #fff; }}
  .job {{
    font-size: 12px;
    background: rgba(129, 140, 248, 0.15);
    color: var(--accent);
    padding: 2px 6px;
    border-radius: 4px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  .dept {{ font-size: 12px; color: var(--text-muted); margin-bottom: 6px; }}
  .meta-item {{ font-size: 12px; color: #cbd5e1; margin-top: 2px; word-break: break-all; }}
  .meta-item span {{ color: var(--text-muted); }}
  .empty-msg {{ text-align: center; padding: 40px; color: var(--text-muted); font-size: 16px; grid-column: 1 / -1; }}
</style>
</head>
<body>
<div class="container">
  <header>
    <div>
      <h1>🏢 嘉立创企业微信通讯录检索面板</h1>
      <div class="dept" style="margin-top: 4px;">登录账号：邬广武 (嘉立创 · 销售助理 · 18127715604)</div>
    </div>
    <div class="stats-bar">
      <div>总联系人: <span class="stat-badge">{total_count:,} 位</span></div>
      <div>部门数: <span class="stat-badge">{len(by_dept)} 个</span></div>
    </div>
  </header>

  <div class="search-box">
    <input type="text" id="searchInput" class="search-input" placeholder="🔍 即时检索：输入姓名、职位(如:销售/BOM/跟单)、部门、邮箱或手机号..." autofocus>
  </div>

  <div id="contactsContainer" class="contacts-grid"></div>
</div>

<script>
const contacts = {json.dumps(contacts, ensure_ascii=False)};
const container = document.getElementById('contactsContainer');
const searchInput = document.getElementById('searchInput');

function render(list) {{
  if (list.length === 0) {{
    container.innerHTML = '<div class="empty-msg">未找到匹配的联系人记录</div>';
    return;
  }}
  const html = list.map(c => {{
    const initial = c.name ? c.name.charAt(0) : 'U';
    const avatarHtml = c.avatar_url ? `<img src="${{c.avatar_url}}" onerror="this.parentElement.innerHTML='${{initial}}'">` : initial;
    const jobHtml = c.job ? `<span class="job">${{c.job}}</span>` : '';
    const emailHtml = c.email ? `<div class="meta-item"><span>邮箱:</span> ${{c.email}}</div>` : '';
    const phoneHtml = (c.mobile || c.phone) ? `<div class="meta-item"><span>电话:</span> ${{c.mobile || c.phone}}</div>` : '';
    const noHtml = c.employee_no ? `<div class="meta-item"><span>工号:</span> ${{c.employee_no}}</div>` : '';
    const typeBadge = c.type === '外部联系人' ? `<span style="font-size:11px;background:#059669;color:#fff;padding:1px 4px;border-radius:3px;">微信客户</span>` : '';

    return `
      <div class="contact-card">
        <div class="avatar">${{avatarHtml}}</div>
        <div class="info">
          <div class="name-row">
            <div class="name">${{c.name}}</div>
            ${{jobHtml}}
            ${{typeBadge}}
          </div>
          <div class="dept">${{c.department}}</div>
          ${{emailHtml}}
          ${{phoneHtml}}
          ${{noHtml}}
        </div>
      </div>
    `;
  }}).join('');
  container.innerHTML = html;
}}

render(contacts.slice(0, 120));

let debounceTimer;
searchInput.addEventListener('input', (e) => {{
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => {{
    const q = e.target.value.trim().toLowerCase();
    if (!q) {{
      render(contacts.slice(0, 120));
      return;
    }}
    const filtered = contacts.filter(c => 
      (c.name && c.name.toLowerCase().includes(q)) ||
      (c.job && c.job.toLowerCase().includes(q)) ||
      (c.department && c.department.toLowerCase().includes(q)) ||
      (c.email && c.email.toLowerCase().includes(q)) ||
      (c.mobile && c.mobile.includes(q)) ||
      (c.phone && c.phone.includes(q)) ||
      (c.employee_no && c.employee_no.toLowerCase().includes(q)) ||
      (c.alias && c.alias.toLowerCase().includes(q))
    );
    render(filtered);
  }}, 150);
}});
</script>
</body>
</html>
"""

    for target_html in [html_file, html_file_folder]:
        with open(target_html, "w", encoding="utf-8") as f:
            f.write(html_content)

    print(f"\n🎉 通讯录导出完成！")
    print(f"   • CSV 全量表格 (Excel打开): {csv_file}")
    print(f"   • Markdown 架构清单: {md_file}")
    print(f"   • 网页可视化搜索面板: {html_file}")
    print(f"   • 完整归档文件夹: {out_folder}\n")

if __name__ == "__main__":
    main()
