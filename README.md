# 文广学生票监控

上海文化广场（SHC Theatre）学生票自动化监控器 —— 通过官方 API 定时检测指定演出的学生票档位状态，一旦出现"可购"或"售罄"变化，立即通过手机推送通知，帮助你第一时间抢到学生票。

## 项目简介

上海文化广场的演出经常设有少量学生票（如 80 元档），但放票时间不确定、数量稀少，手动刷新页面容易错过。本项目以固定间隔自动查询官方接口，识别含"学生"字样的票档，检测"有票 ↔ 售罄"的状态转换，并通过 **PushPlus / Server酱 / 企业微信群机器人 / 邮件** 等多种渠道推送到你的手机，全程无需打开网页。

**核心能力：**

- 自动发现上海文化广场官网的演出列表，无需手动维护演出 ID
- 识别每个演出的学生票档位（票价、场次、余票数）
- 只关注"有票 ↔ 售罄"两种关键状态变化，避免无效打扰
- 支持多人同时接收推送（每人一个 token / 或企微群一键全群通知）
- 支持静默时段，夜间不打扰
- 配置热加载：修改 `config.json` 即时生效，无需重启

## 核心功能

- **学生票状态监控**：定时查询指定演出的学生票档位（场次、价格、余票、售罄状态）
- **演出自动发现**：从节目列表页抓取全部演出，可单独启用/禁用每个演出
- **状态变化检测**：仅在上新（无票 → 有票）与售罄（有票 → 无票）时触发通知
- **多人推送通知**：支持 PushPlus、Server酱、企业微信群机器人、QQ 邮箱，可同时配置多人
- **静默时段**：可配置夜间不推送（默认关闭）
- **可调监控频率**：检查间隔默认 30 秒（可按需调整，建议合理设置避免给官网造成压力）

## 技术栈

| 类别 | 说明 |
| ---- | ---- |
| 语言 | Python 3 |
| 依赖 | `requests`（`>=2.28.0`） |
| 数据源 | 上海文化广场官网公开接口 `webapi.ashx`（Gettblprogram / GettblpricelevelList_ns） |
| 推送渠道 | PushPlus、Server酱（ServerChan）、企业微信群机器人、SMTP 邮件（QQ/163/Gmail 等） |
| 运行方式 | 命令行 / Windows 批处理脚本 |
| 数据库 | 无（状态保存在本地 JSON 文件） |

## 项目结构

```
文广学生票监控/
├── monitor.py           # 主程序：监控逻辑 + 状态检测 + 多通道推送
├── config.json          # 本地配置（含推送 Token，已被 .gitignore 忽略，不入库）
├── config.example.json  # 配置模板（无真实密钥，可直接复制使用）
├── last_state.json      # 上次检查状态（运行时自动生成，不入库）
├── monitor.log          # 运行日志（运行时自动生成，不入库）
├── requirements.txt     # Python 依赖
├── run.bat              # Windows 一键安装依赖并启动监控
├── test_push.bat        # 测试推送是否可用
├── README.md
└── .gitignore
```

## 环境要求

- Python 3.8 及以上（已在 Python 3.14 下验证运行）
- Windows / macOS / Linux 均可（Windows 下可直接使用 `run.bat`）

## 安装

```bash
# 1. 克隆仓库
git clone https://github.com/9thawk/wen-guang-student-ticket-monitor.git
cd wen-guang-student-ticket-monitor

# 2. 安装依赖
pip install -r requirements.txt
```

Windows 用户也可以直接双击 `run.bat`，脚本会自动安装依赖并启动监控。

## 配置

```bash
# 复制配置模板为实际配置
copy config.example.json config.json    # Windows
# cp config.example.json config.json    # macOS / Linux
```

然后编辑 `config.json`，按需填写：

| 配置项 | 说明 |
| ------ | ---- |
| `performances` | 要监控的演出列表（`article_id` 为官网节目 ID，`enabled` 控制是否监控） |
| `check_interval_seconds` | 检查间隔（秒），默认 30 |
| `request_timeout_seconds` | 请求超时（秒），默认 15 |
| `quiet_hours_enabled` / `quiet_start` / `quiet_end` | 静默时段开关与时间段 |
| `pushplus_tokens` | PushPlus Token 数组，支持多人（每人一个 token） |
| `serverchan_keys` | Server酱 SendKey 数组，支持多人 |
| `wechat_work_webhook` | 企业微信群机器人 Webhook 地址，一条消息通知全群 |
| `email_user` / `email_pass` / `email_to` | QQ 邮箱账号、16 位授权码、收件人列表（可不填） |

> **安全提醒**：`config.json` 包含你的推送凭证，已被 `.gitignore` 忽略，请勿提交到 Git；仓库中仅提供不含密钥的 `config.example.json` 模板。

## 启动项目

```bash
# 持续监控（默认模式）
python monitor.py

# 单次检查（检查一次并退出）
python monitor.py --once

# 仅查看当前状态
python monitor.py --status

# 测试推送（执行一次真实检查并强制推送当前状态）
python monitor.py --test-push
```

Windows 下也可以：

- 双击 `run.bat` —— 一键启动持续监控
- 双击 `test_push.bat` —— 测试推送是否正常

## 构建

本项目为纯 Python 脚本，无构建步骤，安装依赖后即可直接运行。

## 部署

本项目无需 Docker / 云服务等部署，直接在**本机或一台常开的服务器**上运行即可：

- 方式一：命令行前台运行（`python monitor.py`）
- 方式二：Windows 双击 `run.bat`（弹出窗口运行，Ctrl+C 停止）
- 方式三：配合 Windows 任务计划程序 / systemd 等设为开机自启，实现 7×24 小时常驻监控

## 注意事项

- 项目通过上海文化广场官网公开接口查询数据，请合理设置检查间隔（默认 30 秒已足够），避免过度频繁请求影响官网正常服务
- 学生票通常数量极少，建议同时开启多个推送渠道提高送达率
- 推送失败不会影响监控主流程，日志会记录失败原因，可用 `python monitor.py --test-push` 验证配置
- 每次运行会重新读取 `config.json`，修改配置后无需重启
- `monitor.log` 会持续增长，请定期清理或使用日志轮转
- 演出下架 / 接口变更可能导致监控异常，日志中的报错信息可用于排查

## License

本项目目前**暂未指定开源 License**，版权所有归作者所有。如需使用或二次分发，请联系作者确认。
