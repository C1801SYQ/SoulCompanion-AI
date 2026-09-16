# Deployment / 部署与运行

## 1. 选择运行模式

| 模式 | 入口 | 能力边界 |
| --- | --- | --- |
| 本地 Web 看板 | `python -m web.app` | 轻量 API 与页面；没有注入 bridge 时不代表摄像头/麦克风已工作 |
| 集成运行 | `python launch.py` | 按主 README 配置感知模块、模型与设备 |
| 静态演示 | `python scripts/build_site.py` | 演示数据与静态界面，不运行 Python 感知链路 |

项目是情感交互研究原型；看板与情绪推断不能用于临床诊断或疗效判断。

## 2. 本地看板

Python 3.12 为本轮验证环境。

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -r requirements-web.txt
python -m web.app --host 127.0.0.1 --port 8000
```

访问 `http://127.0.0.1:8000`；API 文档位于 `/docs`。
`GET /healthz` 返回 HTTP 200 和版本号，只检查进程存活，不初始化设备、模型或数据库。
使用 `/api/bridge/status` 查看 bridge 状态；进程存活不意味着设备数据可用。

## 3. 配置与数据

| 环境变量 | 默认值 / 用途 |
| --- | --- |
| `SOULCOMPANION_DB` | 仓库 `data/emotional_db.sqlite`；部署时建议指定持久化卷中的绝对路径 |
| `SOULCOMPANION_DASHBOARD_HOST` | `127.0.0.1`；CLI `--host` 可覆盖 |
| `SOULCOMPANION_DASHBOARD_PORT` | `8000`；CLI `--port` 可覆盖 |
| `SOULCOMPANION_CORS_ORIGINS` | 本机来源，逗号分隔 |

配置通过进程环境变量读取，复制 `.env.example` 不会自动加载它。
SQLite 数据应持久保存；备份时使用 SQLite backup API，或停止写入后处理数据库及 WAL 文件。
不要把情绪记录提交到 Git。

## 4. 受控部署

当前 API 没有完整的用户认证与多租户隔离，默认绑定本机。
远程演示应使用演示数据；实际个人数据访问需要先增加身份认证、访问控制和 HTTPS。
CORS 不是身份认证。不要直接将含真实记录的接口暴露到公网。
集成 bridge 使用进程内共享状态，部署保持单 worker；多 worker 不能共享设备状态。

本仓库未提供经过验证的 Vercel 无服务器持久化方案；静态托管只能运行静态演示。

## 5. 验证

```bash
python -m pip install -r requirements-web.txt -r requirements-dev.txt
python -m pytest
```

测试覆盖情绪逻辑、存储和 Web 参数契约。历史查询 `limit` 为 1–500，`offset` 为 0–1000000；
按天查询为 1–365。非法请求返回 422，不进入数据库查询。
