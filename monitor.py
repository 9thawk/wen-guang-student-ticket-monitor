# -*- coding: utf-8 -*-
"""
上海文化广场 - 学生票监控器 (API版)
==========================================
通过官方 API 监控指定演出的学生票状态，支持多人手机推送。

原理:
  1. session cookie -> Gettblprogram 获取场次
  2. GettblpricelevelList_ns 获取票档
  3. 识别 VC_PRICEDESC 含"学生"且 SOLD_OUT=0 的学生票
  4. 状态变化时推送到多人

用法:
    python monitor.py          # 持续监控
    python monitor.py --once   # 单次检查
    python monitor.py --status # 查看状态

手机推送（支持多人）:
  - PushPlus: https://www.pushplus.plus/ (免费，每人一个token)
  - Server酱: https://sct.ftqq.com/
  - 企微群机器人: 一个webhook通知全群
"""

import requests, re, time, json, sys, os, random
from datetime import datetime
import smtplib
from email.mime.text import MIMEText

CONFIG_FILE = "config.json"
STATE_FILE = "last_state.json"
LOG_FILE = "monitor.log"

HOMEPAGE = "https://www.shcstheatre.com/"
API_PROGRAM = "https://www.shcstheatre.com/webapi.ashx?op=Gettblprogram"
API_PRICE = "https://www.shcstheatre.com/webapi.ashx?op=GettblpricelevelList_ns"
PROGRAM_LIST_URL = "https://www.shcstheatre.com/Program/programList.aspx"
PUSHPLUS_URL = "http://www.pushplus.plus/send"
SERVERCHAN_URL = "https://sctapi.ftqq.com/{key}.send"

