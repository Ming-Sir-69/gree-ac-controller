#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
格力空调云端覆盖控制脚本 - Docker 版
v6: 修复缩进和转义字符问题，调整默认触发时间
时区：强制 Asia/Shanghai (UTC+8)，双重保险
"""

import os
import requests
import hashlib
import hmac
import time
import json
import logging
from datetime import datetime, timezone, timedelta
from enum import Enum

# ══════════════════════════════════════════════════════════════
# 时区配置（双重保险）
# ══════════════════════════════════════════════════════════════
try:
    from zoneinfo import ZoneInfo
    _CST = ZoneInfo("Asia/Shanghai")
    def _now_cst():
        return datetime.now(_CST)
except ImportError:
    _CST = timezone(timedelta(hours=8))
    def _now_cst():
        return datetime.now(timezone.utc).astimezone(_CST)

# ══════════════════════════════════════════════════════════════
# 五种模式枚举
# ══════════════════════════════════════════════════════════════
class Mode(Enum):
    SLEEP      = "睡眠"
    NORMAL     = "普通"
    PRECOOL    = "预冷"
    AFTER_MEAL = "饭后"
    OFF_CHECK  = "关机检查"

# ══════════════════════════════════════════════════════════════
# 时钟校准（每5分钟打印一次 CST/UTC 对比）
# ══════════════════════════════════════════════════════════════
CALIBRATE_INTERVAL = 300
_last_calibrate_ts = 0

def calibrate_clock():
    global _last_calibrate_ts
    if time.time() - _last_calibrate_ts < CALIBRATE_INTERVAL:
        return
    _last_calibrate_ts = time.time()
    cst = _now_cst()
    utc = datetime.now(timezone.utc)
    offset_h = cst.utcoffset().total_seconds() / 3600
    status = "✅ 东八区正常" if offset_h == 8.0 else "⚠️ 时区异常！预期+8.0"
    log.info(
        f"[时钟校准] CST={cst.strftime('%Y-%m-%d %H:%M:%S')}  "
        f"UTC={utc.strftime('%Y-%m-%d %H:%M:%S')}  "
        f"UTC偏移={offset_h:+.1f}h  {status}"
    )

# ══════════════════════════════════════════════════════════════
# 解析函数
# ══════════════════════════════════════════════════════════════
def parse_mode(v):
    v = str(v).strip().lower()
    if v in ("0", "cool", "制冷"): return 0
    if v in ("1", "heat", "制热"): return 1
    if v in ("2", "auto", "自动"): return 2
    if v in ("3", "fan",  "送风"): return 3
    if v in ("4", "dry",  "除湿"): return 4
    raise ValueError(f"模式值无法识别: '{v}'")

def parse_wind(v):
    v = str(v).strip().lower()
    if v in ("0", "auto",          "自动"): return 0
    if v in ("1", "low",  "小",    "低"):   return 1
    if v in ("2", "medium", "med", "中"):   return 2
    if v in ("3", "high", "大",    "高"):   return 3
    raise ValueError(f"风速值无法识别: '{v}'")

def parse_trigger_time(v):
    """
    解析 TRIGGER_TIME（MM:SS），返回 (target_minute_mod5, target_second)。
    仅作为「首选触发窗口」参考，不再作为唯一触发条件。
    """
    try:
        parts = str(v).strip().split(":")
        minute = int(parts[0]) % 5
        second = int(parts[1])
        if not (0 <= second <= 59):
            raise ValueError
        return minute, second
    except Exception:
        logging.warning(f"TRIGGER_TIME 格式错误: '{v}'，已使用默认值 00:30")
        return 0, 30

def parse_off_interval(v):
    """关机检查间隔，单位分钟，范围 1–120，超范围自动 clamp。"""
    try:
        val = int(str(v).strip())
        if val < 1:
            logging.warning(f"OFF_CHECK_INTERVAL={v} 小于最小值1，已设为 1")
            return 1
        if val > 120:
            logging.warning(f"OFF_CHECK_INTERVAL={v} 大于最大值120，已设为 120")
            return 120
        return val
    except Exception:
        logging.warning(f"OFF_CHECK_INTERVAL 格式错误: '{v}'，已使用默认值 30")
        return 30

# ══════════════════════════════════════════════════════════════
# 环境变量
# ══════════════════════════════════════════════════════════════
CLIENT_ID     = os.getenv("CLIENT_ID",     "")
CLIENT_SECRET = os.getenv("CLIENT_SECRET", "")
DEVICE_ID     = os.getenv("DEVICE_ID",     "")
REMOTE_ID     = os.getenv("REMOTE_ID",     "")
BASE_URL      = os.getenv("BASE_URL",      "https://openapi.tuyacn.com")

if not all([CLIENT_ID, CLIENT_SECRET, DEVICE_ID, REMOTE_ID]):
    raise EnvironmentError(
        "❌ 缺少必需的环境变量！\n"
        "  CLIENT_ID=\n  CLIENT_SECRET=\n  DEVICE_ID=\n  REMOTE_ID="
    )

# 调温触发参数
TRIGGER_MINUTE, TRIGGER_SECOND = parse_trigger_time(
    os.getenv("TRIGGER_TIME", "00:30")
)
# 触发窗口容差：±TRIGGER_WINDOW 秒内都算命中（解决 sleep 漂移）
TRIGGER_WINDOW = int(os.getenv("TRIGGER_WINDOW", "2"))
# 调温间隔（秒）：5分钟 = 300秒
AC_INTERVAL_SEC = 300

# 关机检查间隔（独立）
OFF_CHECK_INTERVAL     = parse_off_interval(os.getenv("OFF_CHECK_INTERVAL", "30"))
OFF_CHECK_INTERVAL_SEC = OFF_CHECK_INTERVAL * 60

# 兜底倍率：超过间隔 * FALLBACK_RATIO 秒仍未触发则强制补发
FALLBACK_RATIO = float(os.getenv("FALLBACK_RATIO", "1.3"))

PRECOOL_TEMP    = int(os.getenv("PRECOOL_TEMP",    "20"))
PRECOOL_MODE    = parse_mode(os.getenv("PRECOOL_MODE",    "制冷"))
PRECOOL_WIND    = parse_wind(os.getenv("PRECOOL_WIND",    "中"))

AFTER_MEAL_TEMP = int(os.getenv("AFTER_MEAL_TEMP", "22"))
AFTER_MEAL_MODE = parse_mode(os.getenv("AFTER_MEAL_MODE", "制冷"))
AFTER_MEAL_WIND = parse_wind(os.getenv("AFTER_MEAL_WIND", "小"))

NORMAL_TEMP     = int(os.getenv("NORMAL_TEMP",     "24"))
NORMAL_MODE     = parse_mode(os.getenv("NORMAL_MODE",     "制冷"))
NORMAL_WIND     = parse_wind(os.getenv("NORMAL_WIND",     "小"))

SLEEP_TEMP      = int(os.getenv("SLEEP_TEMP",      "25"))
SLEEP_MODE      = parse_mode(os.getenv("SLEEP_MODE",      "制冷"))
SLEEP_WIND      = parse_wind(os.getenv("SLEEP_WIND",      "小"))

# ══════════════════════════════════════════════════════════════
# 日志配置
# ══════════════════════════════════════════════════════════════
log_dir = "logs"
os.makedirs(log_dir, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(f"{log_dir}/ac_final.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════
# Token 管理
# ══════════════════════════════════════════════════════════════
token        = None
token_expire = 0

def _sign(method, path, body_str, tk):
    ts           = str(int(time.time() * 1000))
    content_hash = hashlib.sha256(body_str.encode()).hexdigest()
    str_to_sign  = "\n".join([method.upper(), content_hash, "", path])
    raw          = CLIENT_ID + (tk or "") + ts + str_to_sign
    sign         = hmac.new(
        CLIENT_SECRET.encode(), raw.encode(), hashlib.sha256
    ).hexdigest().upper()
    return ts, sign

def get_token():
    global token, token_expire
    path = "/v1.0/token?grant_type=1"
    ts, sign = _sign("GET", path, "", "")
    headers = {
        "client_id":   CLIENT_ID,
        "sign":        sign,
        "t":           ts,
        "sign_method": "HMAC-SHA256",
    }
    resp = requests.get(BASE_URL + path, headers=headers, timeout=10).json()
    if not resp.get("success"):
        raise Exception(f"Token 获取失败: {resp}")
    token        = resp["result"]["access_token"]
    token_expire = time.time() + resp["result"]["expire_time"] - 120
    log.info("Token 刷新成功")
    return token

def ensure_token():
    if not token or time.time() > token_expire:
        get_token()
    return token

# ══════════════════════════════════════════════════════════════
# API 调用（含完整响应日志，用于排查虚假 success）
# ══════════════════════════════════════════════════════════════
def call_api(method, path, body=None):
    tk       = ensure_token()
    body_str = json.dumps(body, separators=(",", ":")) if body else ""
    ts, sign = _sign(method, path, body_str, tk)
    headers  = {
        "client_id":    CLIENT_ID,
        "access_token": tk,
        "sign":         sign,
        "t":            ts,
        "sign_method":  "HMAC-SHA256",
        "Content-Type": "application/json",
    }
    url = BASE_URL + path
    if method.upper() == "GET":
        resp = requests.get(url, headers=headers, timeout=10).json()
    else:
        resp = requests.post(url, headers=headers, data=body_str, timeout=10).json()

    # 完整响应写入日志，方便排查虚假 success / 频率限制报错
    log.debug(f"[API响应] {method} {path} → {json.dumps(resp, ensure_ascii=False)}")

    # 频率限制检测：涂鸦限频时 code 通常为 429 或 "rate limit"
    code = str(resp.get("code", ""))
    msg  = str(resp.get("msg",  "")).lower()
    if "429" in code or "rate" in msg or "limit" in msg or "频率" in msg:
        log.warning(f"[⚠️ 频率限制] API 返回疑似限频: code={code} msg={resp.get('msg','')}")

    return resp

# ══════════════════════════════════════════════════════════════
# 空调指令
# ══════════════════════════════════════════════════════════════
MODE_NAMES = ["制冷", "制热", "自动", "送风", "除湿"]
WIND_NAMES = ["自动", "小", "中", "大"]

def send_ac_command(power, mode=None, temp=None, wind=None):
    path = (
        f"/v2.0/infrareds/{DEVICE_ID}"
        f"/air-conditioners/{REMOTE_ID}/scenes/command"
    )
    body   = {"power": power}
    if mode is not None: body["mode"] = mode
    if temp is not None: body["temp"] = temp
    if wind is not None: body["wind"] = wind

    result = call_api("POST", path, body)
    ok     = result.get("success", False)

    if power == 0:
        log.info(f" ↓ 关机指令 → {'✅ 成功' if ok else '❌ 失败: ' + str(result)}")
    else:
        log.info(
            f" ↑ 调温指令 → 开机 | 模式:{MODE_NAMES[mode]} | "
            f"温度:{temp}°C | 风速:{WIND_NAMES[wind]} | "
            f"{'✅ 成功' if ok else '❌ 失败: ' + str(result)}"
        )
    return ok

def turn_off_ac():
    try:
        send_ac_command(power=0)
    except Exception as e:
        log.error(f"关机异常: {e}")

def set_ac(temp, mode, wind):
    try:
        send_ac_command(power=1, mode=mode, temp=temp, wind=wind)
    except Exception as e:
        log.error(f"调温异常: {e}")

# ══════════════════════════════════════════════════════════════
# 模式判断（单一入口）
# ══════════════════════════════════════════════════════════════
def get_mode(now) -> Mode:
    t = now.hour * 60 + now.minute
    is_weekend = now.weekday() in (5, 6)

    if t >= 23 * 60 or t < 6 * 60:
        return Mode.SLEEP

    if is_weekend:
        return Mode.NORMAL

    # 预冷档
    if (9*60+50  <= t < 10*60) or \
       (11*60+50 <= t < 12*60) or \
       (15*60+20 <= t < 15*60+30):
        return Mode.PRECOOL

    # 饭后档
    if (12*60 <= t < 12*60+30) or \
       (17*60+30 <= t < 18*60):
        return Mode.AFTER_MEAL

    # 关机检查（人不在）
    if (8*60     <= t < 9*60+50)  or \
       (10*60+10    <= t < 11*60+50) or \
       (13*60+30 <= t < 15*60+20) or \
       (15*60+40 <= t < 17*60+30):
        return Mode.OFF_CHECK

    return Mode.NORMAL

# ══════════════════════════════════════════════════════════════
# 执行模式
# ══════════════════════════════════════════════════════════════
def execute_mode(mode: Mode, now, reason: str):
    label = f"[{mode.value}] {now.strftime('%H:%M:%S CST')} ({reason})"
    if mode == Mode.OFF_CHECK:
        log.info(f"{label} → 发送关机指令")
        turn_off_ac()
    elif mode == Mode.SLEEP:
        log.info(f"{label} → {SLEEP_TEMP}°C | {MODE_NAMES[SLEEP_MODE]} | {WIND_NAMES[SLEEP_WIND]}风")
        set_ac(SLEEP_TEMP, SLEEP_MODE, SLEEP_WIND)
    elif mode == Mode.PRECOOL:
        log.info(f"{label} → {PRECOOL_TEMP}°C | {MODE_NAMES[PRECOOL_MODE]} | {WIND_NAMES[PRECOOL_WIND]}风")
        set_ac(PRECOOL_TEMP, PRECOOL_MODE, PRECOOL_WIND)
    elif mode == Mode.AFTER_MEAL:
        log.info(f"{label} → {AFTER_MEAL_TEMP}°C | {MODE_NAMES[AFTER_MEAL_MODE]} | {WIND_NAMES[AFTER_MEAL_WIND]}风")
        set_ac(AFTER_MEAL_TEMP, AFTER_MEAL_MODE, AFTER_MEAL_WIND)
    elif mode == Mode.NORMAL:
        log.info(f"{label} → {NORMAL_TEMP}°C | {MODE_NAMES[NORMAL_MODE]} | {WIND_NAMES[NORMAL_WIND]}风")
        set_ac(NORMAL_TEMP, NORMAL_MODE, NORMAL_WIND)

# ══════════════════════════════════════════════════════════════
# 三层触发判断
# ══════════════════════════════════════════════════════════════
def should_trigger(mode: Mode, now, last_fired: dict) -> tuple[bool, str]:
    """
    返回 (是否触发, 原因描述)。

    触发层级（优先级递减）：
      1. 窗口命中：当前秒在 TRIGGER_TIME ±TRIGGER_WINDOW 内，
                   且距上次触发 >= 间隔 * 0.8（防止同窗口双触发）
      2. 兜底补发：距上次触发 >= 间隔 * FALLBACK_RATIO
                   （窗口被漂移跳过时自动补发）

    OFF_CHECK 模式不使用 TRIGGER_TIME 窗口，只用间隔兜底。
    """
    now_ts   = time.time()
    is_off   = (mode == Mode.OFF_CHECK)
    interval = OFF_CHECK_INTERVAL_SEC if is_off else AC_INTERVAL_SEC
    elapsed  = now_ts - last_fired.get(mode, 0)

    # OFF_CHECK：纯间隔触发，不依赖时钟窗口
    if is_off:
        if elapsed >= interval * FALLBACK_RATIO:
            return True, f"间隔兜底({elapsed:.0f}s≥{interval*FALLBACK_RATIO:.0f}s)"
        if elapsed >= interval and now.second == 0:
            return True, f"间隔整点({elapsed:.0f}s)"
        return False, ""

    # 调温模式：窗口优先 + 间隔兜底
    target_sec     = TRIGGER_MINUTE * 60 + TRIGGER_SECOND
    current_sec    = now.minute % 5 * 60 + now.second
    in_window      = abs(current_sec - target_sec) <= TRIGGER_WINDOW

    # 窗口命中（需已过 80% 间隔）
    if in_window and elapsed >= interval * 0.8:
        return True, f"窗口命中({now.minute%5:01d}:{now.second:02d}, 距上次{elapsed:.0f}s)"

    # 兜底：超时未触发
    if elapsed >= interval * FALLBACK_RATIO:
        return True, f"兜底补发({elapsed:.0f}s≥{interval*FALLBACK_RATIO:.0f}s)"

    return False, ""

# ══════════════════════════════════════════════════════════════
# 主循环
# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":

    log.info("=" * 65)
    log.info("格力空调控制器 v6 启动")
    log.info(f"时区：Asia/Shanghai (UTC+8)，zoneinfo 双重保险")
    log.info(f"调温首选窗口：每5min 第{TRIGGER_MINUTE}分 {TRIGGER_SECOND}秒 ±{TRIGGER_WINDOW}s")
    log.info(f"调温兜底超时：{AC_INTERVAL_SEC * FALLBACK_RATIO:.0f}s ({FALLBACK_RATIO}x)")
    log.info(f"关机检查间隔：{OFF_CHECK_INTERVAL}min，兜底 {OFF_CHECK_INTERVAL_SEC * FALLBACK_RATIO:.0f}s")
    log.info(f"模式切换：边界立即触发，重置计时器")
    log.info(f"频率限制检测：API 响应含 429/rate/limit 时自动 WARNING")
    log.info(f"详细响应日志：DEBUG 级别（需设置 LOG_LEVEL=DEBUG 启用）")
    log.info("-" * 65)
    log.info(f"预冷   → {PRECOOL_TEMP}°C | {MODE_NAMES[PRECOOL_MODE]} | {WIND_NAMES[PRECOOL_WIND]}风")
    log.info(f"饭后   → {AFTER_MEAL_TEMP}°C | {MODE_NAMES[AFTER_MEAL_MODE]} | {WIND_NAMES[AFTER_MEAL_WIND]}风")
    log.info(f"日常   → {NORMAL_TEMP}°C | {MODE_NAMES[NORMAL_MODE]} | {WIND_NAMES[NORMAL_WIND]}风")
    log.info(f"睡眠   → {SLEEP_TEMP}°C | {MODE_NAMES[SLEEP_MODE]} | {WIND_NAMES[SLEEP_WIND]}风")
    log.info(f"关机检查 → 每 {OFF_CHECK_INTERVAL}min 发一次")
    log.info("=" * 65)

    # 支持 LOG_LEVEL=DEBUG 环境变量启用详细日志
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    if log_level == "DEBUG":
        logging.getLogger().setLevel(logging.DEBUG)
        log.debug("DEBUG 模式已启用，API 完整响应将写入日志")

    _last_calibrate_ts = 0
    calibrate_clock()
    get_token()

    last_mode:  Mode            = None
    last_fired: dict            = {m: 0.0 for m in Mode}  # 各模式上次触发时间戳

    while True:
        now  = _now_cst()
        ts   = time.time()

        calibrate_clock()
        current_mode = get_mode(now)

        log.info(
            f"[{now.strftime('%H:%M:%S')} CST] 模式={current_mode.value}  "
            f"距上次触发={ts - last_fired[current_mode]:.0f}s"
        )

        # ── 层级1：边界触发 ──────────────────────────────────────
        if current_mode != last_mode and last_mode is not None:
            log.info(f"[模式切换] {last_mode.value} → {current_mode.value}，边界立即触发")
            execute_mode(current_mode, now, "边界切换")
            last_fired[current_mode] = ts  # 重置计时器

        # ── 层级2/3：窗口命中 or 兜底补发 ────────────────────────
        else:
            do_fire, reason = should_trigger(current_mode, now, last_fired)
            if do_fire:
                execute_mode(current_mode, now, reason)
                last_fired[current_mode] = ts
            # else: 正常等待，日志已在上方打印距上次时间，无需额外输出

        last_mode = current_mode
        time.sleep(1)
