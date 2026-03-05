# Ontology

一个面向“对象模型 + 可执行动作（Action）”的轻量后端框架，整体设计参考 Palantir Ontology 的核心思想：
- 用对象/关系表示业务实体；
- 用函数驱动的 Action 产生事务编辑（edits）；
- 通过统一的数据漏斗（Data Funnel）校验并落库；
- 提供查询接口与执行审计能力。

## Doc
Detail docs in zread
[![zread](https://img.shields.io/badge/Ask_Zread-_.svg?style=flat-square&color=00b0aa&labelColor=000000&logo=data%3Aimage%2Fsvg%2Bxml%3Bbase64%2CPHN2ZyB3aWR0aD0iMTYiIGhlaWdodD0iMTYiIHZpZXdCb3g9IjAgMCAxNiAxNiIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHBhdGggZD0iTTQuOTYxNTYgMS42MDAxSDIuMjQxNTZDMS44ODgxIDEuNjAwMSAxLjYwMTU2IDEuODg2NjQgMS42MDE1NiAyLjI0MDFWNC45NjAxQzEuNjAxNTYgNS4zMTM1NiAxLjg4ODEgNS42MDAxIDIuMjQxNTYgNS42MDAxSDQuOTYxNTZDNS4zMTUwMiA1LjYwMDEgNS42MDE1NiA1LjMxMzU2IDUuNjAxNTYgNC45NjAxVjIuMjQwMUM1LjYwMTU2IDEuODg2NjQgNS4zMTUwMiAxLjYwMDEgNC45NjE1NiAxLjYwMDFaIiBmaWxsPSIjZmZmIi8%2BCjxwYXRoIGQ9Ik00Ljk2MTU2IDEwLjM5OTlIMi4yNDE1NkMxLjg4ODEgMTAuMzk5OSAxLjYwMTU2IDEwLjY4NjQgMS42MDE1NiAxMS4wMzk5VjEzLjc1OTlDMS42MDE1NiAxNC4xMTM0IDEuODg4MSAxNC4zOTk5IDIuMjQxNTYgMTQuMzk5OUg0Ljk2MTU2QzUuMzE1MDIgMTQuMzk5OSA1LjYwMTU2IDE0LjExMzQgNS42MDE1NiAxMy43NTk5VjExLjAzOTlDNS42MDE1NiAxMC42ODY0IDUuMzE1MDIgMTAuMzk5OSA0Ljk2MTU2IDEwLjM5OTlaIiBmaWxsPSIjZmZmIi8%2BCjxwYXRoIGQ9Ik0xMy43NTg0IDEuNjAwMUgxMS4wMzg0QzEwLjY4NSAxLjYwMDEgMTAuMzk4NCAxLjg4NjY0IDEwLjM5ODQgMi4yNDAxVjQuOTYwMUMxMC4zOTg0IDUuMzEzNTYgMTAuNjg1IDUuNjAwMSAxMS4wMzg0IDUuNjAwMUgxMy43NTg0QzE0LjExMTkgNS42MDAxIDE0LjM5ODQgNS4zMTM1NiAxNC4zOTg0IDQuOTYwMVYyLjI0MDFDMTQuMzk4NCAxLjg4NjY0IDE0LjExMTkgMS42MDAxIDEzLjc1ODQgMS42MDAxWiIgZmlsbD0iI2ZmZiIvPgo8cGF0aCBkPSJNNCAxMkwxMiA0TDQgMTJaIiBmaWxsPSIjZmZmIi8%2BCjxwYXRoIGQ9Ik00IDEyTDEyIDQiIHN0cm9rZT0iI2ZmZiIgc3Ryb2tlLXdpZHRoPSIxLjUiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIvPgo8L3N2Zz4K&logoColor=ffffff)](https://zread.ai/littleDrew/ontology)

## 仓库功能总览

当前仓库主要包含 4 条能力主线：

1. **对象与关系存储（Instance / GraphStore）**
   - 定义对象编辑模型（新增/修改/删除对象、增删关系）。
   - 通过 `GraphStore` 抽象支持多种后端（内存实现、Neo4j 实现）。
   - 提供统一读写接口 `InstanceService`。

2. **Action 编排与执行（Action Service）**
   - 支持 Action 定义版本化、提交与执行状态追踪。
   - 执行过程会把函数结果归一化为事务编辑，再交给 `InstanceService` 应用。
   - 内置日志、通知、补偿/修复与 outbox 重试机制（阶段化能力）。

3. **函数运行时（Execution Runtime）**
   - 提供 `ActionRunner`、`Context`、`ObjectProxy`，用于在函数内捕获属性修改与关系变更。
   - 将函数副作用沉淀为结构化 edits，便于审计、回放与测试。

4. **HTTP API（FastAPI）**
   - `action/api/router.py`：`/api/v1/actions/*` 新版接口。
   - `action/api/legacy_router.py`：兼容旧接口 `/actions/*`。
   - `search/api/router.py`：对象查询接口 `/api/v1/objects/*`。

## 目录结构（核心）

```text
ontology/
  main.py                    # 应用装配入口 create_app
  action/
    api/                     # Action HTTP 与编排服务
    execution/               # 函数运行时、通知、沙箱
    storage/                 # 仓储抽象、SQL/内存实现、编辑模型
  instance/
    api/service.py           # DataFunnelService + InstanceService
    storage/graph_store.py   # GraphStore 抽象与实现
  search/
    api/
      router.py              # /objects 查询路由
      service.py             # SearchService（查询编排）
```

## 快速开始

### 1) 安装

```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install fastapi uvicorn sqlalchemy pytest httpx
```

如需 Neo4j：

```bash
pip install neo4j
```

如需 MySQL 持久化存储测试：

```bash
pip install pymysql
```

### 2) 运行一个最小 API（内存存储）

```bash
python -m ontology.main
```

可选参数：

```bash
python -m ontology.main --host 127.0.0.1 --port 9000 --no-legacy-routes
```

### 3) 访问查询接口

```bash
curl http://localhost:8765/api/v1/objects/Employee/emp-1
curl "http://localhost:8765/api/v1/objects/Employee?limit=20&offset=0"
```

启动后可查看自动生成的 API 文档：

```bash
# Swagger UI
http://localhost:8765/docs

# ReDoc
http://localhost:8765/redoc

# OpenAPI JSON
http://localhost:8765/openapi.json
```

> 说明：`/` 根路径默认会重定向到 `/docs`。如果看到 `404 Not Found`，请确认使用的是最新代码并优先访问上面的 `/docs` 或 `/api/v1/*` 接口路径。

## 测试

```bash
pytest -q
```

### MySQL 持久化存储测试说明

仓库中的 `SqlActionRepository` 基于 SQLAlchemy，可通过 `MYSQL_TEST_URL` 对接 MySQL 执行 smoke 测试。

1) 安装 MySQL（Ubuntu）：

```bash
sudo apt-get update
sudo apt-get install -y mysql-server
```

2) 创建测试库（示例）：

```bash
mysql -uroot -e "CREATE DATABASE IF NOT EXISTS ontology_test;"
```

3) 配置连接串并执行用例：

```bash
export MYSQL_TEST_URL='mysql+pymysql://root@127.0.0.1:3306/ontology_test'
pytest -q tests/test_sql_repository_mysql.py
```

> 未设置 `MYSQL_TEST_URL` 时，该用例会自动 `skip`。

### Neo4j 集成测试说明

`tests/test_action_flow.py::test_action_function_applies_edits_to_neo4j` 依赖外部 Neo4j 实例。  
若未设置以下环境变量，测试会自动 `skip`：

```bash
export NEO4J_URI=bolt://127.0.0.1:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD=your-password
```

另外需安装 Neo4j Python 驱动（`pip install neo4j`）。
