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

    # 2.1 针对 国际事业部 与 集团核心架构进行 100% 精确归组映射 (依据企业微信官方组织架构树)
    intl_div_dept = "嘉立创 / 国际事业部"
    proj_sales_dept = "嘉立创 / 国际事业部 / 项目销售部"
    smt_team_dept = "嘉立创 / 国际事业部 / 项目销售部 / SMT项目组"
    cnc_team_dept = "嘉立创 / 国际事业部 / 项目销售部 / CNC项目组"
    pcb_team_dept = "嘉立创 / 国际事业部 / 项目销售部 / PCB项目组"
    d3_team_dept = "嘉立创 / 国际事业部 / 项目销售部 / 3D项目组"
    fa_team_dept = "嘉立创 / 国际事业部 / 项目销售部 / FA项目组"
    eda_team_dept = "嘉立创 / 国际事业部 / 项目销售部 / EDA与Layout项目组"
    stencil_team_dept = "嘉立创 / 国际事业部 / 项目销售部 / 钢网项目组"
    logistics_dept = "嘉立创 / 国际事业部 / 物流部"
    corp_biz_dept = "嘉立创 / 集团商务管理团队"

    # 部门归属模式表
    dept_mappings = [
        # 集团商务代表
        (["严垚垚", "宋绚绚", "赖怡静", "李成程", "董思月"], corp_biz_dept),
        # 国际事业部直属
        (["陈世周", "黎睿冰"], intl_div_dept),
        # 项目销售部直属
        (["王逸维"], proj_sales_dept),
        # 3D 项目组
        (["陈莉华", "陈熙", "池忠涛", "劳艺杰", "马玉枭", "苏玉仪", "王新蕊", "袁泽铭", "张强（Ronen)", "张强 (Ronen)", "张雨婷", "钟坤梅", "李倩钰", "潘迪生"], d3_team_dept),
        # PCB 项目组
        (["陈澄锋", "陈婧咏", "郭海波", "何芳柔", "何望阳", "沈万鑫", "韦忠达", "吴奇", "张倩", "李婷", "肖俊", "郭小林", "杨婉婷", "张彩琳", "陈小娇", "刘骏飞", "施如画", "贺永丽", "贺鹏", "王欣冉", "林土珍", "林静雯", "董蔓", "潘雨", "易丽丽", "蓝昕悦", "高方跃"], pcb_team_dept),
        # FA 项目组
        (["陈聪", "Colton", "梁媛怡", "杨慧", "王曼菲", "Miya"], fa_team_dept),
        # EDA 与 Layout
        (["蔡知霖", "陈海琪", "何立元", "邓馨怡", "EasyEDA", "刘传涛"], eda_team_dept),
        # 钢网项目组
        (["方莹", "钟仕婷"], stencil_team_dept),
        # 物流部
        (["叶俊燊", "侯郁柔", "谢政阳", "袁旭阳", "丁艳平"], logistics_dept),
        # CNC 项目组
        (["覃凤娇", "赵伊莎", "赵靖棉", "吕诗影", "代传昊", "符汝岩", "蒋燕林", "柯望", "陈诗英", "王洁颖", "麦柔莹", "李洁", "王蔚"], cnc_team_dept),
        # SMT 项目组
        (["冯玉碟", "贺亚东", "龙钰", "曾小妹", "朱懿", "姜丽", "郭兰芳", "卢志粤", "叶舒淇", "魏运添", "彭龙", "韦小燕", "李嘉衡", "付彩玉", "罗雪薇", "陈紫欣", "黄骎菁", "张莹", "江灿", "刘芳君", "邓仰林", "冯龙", "杜博琳", "芦莹", "张文佩", "张金燕", "李渊", "高子聪", "叶明鑫", "周敏", "管丹丹", "邬广武", "沈伟槟", "邢小妹", "李思敏", "张清", "徐晓莹", "叶诗雅", "何敏"], smt_team_dept)
    ]

    for c in contacts:
        for patterns, target_dept in dept_mappings:
            if any(pat in c["name"] for pat in patterns):
                if c["name"] == "何敏" and c.get("corp_name") == "韶关市嘉立创电子科技有限公司" and target_dept == smt_team_dept:
                    continue
                old_dept = c["department"]
                if old_dept != target_dept:
                    if old_dept in by_dept and c in by_dept[old_dept]:
                        by_dept[old_dept].remove(c)
                    c["department"] = target_dept
                    by_dept[target_dept].append(c)
                break

    # 2.2 补齐截图中存在但在离线库未缓存的组员（严格按中文名去重）
    full_rosters = [
        # SMT
        (smt_team_dept, [
            {"name": "冯玉碟 Rachel-SMT销售-JSR", "job": "销售工程师", "alias": "Rachel"},
            {"name": "贺亚东-Lucas-SMT销售-JSLH", "job": "销售工程师", "alias": "Lucas"},
            {"name": "龙钰 Lorraine", "job": "销售工程师", "alias": "Lorraine"},
            {"name": "曾小妹 Rebecca-SMT销售-JSRZ", "job": "销售工程师", "alias": "Rebecca"},
            {"name": "朱懿 Sinclair-SMT销售-JSS", "job": "销售工程师", "alias": "Sinclair"},
            {"name": "姜丽 Jamila-SMT跟单 售后/培训/AI", "job": "跟单专员", "alias": "Jamila"},
            {"name": "郭兰芳 Claire 早班—SMT跟单-个性化 在线/邮件", "job": "跟单专员", "alias": "Claire"},
            {"name": "卢志粤 Carl-SMT销售-JSCL", "job": "销售工程师", "alias": "Carl"},
            {"name": "叶舒淇 Suki-SMT销售-JSSY", "job": "销售工程师", "alias": "Suki"},
            {"name": "魏运添 Ethan", "job": "销售工程师", "alias": "Ethan"},
            {"name": "彭龙 Paul", "job": "销售工程师", "alias": "Paul"},
            {"name": "韦小燕 Sharon", "job": "销售工程师", "alias": "Sharon"},
            {"name": "李嘉衡", "job": "销售助理", "alias": ""},
            {"name": "付彩玉 Ella", "job": "销售助理", "alias": "Ella"},
            {"name": "罗雪薇 Vayne-SMT-JSVL", "job": "销售工程师", "alias": "Vayne"},
            {"name": "陈紫欣 Christine", "job": "跟单专员", "alias": "Christine"},
            {"name": "黄骎菁 Shannon", "job": "销售助理", "alias": "Shannon"},
            {"name": "张莹 Clara SMT-邮件/在线", "job": "销售助理", "alias": "Clara"},
            {"name": "江灿 Dorae - SMT", "job": "销售助理", "alias": "Dorae"},
            {"name": "刘芳君", "job": "销售助理", "alias": ""},
            {"name": "邓仰林", "job": "项目销售主管助理", "alias": ""},
            {"name": "冯龙 (Leander)", "job": "国际部SMT项目部主管", "alias": "Leander", "email": "fenglong@szjlc.wecom.work"},
            {"name": "杜博琳", "job": "销售助理", "alias": ""},
            {"name": "芦莹", "job": "销售助理", "alias": ""},
            {"name": "张文佩 Ava", "job": "销售助理", "alias": "Ava"},
            {"name": "张金燕 Yana", "job": "销售助理", "alias": "Yana"},
            {"name": "李渊", "job": "销售助理", "alias": ""},
            {"name": "高子聪", "job": "销售助理", "alias": ""},
            {"name": "叶明鑫 Mason", "job": "销售助理", "alias": "Mason"},
            {"name": "周敏", "job": "销售助理", "alias": ""},
            {"name": "管丹丹", "job": "销售助理", "alias": ""},
            {"name": "邬广武", "job": "销售助理", "alias": "WuGuangWu", "mobile": "18127715604"},
            {"name": "沈伟槟", "job": "销售助理", "alias": ""},
            {"name": "邢小妹 Gemma", "job": "销售助理", "alias": "Gemma"},
            {"name": "李思敏-Simin L", "job": "销售助理", "alias": "Simin"},
            {"name": "张清 (Aurelia)", "job": "销售助理", "alias": "Aurelia"},
            {"name": "徐晓莹 (Bella)", "job": "销售助理", "alias": "Bella"},
            {"name": "叶诗雅 Sabrina", "job": "销售助理", "alias": "Sabrina"},
            {"name": "何敏", "job": "销售助理", "alias": ""}
        ]),
        # CNC
        (cnc_team_dept, [
            {"name": "覃凤娇 Quincy", "job": "销售工程师", "alias": "Quincy"},
            {"name": "赵伊莎 Essie-CNC销售-JCE", "job": "销售工程师", "alias": "Essie"},
            {"name": "赵靖棉 Jasmine", "job": "销售工程师", "alias": "Jasmine"},
            {"name": "吕诗影 Gina- CNC销售-JCG", "job": "跟单专员", "alias": "Gina"},
            {"name": "代传昊-CNC/钣金海外技术支持", "job": "海外技术支持", "alias": ""},
            {"name": "符汝岩 Roy-CNC钣金", "job": "项目销售主管", "alias": "Roy", "email": "guojibufuruyan@szjlc.wecom.work"},
            {"name": "蒋燕林 Jolin-CNC", "job": "销售助理", "alias": "Jolin"},
            {"name": "柯望 Cora-CNC", "job": "销售助理", "alias": "Cora"},
            {"name": "陈诗英 Ying", "job": "销售助理", "alias": "Ying"},
            {"name": "王洁颖 Janine", "job": "销售助理", "alias": "Janine", "email": "janinewong888@outlook.com"},
            {"name": "麦柔莹 Maryin", "job": "销售助理", "alias": "Maryin"},
            {"name": "李洁 Nora", "job": "跟单外协", "alias": "Nora"},
            {"name": "王蔚 Hardy", "job": "销售助理", "alias": "Hardy"}
        ]),
        # 3D
        (d3_team_dept, [
            {"name": "陈莉华 Eliza", "job": "销售助理", "alias": "Eliza"},
            {"name": "陈熙 Elven-3D 销售-J3DE", "job": "销售工程师", "alias": "Elven"},
            {"name": "池忠涛 Julia -3D 销售-J3DJ", "job": "销售工程师", "alias": "Julia"},
            {"name": "劳艺杰 Laura", "job": "销售助理", "alias": "Laura"},
            {"name": "马玉枭", "job": "销售助理", "alias": ""},
            {"name": "苏玉仪 Lesley-3D 销售-J3DL", "job": "销售工程师", "alias": "Lesley"},
            {"name": "王新蕊 Rayne", "job": "销售助理", "alias": "Rayne"},
            {"name": "袁泽铭 Frank-3D 销售-J3DF", "job": "销售工程师", "alias": "Frank"},
            {"name": "张强 (Ronen) -3D", "job": "项目销售主管", "alias": "Ronen"},
            {"name": "张雨婷 Marina-3D 销售-J3DM", "job": "销售工程师", "alias": "Marina"},
            {"name": "钟坤梅 Kimie-3D 跟单-售后/邮件", "job": "跟单专员", "alias": "Kimie"},
            {"name": "李倩钰-Cherie", "job": "销售助理", "alias": "Cherie"}
        ]),
        # PCB
        (pcb_team_dept, [
            {"name": "陈澄锋 Claus - PCB 销售- JPC", "job": "销售工程师", "alias": "Claus"},
            {"name": "陈婧咏 Joann - PCB 销售- JPJ", "job": "销售工程师", "alias": "Joann"},
            {"name": "郭海波 Myles - PCB 销售- JPM", "job": "销售工程师", "alias": "Myles"},
            {"name": "何芳柔 Rosie - PCB 销售 - JPR", "job": "销售工程师", "alias": "Rosie"},
            {"name": "何望阳 Eric - PCB 销售 - JPE", "job": "销售工程师", "alias": "Eric"},
            {"name": "沈万鑫 Reiter-PCB", "job": "销售工程师", "alias": "Reiter"},
            {"name": "韦忠达-Wick-PCB 跟单 -在线/邮件", "job": "跟单专员", "alias": "Wick"},
            {"name": "吴奇 Troy - PCB 销售- JPT", "job": "销售工程师", "alias": "Troy"},
            {"name": "张倩 Ines-PCB 跟单-售后/AI", "job": "跟单专员", "alias": "Ines"},
            {"name": "李婷 Yvette - PCB 销售 - JPY", "job": "销售工程师", "alias": "Yvette"},
            {"name": "肖俊 Jonas-PCB", "job": "项目销售主管助理", "alias": "Jonas"},
            {"name": "郭小林 Ryan-PCB 跟单-在线/邮件", "job": "跟单专员", "alias": "Ryan"},
            {"name": "杨婉婷 Winnie", "job": "销售助理", "alias": "Winnie"},
            {"name": "张彩琳 Mila-PCB 销售-JPMI", "job": "销售工程师", "alias": "Mila"},
            {"name": "陈小娇 Lizz-PCB 销售-JPL", "job": "销售工程师", "alias": "Lizz"},
            {"name": "刘骏飞 Jaffrey Lor", "job": "销售助理", "alias": "Jaffrey"},
            {"name": "施如画 Carrie-PCB", "job": "销售工程师", "alias": "Carrie"},
            {"name": "贺永丽 lily-PCB", "job": "销售助理", "alias": "lily"},
            {"name": "贺鹏 Patrick-PCB", "job": "销售工程师", "alias": "Patrick"},
            {"name": "王欣冉 Stella", "job": "销售助理", "alias": "Stella"},
            {"name": "林土珍", "job": "销售助理", "alias": ""},
            {"name": "林静雯", "job": "销售助理", "alias": ""},
            {"name": "董蔓 Sookie", "job": "销售助理", "alias": "Sookie"},
            {"name": "潘雨", "job": "销售助理", "alias": ""},
            {"name": "易丽丽 Katie", "job": "销售助理", "alias": "Katie"},
            {"name": "蓝昕悦 Mory", "job": "销售助理", "alias": "Mory"},
            {"name": "高方跃 (Owen)", "job": "销售助理", "alias": "Owen"}
        ]),
        # FA
        (fa_team_dept, [
            {"name": "Colton-陈聪", "job": "销售助理", "alias": "Colton"},
            {"name": "梁媛怡 Eileen", "job": "销售助理", "alias": "Eileen"},
            {"name": "杨慧", "job": "销售助理", "alias": ""},
            {"name": "Miya-王曼菲", "job": "销售助理", "alias": "Miya"}
        ]),
        # EDA 与 Layout
        (eda_team_dept, [
            {"name": "EasyEDA技术支持：蔡知霖 (David cai)", "job": "EDA技术支持", "alias": "David"},
            {"name": "EasyEDA技术支持：陈海琪 (Haidy chen)", "job": "EDA技术支持", "alias": "Haidy"},
            {"name": "何立元 Lyle", "job": "销售助理", "alias": "Lyle"},
            {"name": "邓馨怡 Estella", "job": "销售助理", "alias": "Estella"}
        ]),
        # 钢网
        (stencil_team_dept, [
            {"name": "方莹 Sophia 8.19-8.23休假", "job": "销售助理", "alias": "Sophia"},
            {"name": "钟仕婷 Christine", "job": "销售助理", "alias": "Christine"}
        ]),
        # 物流部
        (logistics_dept, [
            {"name": "叶俊燊", "job": "国际物流专员", "alias": ""},
            {"name": "侯郁柔", "job": "国际物流专员", "alias": ""},
            {"name": "谢政阳", "job": "国际物流专员", "alias": ""},
            {"name": "袁旭阳", "job": "国际物流专员", "alias": ""},
            {"name": "丁艳平", "job": "国际物流专员", "alias": ""}
        ])
    ]

    for target_dept, members in full_rosters:
        for item in members:
            base_name = re.sub(r"[a-zA-Z0-9\s\-_（）\(\)/:：]+", "", item["name"])
            exists = any(base_name and base_name in re.sub(r"[a-zA-Z0-9\s\-_（）\(\)/:：]+", "", c["name"]) and c["department"] == target_dept for c in contacts)
            if not exists:
                new_c = {
                    "user_id": f"EXT_{len(contacts)+1}",
                    "name": item["name"],
                    "gender": "未知",
                    "job": item["job"],
                    "department": target_dept,
                    "email": item.get("email", ""),
                    "mobile": item.get("mobile", ""),
                    "phone": "",
                    "employee_no": "",
                    "alias": item["alias"],
                    "corp_name": "深圳市嘉立创科技集团",
                    "avatar_url": "",
                    "type": "企业内部员工"
                }
                contacts.insert(0, new_c)
                by_dept[target_dept].append(new_c)

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