DEFAULT_CONFIG = {
    "performances": [
        {"name": "基督山伯爵", "article_id": "41911", "enabled": True},
        {"name": "大状王",     "article_id": "41885", "enabled": True},
        {"name": "锦衣卫之刀与花", "article_id": "41784", "enabled": True},
        {"name": "粉丝来信",   "article_id": "41809", "enabled": False},
    ],
    "check_interval_seconds": 300,
    "request_timeout_seconds": 15,
    "quiet_hours_enabled": False,
    "quiet_start": "23:00",
    "quiet_end": "08:00",
    "pushplus_tokens": [],
    "serverchan_keys": [],
    "wechat_work_webhook": ""
}

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        for k, v in DEFAULT_CONFIG.items():
            if k not in cfg:
                cfg[k] = v
        # 向后兼容旧的单 token 写法
        if isinstance(cfg.get("pushplus_token",""), str) and cfg.get("pushplus_token") and not cfg.get("pushplus_tokens"):
            cfg["pushplus_tokens"] = [cfg["pushplus_token"]]
        if isinstance(cfg.get("serverchan_key",""), str) and cfg.get("serverchan_key") and not cfg.get("serverchan_keys"):
            cfg["serverchan_keys"] = [cfg["serverchan_key"]]
        return cfg
    cfg = DEFAULT_CONFIG.copy()
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    return cfg

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    safe = msg.encode("ascii", errors="replace").decode("ascii")
    line = f"[{ts}] {safe}"
    try:
        print(line, flush=True)
    except:
        pass
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except:
        pass

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def fetch_with_session(timeout=15):
    s = requests.Session()
    s.get(HOMEPAGE, timeout=timeout,
          headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
    return s

def scrape_performances(session, timeout=15):
    """从节目列表页抓取所有演出"""
    try:
        r = session.get(PROGRAM_LIST_URL, timeout=timeout)
        pattern = r'ARTICLE_ID=(\d+).*?>([^<]+)</a>'
        seen = set()
        result = []
        for m in re.finditer(pattern, r.text):
            aid = m.group(1)
            name = m.group(2).strip()
            if name == "立即购票" or aid in seen:
                continue
            seen.add(aid)
            result.append({"name": name, "article_id": aid, "enabled": True})
        return result
    except Exception as e:
        log(f"[抓取] 节目列表失败: {e}")
        return []

def is_quiet_hours(config):
    if not config.get("quiet_hours_enabled", False):
        return False
    now = datetime.now().strftime("%H:%M")
    s = config.get("quiet_start", "23:00")
    e = config.get("quiet_end", "08:00")
    if s <= e:
        return s <= now <= e
    return now >= s or now <= e

def check_performance(session, perf, timeout=15):
    """检查单个演出的学生票"""
    name = perf.get("name", "?")
    aid = perf.get("article_id", "")
    try:
        r = session.post(API_PROGRAM, data={"id": aid}, timeout=timeout)
        data = r.json()
    except Exception as e:
        return {"name": name, "error": str(e), "student_tickets": []}
    if data.get("code") != 0:
        return {"name": name, "error": data.get("msg","?"), "student_tickets": []}
    events = data.get("data", {}).get("TBLEVENT", [])
    if not events:
        return {"name": name, "error": "无场次", "student_tickets": []}

    tickets = []
    for evt in events:
        eid = evt.get("I_EVENT_ID")
        dt = evt.get("DT_EVENT_DATETIME", "?")
        try:
            r2 = session.post(API_PRICE, data={"I_EVENT_ID": eid}, timeout=timeout)
            prices = r2.json()
        except:
            continue
        if prices.get("code") != 0:
            continue
        for p in prices.get("data", []):
            desc = (p.get("VC_PRICEDESC") or "").strip()
            if "学生" in desc:
                tickets.append({
                    "event_id": eid,
                    "datetime": dt,
                    "price": p.get("I_PRICE_AMT", 0),
                    "desc": desc,
                    "sold_out": int(p.get("SOLD_OUT", 0)) == 1,
                    "seat_cnt": int(p.get("I_WHGC_WEB_SEAT_CNT", 0))
                })
    return {"name": name, "student_tickets": tickets, "error": None}

def check_all(config):
    """自动发现并检查所有演出"""
    session = fetch_with_session(config.get("request_timeout_seconds", 15))
    
    # 自动抓取节目列表
    auto_list = scrape_performances(session, config.get("request_timeout_seconds", 15))
    if auto_list:
        log(f"[发现] 共 {len(auto_list)} 个演出")
    else:
        log(f"[警告] 无法获取节目列表，使用配置中的演出")
        auto_list = config.get("performances", [])
    
    # 合并用户配置（可覆盖 enabled 状态）
    manual = {p["article_id"]: p for p in config.get("performances", [])}
    performances = []
    for p in auto_list:
        aid = p["article_id"]
        if aid in manual:
            p["enabled"] = manual[aid].get("enabled", True)
        performances.append(p)
    # 添加仅存在于配置中的演出
    for aid, mp in manual.items():
        if aid not in {p["article_id"] for p in performances}:
            performances.append(mp)
    
    results = []
    for perf in performances:
        if not perf.get("enabled", True):
            continue
        name = perf.get("name", "?")
        log(f"  检查: {name}...")
        r = check_performance(session, perf, config.get("request_timeout_seconds", 15))
        results.append(r)
        tix = r.get("student_tickets", [])
        avail = [t for t in tix if not t["sold_out"] and t["seat_cnt"] > 0]
        sold = [t for t in tix if t["sold_out"] or t["seat_cnt"] == 0]
        total_seats = sum(t["seat_cnt"] for t in avail)
        if r.get("error"):
            log(f"    [{name}] 错误: {r['error']}")
        elif tix:
            log(f"    [{name}] 学生票 {len(tix)}场 (可购:{len(avail)}场/{total_seats}张  售罄:{len(sold)}场)")
            for t in avail:
                log(f"      >>> 可购  {t['datetime'][:10]} {t['price']}元 {t['desc']} ({t['seat_cnt']}张)")
            for t in sold:
                log(f"      --- 售罄  {t['datetime'][:10]} {t['price']}元 {t['desc']}")
        else:
            log(f"    [{name}] 无学生票档位")
    return results

def detect_changes(results):
    """检测状态变化：只关注「有票 ↔ 售罄」两种状态转换。

    有票 = 至少存在一张 sold_out=False 且 seat_cnt>0 的学生票
    售罄 = 其余一切情况（无学生票档位 / 全 sold_out / seat_cnt 全为 0）
    """
    previous_state = load_state()
    changes = []
    new_state = {}
    for r in results:
        name = r["name"]
        tickets = r.get("student_tickets", [])
        # 真正可购的票：未售罄且余票 > 0
        available = [t for t in tickets if not t["sold_out"] and t["seat_cnt"] > 0]
        curr_has_tickets = len(available) > 0

        prev = previous_state.get(name, {})
        if not isinstance(prev, dict):
            prev = {}
        prev_has_tickets = prev.get("has_tickets", False)
        prev_recorded = prev.get("recorded", False)

        if prev_recorded:
            if curr_has_tickets and not prev_has_tickets:
                # 从无到有：上新了！
                changes.append({
                    "type": "new_tickets",
                    "name": name,
                    "tickets": available,
                    "detail": format_ticket_detail(available)
                })
            elif not curr_has_tickets and prev_has_tickets:
                # 从有到无：售罄了
                changes.append({
                    "type": "sold_out",
                    "name": name,
                    "detail": f"{name} 学生票已全部售罄"
                })
            # 其他情况（有→有、无→无）不通知

        # 保存当前状态
        tickets_sorted = sorted(tickets, key=lambda t: t["event_id"])
        new_state[name] = {
            "recorded": True,
            "has_tickets": curr_has_tickets,
            "total": len(tickets),
            "available_ids": [t["event_id"] for t in available],
            "available_seats": sum(t["seat_cnt"] for t in available),
            "sessions": [{
                "dt": t["datetime"][:10],
                "price": t["price"],
                "desc": t["desc"],
                "seats": t["seat_cnt"],
                "sold": t["sold_out"]
            } for t in tickets_sorted],
            "sold_ids": [t["event_id"] for t in tickets if t["sold_out"]]
        }
    save_state(new_state)
    return changes

def format_ticket_detail(tickets):
    lines = []
    for t in tickets:
        lines.append(f"{t['datetime']} | {t['price']}元 {t['desc']}")
    return "\n".join(lines)

# ============================================================
#  推送函数（支持多人）
# ============================================================

def send_pushplus(token, title, content):
    try:
        r = requests.post(PUSHPLUS_URL, json={
            "token": token, "title": title, "content": content, "template": "html"
        }, timeout=10)
        result = r.json()
        if result.get("code") == 200:
            log(f"[推送] PushPlus({token[:8]}...) 成功")
            return True
        else:
            log(f"[推送] PushPlus 失败: {result.get('msg','?')}")
    except Exception as e:
        log(f"[推送] PushPlus 异常: {e}")
    return False

def send_serverchan(key, title, content):
    try:
        url = SERVERCHAN_URL.format(key=key)
        r = requests.post(url, data={"title": title, "desp": content}, timeout=10)
        result = r.json()
        if result.get("code") == 0:
            log(f"[推送] Server酱({key[:8]}...) 成功")
            return True
        else:
            log(f"[推送] Server酱 失败: {result.get('message','?')}")
    except Exception as e:
        log(f"[推送] Server酱 异常: {e}")
    return False

def send_wechat_work(webhook, title, content):
    """企业微信群机器人 - 一条消息推送全群，天然支持多人"""
    try:
        plain = content.replace("<pre>", "").replace("</pre>", "\n")
        plain = plain.replace("<h3>", "**").replace("</h3>", "**\n")
        plain = plain.replace("<p>", "").replace("</p>", "\n")
        r = requests.post(webhook, json={
            "msgtype": "markdown",
            "markdown": {"content": f"## {title}\n{plain}"}
        }, timeout=10)
        result = r.json()
        if result.get("errcode") == 0:
            log(f"[推送] 企微群机器人 成功")
            return True
        else:
            log(f"[推送] 企微群机器人 失败: {result.get('errmsg','?')}")
    except Exception as e:
        log(f"[推送] 企微群机器人 异常: {e}")
    return False


def send_email(config, title, content):
    """通过邮箱发送通知（支持QQ/163/Gmail等，支持多收件人）"""
    smtp_host = config.get("email_smtp", "smtp.qq.com")
    smtp_port = config.get("email_port", 465)
    smtp_user = config.get("email_user", "")
    smtp_pass = config.get("email_pass", "")
    to_list = config.get("email_to", [])
    if isinstance(to_list, str):
        to_list = [to_list] if to_list else []
    if not smtp_user or not smtp_pass or not to_list:
        return False
    plain = content.replace("<h3>", "[").replace("</h3>", "]")
    plain = plain.replace("<pre>", "").replace("</pre>", "")
    plain = plain.replace("<p>", "").replace("</p>", "")
    try:
        msg = MIMEText(plain, "plain", "utf-8")
        msg["Subject"] = title
        msg["From"] = smtp_user
        msg["To"] = ", ".join(to_list)
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=10) as server:
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, to_list, msg.as_string())
        log(f"[推送] 邮件成功 -> {', '.join(to_list)}")
        return True
    except Exception as e:
        log(f"[推送] 邮件失败: {e}")
    return False


