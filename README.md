# thomas-core

THOMAS 认证 / 身份 / 合规 / RAG 核服务。**独立发版仓**，由 `GenzLTD/looma-zervi` 经
`git filter-repo` subtree split 抽出，保留核路径的完整提交历史。

## 来源与边界

| 项 | 值 |
|---|---|
| 来源仓 | `GenzLTD/looma-zervi` |
| 切出基线 | `feat/core-selfcontained` @ `6e3d329`（刀 5 核自足化 tip） |
| 切出方式 | `git filter-repo --path backend/src/thomas_core/ ... --prune-empty auto` |
| 历史 | 26 个提交（含刀 2 分包 → 刀 5 自足化全链），40 个文件 |
| 核体量 | 4,233 行 Python |
| 不含 | 产品 27 蓝图、`DatabaseManager.init_schema()` 全量 DDL、timeline / reports / central_brain 实现 |

**单库不拆文件**：核与产品同写一个 `looma.db`，只是建表权分开。核启动时 ensure
`core_schema.sql`（7 表）和 `profile_schema.sql`（画像事实表 `profile_events`），
再加上 `schema_meta`。产品表由宿主 ensure `product_schema.sql`。Chroma 只做检索。
`THOMAS_SCHEMA_SPLIT=0` 为 legacy 模式，核退回跑 `DatabaseManager.init_schema()`（本仓
不含该实现，故独立部署必须保持 `THOMAS_SCHEMA_SPLIT=1`）。

## 目录

```
backend/
  run_core.py                       # :5300 入口
  requirements.txt                  # 来源仓全量依赖（含产品侧，仅作溯源）
  requirements-core.txt             # 本仓实际需要的依赖（推荐用它安装）
  src/
    __init__.py
    db/core_schema.sql              # core 7 表 DDL
    db/product_schema.sql           # product 50 表 DDL（宿主侧，核只读其路径）
    thomas_core/
      app.py                        # create_core_app()
      config.py                     # CoreConfig（只读核段）
      runtime.py                    # /health 的 git_commit 解析
      db/core_db.py                 # CoreDB：连接 + 身份 / 配额 / 计量（26 方法）
      db/schema_loader.py           # scope-aware DDL 加载 + LF 归一版本校验
      hooks.py                      # 埋点 / 报告注入点（缺省惰性宿主实现或 no-op）
      brain.py                      # 意图解析派发注入点
      auth/ compliance/ identity/ rag/ routes/ llm/ utils/ quota.py ...
scripts/
  smoke_core.py                     # 无宿主依赖的四端点 + 建表 + 自足性冒烟
.env.example                        # 环境变量键名（全部空值，无密钥）
```

## 启动

```bash
cd backend
python -m venv .venv && .venv/Scripts/pip install -r requirements-core.txt   # Windows
cp ../.env.example .env            # 按需填值；生产必须覆盖 SECRET_KEY / JWT_SECRET
set THOMAS_SCHEMA_SPLIT=1
set DATABASE_PATH=%CD%\data\core.db
set FLASK_PORT=5300
python run_core.py
```

验活：`curl http://127.0.0.1:5300/health` →
`{"service":"thomas-core","deploy_track":"looma", ...}`。

## 三个注入点（宿主集成时必读）

独立仓**不含产品实现**，以下能力由宿主在 `create_app()` 时注册；未注册时的行为见括号：

| 注入点 | 注册函数 | 未注册时 |
|---|---|---|
| 意图解析 / 派发 | `src.thomas_core.brain.register_brain()` | `/v1/ask` 抛 `BrainNotConfigured` → 退配额 + 500，**不会静默返回空答案** |
| 时间线埋点 | `src.thomas_core.hooks.register_timeline_logger()` | no-op（best-effort，异常吞掉） |
| 匹配报告读取 | `src.thomas_core.hooks.register_report_manager_factory()` | 返回 `None` |

`hooks.py` / `brain.py` 里仍保留指向 `src.timeline.*`、`src.reports.*`、
`src.agents.central_brain` 的**惰性 import**，但全部包在 `try/except` 内 —— 这是
「同仓部署时零改动」的兼容路径，独立仓里这些模块不存在也不会导致启动失败。

## 安全注意

- `CoreConfig` 带开发默认 `SECRET_KEY=dev-secret-change-me` 与固定 `JWT_SECRET` 默认值，
  **仅用于本地/dev**；生产必须通过环境变量覆盖，否则等于使用公开密钥。
- 所有 Supabase / DeepSeek / 微信 / Google / 华为凭证都从环境变量读取，仓内与历史中
  **无硬编码密钥**（切仓前已对全部 26 个提交、58 个文本 blob 做过敏感串扫描，0 命中）。
- Web 客户端请求走 `urllib` 时须设 `NO_PROXY=127.0.0.1,localhost`，否则会被
  `HTTP_PROXY` 劫持到代理。

## 本仓自检

```bash
cd backend
python ../scripts/smoke_core.py
```

判据：`src.app` 不可导入 / health 200 + `service=thomas-core` + `chroma_ok` /
register 201 / login 200 / consent 200 / 9 张表 + `schema_meta` 有 `core` 与 `profile` /
ask 无 brain 时 500（非静默空答案）/ `BrainNotConfigured` 可捕获 / hooks 缺省 no-op 不炸 /
答题结算写入 `profile_events` / 导出带身份元数据 / 删除后 SQL 与 Chroma 都空。
exit 0 表示全过。

## 与宿主仓的关系

- 本仓是**物理切分后的独立副本**，不是 submodule；两边的后续改动不会自动同步。
- 冻结锚（锚 B 10/10、锚 C 8/8）、键位负向断言、NFR 基线等验收脚本仍留在
  `GenzLTD/looma-zervi`；跨进程验收需两仓同时起。
- 切仓基线：`GenzLTD/looma-zervi` 的 **main `7f112dc`**（PR #53 刀 5 核自足化合入后的主线），
  即本仓历史与来源仓主线同源，不是分支快照。
- 合入后门禁（在 `7f112dc` 上复跑）：锚 B **10/10**、锚 C **8/8**、
  键位 **4/4 × 2 模式**；切仓前 `pytest tests` **402 passed**、#53 CI **5/5 pass**。

## Gitee 备份链路（opt-in）

现有 `zervi-genz/gitee-sync-bot` 是**单向 Gitee → GitHub**、目标 `GH_OWNER=zervi-genz`
个人号，自动发现的是 Gitee 侧仓库并用 `--prune --force` 推镜像。本仓是 `GenzLTD`
组织仓，既不在 Gitee、也不在 `zervi-genz` 个人号下，**不能纳入该 bot 的自动发现**
（否则会被 Gitee 同名仓覆盖）。

因此本仓自带 `.github/workflows/mirror-to-gitee.yml` 做反向镜像，**默认 no-op**：

| 需要账号侧配置 | 说明 |
|---|---|
| `secrets.GITEE_TOKEN_WRITE` | Gitee **可写** token；bot 现有的 `GITEE_TOKEN` 是 `projects:read` 只读，不能推送 |
| `vars.GITEE_MIRROR_REPO` | 形如 `zervi-genz/thomas-core`，须先在 Gitee 侧建好目标仓 |

两项齐全后，每次 push `main` 自动把分支与 tag 镜像到 Gitee；缺任一项则打印 notice 并
正常结束，不改任何远端。镜像采用 `--prune --force`，**请勿在 Gitee 侧直接提交**。
