# Aggregator Web 管理平台

基于 [vue-vben-admin](../vue-vben-admin/) 设计语言与 [PRD v2.4](../docs/2026-10-04/PRD.md) 实现的 aggregator Web 化管理平台，前后端分离：

```
aggregator-main/
├── backend/                 # FastAPI 后端（Python 3.13）
│   ├── app/
│   │   ├── api/             # REST 路由：auth/users/sources/params/tasks/results/storage/dashboard
│   │   ├── engine_adapter/  # 引擎适配：runner（任务执行器）/publisher（准原子发布）/engine（复用 subscribe/）
│   │   ├── services/        # 业务服务：sources/settings/storage/export/scheduler/secrets
│   │   ├── models.py        # SQLAlchemy 2.0 ORM（PRD §6 数据模型）
│   │   └── main.py          # 应用工厂 + 响应包中间件 + SPA 托管
│   ├── tests/               # pytest（96 项：单元 + 集成）
│   ├── run.py               # 启动入口
│   └── pytest.ini
├── frontend/                # Vue 3 + Vite 前端（vben 设计语言）
│   └── src/
│       ├── api/             # axios 客户端（统一响应包/401 跳转）
│       ├── layouts/         # AdminLayout（侧边栏 + 顶栏 + RBAC 菜单）
│       ├── router/          # 路由守卫（登录态 + 角色）
│       ├── stores/          # Pinia auth store
│       └── views/           # 11 个页面（对应 PRD §8 菜单）
├── subscribe/               # 既有聚合引擎（爬取/注册/验活/转换，原样复用）
├── docs/2026-10-04/         # PRD v2.4 + 12 页 HTML 原型
└── data/                    # 运行数据（SQLite + 本地产物，gitignored）
```

## 快速开始

```bash
# 1. 安装后端依赖
pip install -r backend/requirements-web.txt

# 2. 安装前端依赖并构建
cd frontend && npm install && npm run build && cd ..

# 3. 启动（单进程：API + 前端静态托管，默认 8080）
python backend/run.py
```

打开 http://127.0.0.1:8080 ，默认管理员 `admin / admin123`（可通过环境变量
`AGG_ADMIN_USER` / `AGG_ADMIN_PASSWORD` 修改，首次启动请修改）。

### 开发模式

```bash
# 后端（热重载）
python backend/run.py            # 或 uvicorn app.main:app --app-dir backend/app --reload

# 前端（Vite dev server，/api 代理到 8080）
cd frontend && npm run dev
```

## 环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `AGG_DATA_DIR` | `./data` | 数据根目录（SQLite + 本地产物） |
| `AGG_DATABASE_URL` | `sqlite:///<data_dir>/aggregator.db` | 数据库连接 |
| `AGG_JWT_SECRET` | 自动生成 | JWT 签名密钥（首次启动写入 `data/.secret.key`） |
| `AGG_ADMIN_USER` / `AGG_ADMIN_PASSWORD` | `admin` / `admin123` | 初始管理员 |
| `AGG_PORT` / `AGG_HOST` | `8080` / `127.0.0.1` | 监听地址 |
| `AGG_ENGINE` | 空（真实引擎） | `hermetic` 时启用确定性测试引擎（E2E/演示，无网络依赖） |

## 测试

```bash
# 后端：96 项 pytest（TDD，先红后绿）
cd backend && python -m pytest

# 前端：vitest 单元测试
cd frontend && npm test
```

核心链路由 E2E 覆盖（登录/RBAC/源管理/参数/任务全生命周期/准原子发布与补偿/导出），
真实网络与 mihomo 二进制相关的引擎阶段在集成测试中以 HermeticEngine 注入验证。

## 关键设计（PRD v2.4 摘要）

- **系统库为旧数据权威源**：订阅池 = 上轮 full/回测存活节点的来源订阅（派生）；remains = 上轮存活节点；full/回测默认合并 remains 重新验活。
- **存储目标纯发布**：创建任务时绑定写入目标（回测/full 必填）；旧数据只从系统库读；发布准原子——全部目标写成功才置 success，失败记 `publish_pending` 可在详情页「重试发布」补偿。
- **RBAC**：admin/operator/viewer 三角色服务端强校验；存储目标管理仅 admin。
- **定时执行**：`engine_adapter/scheduler.py`（APScheduler，lifespan 启动）为每个启用的定时任务注册 cron 作业，到点自动生成 `trigger=schedule` 的 run；执行器占用时跳过本轮并记录原因，下轮恢复。界面通过图形化间隔构建器（分钟/小时/天/周/每天/每周）创建，不暴露 cron 表达式。
- **引擎复用**：`engine_adapter/engine.py` 把 DB 配置合成为 `CrawlConfig`，直接调用 `subscribe/` 的 `crawl.engine.run` / `workflow.executewrapper` / `pipeline.check_alive_proxies` / `subconverter`。