def send_notification(config, title, content):
    """发送所有已配置的推送（支持多人）"""
    if is_quiet_hours(config):
        log(f"[推送] 静默时段，跳过")
        return

    # PushPlus tokens（数组，支持多人；兼容旧版单 token）
    tokens = config.get("pushplus_tokens", [])
    if not tokens:
        old = config.get("pushplus_token", "")
        if old:
            tokens = [old]
    for t in tokens:
        if t:
            send_pushplus(t, title, content)

    # Server酱 keys（数组，支持多人）
    keys = config.get("serverchan_keys", [])
    if not keys:
        old = config.get("serverchan_key", "")
        if old:
            keys = [old]
    plain = content.replace("<pre>", "").replace("</pre>", "\n")
    plain = plain.replace("<h3>", "").replace("</h3>", "\n")
    plain = plain.replace("<p>", "").replace("</p>", "\n")
    for k in keys:
        if k:
            send_serverchan(k, title, plain)

    # 企业微信群机器人（一键推全群）
    webhook = config.get("wechat_work_webhook", "")
    if webhook:
        send_wechat_work(webhook, title, content)

    # QQ邮箱通知
    send_email(config, title, content)

# ============================================================
#  主逻辑
# ============================================================

def check_once(config):
    log("=" * 40)
    log("[检查] 开始检查...")
    results = check_all(config)
    changes = detect_changes(results)

    if changes:
        for c in changes:
            log(f"[变化] {c['type']}: {c['name']}")
            if c["type"] == "new_tickets":
                title = f"[有票!] {c['name']} 学生票可购"
                content = f"<h3>{c['name']} 学生票!</h3><pre>{c['detail']}</pre><p>请尽快登录购票!</p>"
                send_notification(config, title, content)
            elif c["type"] == "sold_out":
                title = f"[售罄] {c['name']} 学生票"
                content = f"<p>{c['detail']}</p>"
                send_notification(config, title, content)
            # 余票数量变化、新增场次等中间状态一律不通知
    else:
        log("[状态] 无变化")

    return results, changes

