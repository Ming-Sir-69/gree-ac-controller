<picture>
  <source media="(prefers-color-scheme: dark)" srcset="readme-assets/header-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="readme-assets/header-light.svg">
  <img alt="格力空调 · 云端控制配置 · ✦ EricMingle69" src="readme-assets/header-light.svg" width="100%">
</picture>

<p align="center">
  <a href="README.md">简体中文</a> · <a href="README.en.md">English</a> · <a href="PERSONAL-NOTICE.md">✦ EricMingle69</a>
</p>

# 格力空调 · 云端控制配置

通过涂鸦云 API 调用红外空调控制器的 Python / Docker 项目。
程序按已有时段规则调温或关机，供具有设备与账号控制权限的维护者阅读和配置。

## 配置前先看实现

| 文件 | 用途 |
| --- | --- |
| [ac_final.py](ac_final.py) | 云 API、时段规则、模式切换与定时循环 |
| [docker-compose.yml](docker-compose.yml) | 容器、时区、日志与环境参数 |
| [Dockerfile](Dockerfile) | Python 3.11 与 requests 依赖 |
| [.env.example](.env.example) | 本机配置样式 |

使用本人所有或已获明确授权的设备与账号。
当前没有独立的仅模拟入口；启动后会发送真实设备控制指令。

## 启动前检查

1. 根据 `.env.example`准备本机 `.env`，填入自己的授权配置。
2. 核对设备标识、涂鸦 API 权限、网络及配置的目标是否一致。
3. 阅读 `get_mode()`中的作息安排，按实际授权用途适配。
4. 检查时区、温度、模式、风速和触发参数后再启动。

真实凭据不进入仓库、截图或公开日志。

## 已有命令行入口

```sh
docker-compose up -d
docker-compose logs -f
docker-compose down
```

日志用于核对配置及 API 响应，不代表设备已经实际执行。

## 当前调度参数

`TRIGGER_TIME=00:30`采用 `MM:SS`，分钟按 5 取模，是每五分钟周期的首选窗口，不是午夜时刻。
`TRIGGER_WINDOW=2`提供秒级容差，`FALLBACK_RATIO=1.3`定义超时补发倍率。
`OFF_CHECK_INTERVAL=30`单位为分钟，关机按独立间隔检查；模式切换还可触发即时处理。
这些机制不保证固定响应延迟，旧 `01:00`说明不能代替当前配置。

## 许可与权限

当前没有覆盖原代码的 LICENSE/NOTICE；复用范围需确认。
个人文档维护身份不授予账号或设备控制权，设备操作权限与代码许可分别判断。

---

文档维护：**✦ EricMingle69** · [Ming-Sir-69](https://github.com/Ming-Sir-69)  
[个人标识、许可与权限说明](PERSONAL-NOTICE.md) · 明暗页眉随 GitHub 主题自动切换。
