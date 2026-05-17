#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
格力空调云端覆盖控制脚本 - Docker 版

支持通过环境变量配置所有参数
"""

import os
import requests
import hashlib
import hmac
import time
import json
import logging
from datetime import datetime

# ─────────────────────────────────────────
# 配置区（从环境变量读取）
# ─────────────────────────────────────────
CLIENT_ID     = os.getenv("CLIENT_ID", "YOUR_CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET", "YOUR_CLIENT_SECRET")
DEVICE_ID     = os.getenv("DEVICE_ID", "YOUR_DEVICE_ID")
REMOTE_ID     = os.getenv("REMOTE_ID", "YOUR_REMOTE_ID")
BASE_URL      = os.getenv("BASE_URL", "https://openapi.tuyacn.com")

# 空调参数（从环境变量读取，支持中英文文字或数字）
# ─────────────────────────────────────────
def _parse_power(v):
    """on/开/1 → 1，off/关/0 → 0"""
    v = str(v).strip().lower()
    if v in ("on", "开", "开机", "1"):  return 1
    if v in ("off", "关", "关机", "0"): return 0
    raise ValueError(f"TARGET_POWER 不识别的值: {v}，请填 on/off 或 开/关")

def _parse_mode(v):
    """制冷/cool/0 → 0，制热/heat/1 → 1，自动/auto/2 → 2，送风/fan/3 → 3，除湿/dry/4 → 4"""
    v = str(v).strip().lower()
    if v in ("cool", "制冷", "冷", "0"):          return 0
    if v in ("heat", "制热", "热", "暖", "1"):    return 1
    if v in ("auto", "自动", "2"):                return 2
    if v in ("fan",  "送风", "风", "3"):           return 3
    if v in ("dry",  "除湿", "湿", "4"):           return 4
    raise ValueError(f"TARGET_MODE 不识别的值: {v}，请填 cool/heat/auto/fan/dry 或 制冷/制热/自动/送风/除湿")

def _parse_wind(v):
    """auto/自动/0 → 0，low/低/1 → 1，medium/中/2 → 2，high/高/3 → 3"""
    v = str(v).strip().lower()
    if v in ("auto",   "自动", "0"):              return 0
    if v in ("low",    "低",   "低速", "1"):       return 1
    if v in ("medium", "med",  "中",   "中速", "2"): return 2
    if v in ("high",   "高",   "高速", "3"):       return 3
    raise ValueError(f"TARGET_WIND 不识别的值: {v}，请填 auto/low/medium/high 或 自动/低/中/高")

TARGET_POWER = _parse_power(os.getenv("TARGET_POWER", "on"))    # on/off 或 开/关
TARGET_MODE  = _parse_mode (os.getenv("TARGET_MODE",  "cool"))  # cool/heat/auto/fan/dry 或 制冷/制热/自动/送风/除湿
TARGET_TEMP  = int(os.getenv("TARGET_TEMP",  "24"))             # 16-30℃，直接填数字
TARGET_WIND  = _parse_wind (os.getenv("TARGET_WIND",  "auto"))  # auto/low/medium/high 或 自动/低/中/高

# ─────────────────────────────────────────
# 日志（同时输出到终端和文件）
# ─────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("ac_final.log", encoding="utf-8"),
    ]
)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────
# Token 管理（自动续期）
# ─────────────────────────────────────────
_token        = None
_token_expire = 0

def _sign(method, path, body_str="", token=""):
    ts           = str(int(time.time() * 1000))
    content_hash = hashlib.sha256(body_str.encode()).hexdigest()
    str_to_sign  = "\n".join([method.upper(), content_hash, "", path])
    raw          = CLIENT_ID + token + ts + str_to_sign
    sign = hmac.new(
        CLIENT_SECRET.encode(),
        raw.encode(),
        hashlib.sha256
    ).hexdigest().upper()
    return ts, sign

def get_token():
    global _token, _token_expire
    path    = "/v1.0/token?grant_type=1"
    ts, sign = _sign("GET", path)
    headers = {
        "client_id":   CLIENT_ID,
        "sign":        sign,
        "t":           ts,
        "sign_method": "HMAC-SHA256",
    }
    resp = requests.get(BASE_URL + path, headers=headers, timeout=10).json()
    if not resp.get("success"):
        raise Exception(f"Token 获取失败: {resp}")
    _token        = resp["result"]["access_token"]
    _token_expire = time.time() + resp["result"]["expire_time"] - 120
    log.info("Token 刷新成功")
    return _token

def ensure_token():
    if not _token or time.time() >= _token_expire:
        get_token()
    return _token

# ─────────────────────────────────────────
# 通用 API 请求
# ─────────────────────────────────────────
def call_api(method, path, body=None):
    token    = ensure_token()
    body_str = json.dumps(body, separators=(",", ":")) if body else ""
    ts, sign = _sign(method, path, body_str, token)
    headers  = {
        "client_id":    CLIENT_ID,
        "access_token": token,
        "sign":         sign,
        "t":            ts,
        "sign_method":  "HMAC-SHA256",
        "Content-Type": "application/json",
    }
    url = BASE_URL + path
    if method.upper() == "GET":
        return requests.get(url, headers=headers, timeout=10).json()
    return requests.post(url, headers=headers, data=body_str, timeout=10).json()

# ─────────────────────────────────────────
# 批量指令发送（一声提示音完成所有设置）
# ─────────────────────────────────────────
def send_batch_command():
    """使用批量指令 API，一次设置所有参数"""
    path = f"/v2.0/infrareds/{DEVICE_ID}/air-conditioners/{REMOTE_ID}/scenes/command"
    body = {
        "power": TARGET_POWER,
        "mode": TARGET_MODE,
        "temp": TARGET_TEMP,
        "wind": TARGET_WIND
    }
    result = call_api("POST", path, body)
    ok = result.get("success", False)
    mode_names = ["制冷", "制热", "自动", "送风", "除湿"]
    wind_names = ["自动", "低速", "中速", "高速"]
    log.info(f"  [批量指令 power={TARGET_POWER} mode={TARGET_MODE}({mode_names[TARGET_MODE]}) temp={TARGET_TEMP}℃ wind={TARGET_WIND}({wind_names[TARGET_WIND]})] {'✓' if ok else '✗ FAIL'} → {result}")
    return ok

# ─────────────────────────────────────────
# 时间段判断
# ─────────────────────────────────────────
def is_work_hours():
    """
    判断当前是否在工作触发时段
    
    工作日（周一至周五）：
    - 00:00 ~ 08:00（睡觉时间）
    - 11:30 ~ 13:30（午休时间）
    - 17:00 ~ 23:59（晚上时段）
    
    周末（周六、周日）：
    - 00:00 ~ 23:59（全天）
    """
    now = datetime.now()
    weekday = now.weekday()  # 0=周一, 5=周六, 6=周日
    hour = now.hour
    minute = now.minute
    
    # 周末：全天触发
    if weekday in [5, 6]:
        return True
    
    # 工作日判断
    # 00:00 ~ 08:00
    if hour < 8:
        return True
    
    # 11:30 ~ 13:30
    if hour == 11 and minute >= 30:
        return True
    if hour == 12:
        return True
    if hour == 13 and minute < 30:
        return True
    
    # 17:00 ~ 23:59
    if hour >= 17:
        return True
    
    return False

def is_trigger_minute():
    """判断是否为触发分钟（仅在 02分 和 07分 触发）"""
    now = datetime.now()
    minute = now.minute
    return minute % 5 in [2, 7]

# ─────────────────────────────────────────
# 覆盖主逻辑
# ─────────────────────────────────────────
def override_ac():
    log.info("── 开始覆盖 ──────────────────────")
    try:
        send_batch_command()
        log.info("── 覆盖完成 ──────────────────────")
    except Exception as e:
        log.error(f"覆盖异常，将在下次重试: {e}")

# ─────────────────────────────────────────
# 主程序
# ─────────────────────────────────────────
if __name__ == "__main__":
    mode_names = ["制冷", "制热", "自动", "送风", "除湿"]
    wind_names = ["自动", "低速", "中速", "高速"]
    
    log.info("=" * 50)
    log.info("格力空调覆盖守护进程启动")
    log.info(f"目标参数: {TARGET_TEMP}℃, {mode_names[TARGET_MODE]}, {wind_names[TARGET_WIND]}风速")
    log.info("触发规则: 分钟数为 02分 或 07分 时触发")
    log.info("工作日: 00-08时, 11:30-13:30, 17-24时")
    log.info("周末: 全天触发")
    log.info("=" * 50)

    get_token()  # 启动时预热 Token

    while True:
        now = datetime.now()
        
        # 检查是否在触发时段
        if not is_work_hours():
            time.sleep(60)
            continue
        
        # 检查是否为触发分钟
        if is_trigger_minute():
            override_ac()
        
        # 每分钟检查一次
        time.sleep(60)