def show_status(config):
    state = load_state()
    print("")
    print("=" * 50)
    print("  上海文化广场 - 学生票监控状态")
    print("=" * 50)
    if state:
        for name, info in state.items():
            if not isinstance(info, dict):
                continue
            total = info.get("total", 0)
            avail = len(info.get("available_ids", []))
            sold = len(info.get("sold_ids", []))
            seats = info.get("available_seats", 0)
            sessions = info.get("sessions", [])
            if total > 0:
                print(f"  {name}: 共{total}场有学生票 (可购:{avail}场/{seats}张  售罄:{sold}场)")
                for s in sessions:
                    tag = ">>> 可购" if (not s["sold"] and s["seats"] > 0) else "--- 售罄"
                    print(f"      {tag}  {s['dt']} {s['price']}元 {s['desc']} ({s['seats']}张)")
            else:
                print(f"  {name}: 无学生票数据")
    else:
        print("  (尚未执行检查)")
    pp = len(config.get("pushplus_tokens", [])) or (1 if config.get("pushplus_token") else 0)
    sc = len(config.get("serverchan_keys", [])) or (1 if config.get("serverchan_key") else 0)
    ww = "是" if config.get("wechat_work_webhook") else "否"
    print(f"")
    print(f"  推送配置: PushPlus={pp}人 | Server酱={sc}人 | 企微群={ww}")
    print(f"  检查间隔: {config['check_interval_seconds']} 秒")
    print("=" * 50)
    print("")

def run_loop(config):
    log("=" * 50)
    log("上海文化广场学生票监控器已启动 (API版)")
    log(f"   间隔: {config['check_interval_seconds']} 秒")
    log(f"   演出: 自动发现（当前 {len(config.get("performances",[]))} 个配置）")
    pp = len(config.get("pushplus_tokens", [])) or (1 if config.get("pushplus_token") else 0)
    log(f"   推送: PushPlus={pp}人, Server酱, 企微群")
    log("=" * 50)

    check_once(config)
    interval = config["check_interval_seconds"]
    while True:
        try:
            # 每轮重新加载配置，使 config.json 的修改即时生效
            config = load_config()
            interval = config["check_interval_seconds"]
            next_ts = datetime.fromtimestamp(time.time() + interval).strftime("%H:%M:%S")
            log(f"[下次] {next_ts}")
            time.sleep(interval + random.randint(-5, 5))
            check_once(config)
        except KeyboardInterrupt:
            log("监控已停止")
            break
        except Exception as e:
            log(f"[错误] {e}")
            time.sleep(60)

def main():
    config = load_config()
    if "--test-push" in sys.argv:
        print("Running real check and sending to phone...")
        results, changes = check_once(config)
        # Force send current status even if no changes
        lines = ["=== 学生票实时状态 ==="]
        for r in results:
            name = r["name"]
            tix = r.get("student_tickets", [])
            avail = [t for t in tix if not t["sold_out"] and t["seat_cnt"] > 0]
            if tix:
                lines.append("\n" + f"{name}: {len(tix)}场有学生票")
                for t in tix:
                    tag = "[可购]" if (not t["sold_out"] and t["seat_cnt"] > 0) else "[售罄]"
                    lines.append(f"  {tag} {t['datetime'][:10]} {t['price']}元 ({t['seat_cnt']}张)")
        send_notification(config, "[实时状态] 学生票监控", "<pre>" + "\n".join(lines) + "</pre>")
        show_status(config)
        return
    if "--once" in sys.argv or "-1" in sys.argv:
        check_once(config)
        show_status(config)
    elif "--status" in sys.argv or "-s" in sys.argv:
        show_status(config)
    elif "--help" in sys.argv or "-h" in sys.argv:
        print(__doc__)
    else:
        run_loop(config)

if __name__ == "__main__":
    main()
