# 格力空调 Docker 部署指南

## 文件结构

```
gree-ac-controller/
├── docker-compose.yml   # Docker Compose 配置
├── Dockerfile           # Docker 镜像构建文件
├── ac_final.py          # 主程序脚本
└── README.md           # 本文件
```

## 快速部署

### 方式一：Docker Compose UI（推荐）

在飞牛 NAS 的 Docker Compose 界面中：

1. 将 `docker-compose.yml` 内容粘贴进去
2. 在环境变量配置区域填写参数
3. 点击部署

### 方式二：命令行部署

```bash
docker-compose up -d        # 启动
docker-compose logs -f     # 查看日志
docker-compose restart     # 重启
docker-compose down        # 停止
```

## 参数配置说明

### 涂鸦 API 配置

| 环境变量 | 说明 |
|----------|------|
| CLIENT_ID | 涂鸦 API Key（从涂鸦 IoT 平台获取） |
| CLIENT_SECRET | 涂鸦 API Secret（从涂鸦 IoT 平台获取） |
| DEVICE_ID | 红外遥控器设备 ID（从涂鸦 App 或平台获取） |
| REMOTE_ID | 空调遥控器 ID（通过 API 获取） |
| BASE_URL | 涂鸦 API 地址（默认：https://openapi.tuyacn.com） |

### 空调参数配置

| 环境变量 | 默认值 | 可输入值 | 说明 |
|----------|--------|--------|------|
| `TARGET_POWER` | `on` | `on` / `开` / `开机` / `1` = 开机<br>`off` / `关` / `关机` / `0` = 关机 | 开关机 |
| `TARGET_MODE` | `cool` | `cool` / `制冷` / `冷` / `0` = 制冷<br>`heat` / `制热` / `热` / `暖` / `1` = 制热<br>`auto` / `自动` / `2` = 自动<br>`fan` / `送风` / `风` / `3` = 送风<br>`dry` / `除湿` / `湿` / `4` = 除湿 | 运行模式 |
| `TARGET_TEMP` | `24` | `16` ~ `30`（整数） | 目标温度（℃） |
| `TARGET_WIND` | `auto` | `auto` / `自动` / `0` = 自动<br>`low` / `低` / `低速` / `1` = 低速<br>`medium` / `med` / `中` / `中速` / `2` = 中速<br>`high` / `高` / `高速` / `3` = 高速 | 风速 |

> 所有文字输入忽略大小写，`Cool`、`COOL`、`cool` 效果相同。

## 常用配置示例

### 制冷 24℃ 自动风速
```yaml
TARGET_POWER: 开
TARGET_MODE: 制冷
TARGET_TEMP: 24
TARGET_WIND: 自动
```

### 制冷 26℃ 低速风
```yaml
TARGET_POWER: 开
TARGET_MODE: 制冷
TARGET_TEMP: 26
TARGET_WIND: 低
```

### 制热 28℃ 中速风
```yaml
TARGET_POWER: 开
TARGET_MODE: 制热
TARGET_TEMP: 28
TARGET_WIND: 中
```


## 查看日志

```bash
# 实时查看日志
docker logs -f gree-ac-controller

# 查看最近 100 行日志
docker logs --tail 100 gree-ac-controller
```

## 故障排查

1. **容器无法启动**
   ```bash
   docker logs gree-ac-controller
   ```

2. **API 调用失败**
   - 检查 CLIENT_ID 和 CLIENT_SECRET 是否正确
   - 检查网络连接

3. **Token 获取失败**
   - 确认涂鸦开发者平台已开通相关 API 权限
