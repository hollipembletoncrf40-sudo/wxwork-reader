#!/usr/bin/env python3
"""
企业微信通讯录与联系人导出工具 (Contact.db / session.db)
导出 3,530 位联系人至 CSV, Excel, Markdown, JSON 及 HTML 可视化通讯录
"""

import os
import csv
import json
import sqlite3
from datetime import datetime
from collections import defaultdict

def main():
    decrypted_dir = "/Users/josephine001/.gemini/antigravity-ide/scratch/wxwork-reader/wxwork_decrypted_user"
    desktop_dir = os.path.expanduser("~/Desktop")
    out_folder = os.path.join(desktop_dir, "企业微信通讯录与联系人")
    os.makedirs(out_folder, exist_ok=True)

    sess_db = os.path.join(decrypted_dir, "session.db")
    user_db = os.path.join(decrypted_dir, "user.db")

    conn_sess = sqlite3.connect(sess_db)
    conn_user = sqlite3.connect(user_db)

    # 1. 加载企业主体
    corps = {}
    for row in conn_user.execute("SELECT * FROM CORPINFO").fetchall():
        cid = row[0]
        cname = "嘉立创集团"
        corps[cid] = cname

    # 2. 加载所有用户与部门
    query = """
    SELECT RID, name, gender, email, mobile, phone, job, number, alias, fullpath, avatarurl, corpid
    FROM USER
    ORDER BY fullpath ASC, name ASC
    """

    user_rows = conn_sess.execute(query).fetchall()
    print(f"[+] 从通讯录数据库中读取到 {len(user_rows)} 位联系人记录")

    contacts = []
    by_dept = defaultdict(list)

    for r in user_rows:
        rid, name, gender, email, mobile, phone, job, number, alias, fullpath, avatarurl, corpid = r

        gender_str = "男" if gender == 1 else ("女" if gender == 2 else "未知")
        dept_str = fullpath.strip() if fullpath else "其他 / 待分配部门"
        # 规范化部门路径
        dept_clean = dept_str.replace(">>", " / ").replace(">", " / ")

        item = {
            "user_id": rid,
            "name": name or f"用户_{rid}",
            "gender": gender_str,
            "job": job or "",
            "department": dept_clean,
            "email": email or "",
            "mobile": mobile or phone or "",
            "work_id": number or "",
            "alias": alias or "",
            "avatar": avatarurl or "",
            "corp": corps.get(corpid, "嘉立创集团"),
        }
        contacts.append(item)
        by_dept[dept_clean].append(item)

    # 3. 导出 CSV 文件 (支持 Excel 直接双击打开 UTF-8-BOM)
    csv_path = os.path.join(out_folder, "企业微信通讯录_3530位联系人全量表.csv")
    csv_desktop = os.path.join(desktop_dir, "企业微信通讯录_3530位联系人全量表.csv")

    fieldnames = ["姓名", "部门", "职位/头衔", "工作邮箱", "手机/电话", "工号/账号", "性别", "企业微信ID", "所属公司"]
    for cp in (csv_path, csv_desktop):
        with open(cp, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for c in contacts:
                writer.writerow({
                    "姓名": c["name"],
                    "部门": c["department"],
                    "职位/头衔": c["job"],
                    "工作邮箱": c["email"],
                    "手机/电话": c["mobile"],
                    "工号/账号": c["work_id"] or c["alias"],
                    "性别": c["gender"],
                    "企业微信ID": str(c["user_id"]),
                    "所属公司": c["corp"],
                })

    # 4. 导出 JSON 文件
    json_path = os.path.join(out_folder, "contacts.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(contacts, f, ensure_ascii=False, indent=2)

    # 5. 导出 Markdown 汇总文档 (按部门分级呈现)
    md_path = os.path.join(out_folder, "企业微信通讯录_部门与联系人一览.md")
    md_desktop = os.path.join(desktop_dir, "企业微信通讯录_部门与联系人一览.md")

    md_lines = [
        "# 👥 嘉立创企业微信通讯录与组织架构一览",
        "",
        f"> **导出时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ",
        "> **当前登录账号**: **邬广武** (WuGuangWu · 嘉立创 · 销售助理 · 18127715604)  ",
        f"> **联系人总数**: **{len(contacts):,}** 位  ",
        f"> **一级/二级部门数**: **{len(by_dept)}** 个  ",
        "",
        "---",
        "",
        "## 📑 部门快速索引",
        "",
    ]

    for dept, dept_users in sorted(by_dept.items(), key=lambda x: len(x[1]), reverse=True)[:25]:
        md_lines.append(f"- **{dept}** ({len(dept_users)} 人)")

    md_lines.append("")
    md_lines.append("---")
    md_lines.append("")
    md_lines.append("## 📋 各部门联系人明细列表")
    md_lines.append("")

    for dept, dept_users in sorted(by_dept.items(), key=lambda x: len(x[1]), reverse=True):
        md_lines.append(f"### 🏢 {dept} ({len(dept_users)} 人)")
        md_lines.append("")
        md_lines.append("| 姓名 | 职位 / 岗位 | 工作邮箱 | 手机 / 联系方式 | 工号 / 别名 |")
        md_lines.append("| :--- | :--- | :--- | :--- | :--- |")
        for u in dept_users:
            email_cell = f"`{u['email']}`" if u['email'] else "-"
            mobile_cell = f"`{u['mobile']}`" if u['mobile'] else "-"
            job_cell = u['job'] or "-"
            work_cell = u['work_id'] or u['alias'] or "-"
            md_lines.append(f"| **{u['name']}** | {job_cell} | {email_cell} | {mobile_cell} | {work_cell} |")
        md_lines.append("")

    for mp in (md_path, md_desktop):
        with open(mp, "w", encoding="utf-8") as f:
            f.write("\n".join(md_lines))

    # 6. 生成交互式 HTML 可视化通讯录
    html_path = os.path.join(out_folder, "index.html")
    html_desktop = os.path.join(desktop_dir, "企业微信通讯录_可视化搜索面板.html")

    html_content = generate_contacts_html(contacts, by_dept)
    for hp in (html_path, html_desktop):
        with open(hp, "w", encoding="utf-8") as f:
            f.write(html_content)

    print(f"\n🎉 通讯录导出完成！")
    print(f"   • CSV 全量表格 (Excel打开): {csv_desktop}")
    print(f"   • Markdown 架构清单: {md_desktop}")
    print(f"   • 网页可视化搜索面板: {html_desktop}")
    print(f"   • 完整归档文件夹: {out_folder}")


def generate_contacts_html(contacts, by_dept):
    rows_html = []
    for c in contacts:
        avatar = c["avatar"] or "https://cube.elemecdn.com/3/7c/3ea6beec64369c2642b92c6726f1epng.png"
        rows_html.append(f"""
        <tr class="contact-row" data-name="{c['name'].lower()}" data-job="{c['job'].lower()}" data-dept="{c['department'].lower()}" data-email="{c['email'].lower()}" data-mobile="{c['mobile']}">
            <td class="user-cell">
                <img class="avatar" src="{avatar}" onerror="this.src='https://cube.elemecdn.com/3/7c/3ea6beec64369c2642b92c6726f1epng.png'">
                <div>
                    <div class="user-name">{c['name']}</div>
                    <div class="user-id">ID: {c['user_id']}</div>
                </div>
            </td>
            <td><span class="dept-badge">{c['department']}</span></td>
            <td><strong>{c['job'] or '-'}</strong></td>
            <td>{f"<a href='mailto:{c['email']}'>{c['email']}</a>" if c['email'] else '-'}</td>
            <td>{c['mobile'] or '-'}</td>
            <td>{c['work_id'] or c['alias'] or '-'}</td>
            <td>{c['corp']}</td>
        </tr>
        """)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>企业微信通讯录检索面板</title>
<style>
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: #f3f4f6; font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Segoe UI", Roboto, sans-serif; color: #1f2937; }}
.header {{ background: #0052d9; color: #fff; padding: 22px 32px; position: sticky; top: 0; z-index: 100; box-shadow: 0 2px 10px rgba(0,0,0,.15); }}
.header h1 {{ margin: 0; font-size: 22px; }}
.header p {{ margin: 6px 0 0; font-size: 13px; opacity: .9; }}
.stats-bar {{ display: flex; gap: 16px; margin-top: 12px; }}
.stat-pill {{ background: rgba(255,255,255,.18); padding: 4px 12px; border-radius: 20px; font-size: 12px; font-weight: 500; }}
.container {{ max-width: 1400px; margin: 24px auto; padding: 0 20px; }}
.search-bar {{ display: flex; gap: 12px; margin-bottom: 20px; }}
.search-input {{ flex: 1; padding: 12px 18px; font-size: 15px; border: 1px solid #d1d5db; border-radius: 8px; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,.05); }}
.table-card {{ background: #fff; border-radius: 10px; box-shadow: 0 1px 4px rgba(0,0,0,.08); border: 1px solid #e5e7eb; overflow: hidden; }}
table {{ width: 100%; border-collapse: collapse; text-align: left; font-size: 13px; }}
thead {{ background: #f8fafc; border-bottom: 2px solid #e2e8f0; }}
th {{ padding: 12px 16px; font-weight: 600; color: #475569; }}
td {{ padding: 12px 16px; border-bottom: 1px solid #f1f5f9; }}
tr:hover {{ background: #f8fafc; }}
.user-cell {{ display: flex; align-items: center; gap: 12px; }}
.avatar {{ width: 36px; height: 36px; border-radius: 50%; object-fit: cover; background: #e2e8f0; }}
.user-name {{ font-weight: 700; color: #0f172a; font-size: 14px; }}
.user-id {{ font-size: 11px; color: #94a3b8; }}
.dept-badge {{ background: #eff6ff; color: #1d4ed8; padding: 2px 8px; border-radius: 4px; font-size: 12px; }}
a {{ color: #0052d9; text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
.result-count {{ font-size: 13px; color: #64748b; margin-bottom: 10px; }}
</style>
</head>
<body>
<div class="header">
    <h1>👥 嘉立创企业微信全量通讯录检索系统</h1>
    <p>登录账号：邬广武（嘉立创 · 销售助理）</p>
    <div class="stats-bar">
        <div class="stat-pill">👥 通讯录总人数: {len(contacts):,} 人</div>
        <div class="stat-pill">🏢 部门数: {len(by_dept)} 个</div>
    </div>
</div>
<div class="container">
    <div class="search-bar">
        <input type="text" id="searchInput" class="search-input" placeholder="🔍 快速搜索联系人姓名、部门、职位、邮箱或手机号..." onkeyup="filterUsers()">
    </div>
    <div class="result-count" id="resCount">正在显示全部 {len(contacts):,} 位联系人</div>
    <div class="table-card">
        <table>
            <thead>
                <tr>
                    <th>姓名 / 企微ID</th>
                    <th>所属部门</th>
                    <th>职位 / 岗位</th>
                    <th>工作邮箱</th>
                    <th>手机 / 电话</th>
                    <th>工号 / 别名</th>
                    <th>所属公司主体</th>
                </tr>
            </thead>
            <tbody id="userTableBody">
                {''.join(rows_html)}
            </tbody>
        </table>
    </div>
</div>
<script>
function filterUsers() {{
    const val = document.getElementById('searchInput').value.toLowerCase().trim();
    const rows = document.querySelectorAll('.contact-row');
    let visible = 0;
    rows.forEach(r => {{
        const name = r.getAttribute('data-name');
        const job = r.getAttribute('data-job');
        const dept = r.getAttribute('data-dept');
        const email = r.getAttribute('data-email');
        const mobile = r.getAttribute('data-mobile');
        if (!val || name.includes(val) || job.includes(val) || dept.includes(val) || email.includes(val) || mobile.includes(val)) {{
            r.style.display = '';
            visible++;
        }} else {{
            r.style.display = 'none';
        }}
    }});
    document.getElementById('resCount').innerText = `已找到 ${{visible.toLocaleString()}} 位匹配联系人（共 ${{rows.length.toLocaleString()}} 人）`;
}}
</script>
</body>
</html>"""

if __name__ == "__main__":
    main()
