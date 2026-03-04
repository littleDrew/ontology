# Ontology

一个面向“对象模型 + 可执行动作（Action）”的轻量后端框架，整体设计参考 Palantir Ontology 的核心思想：
- 用对象/关系表示业务实体；
- 用函数驱动的 Action 产生事务编辑（edits）；
- 通过统一的数据漏斗（Data Funnel）校验并落库；
- 提供查询接口与执行审计能力。

## doc
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

### 2) 运行一个最小 API（内存存储）

```bash
python - <<'PY'
from ontology import InMemoryGraphStore
from ontology.main import create_app
import uvicorn

app = create_app(store=InMemoryGraphStore())
uvicorn.run(app, host="0.0.0.0", port=8000)
PY
```

### 3) 访问查询接口

```bash
curl http://localhost:8000/api/v1/objects/Employee/emp-1
curl "http://localhost:8000/api/v1/objects/Employee?limit=20&offset=0"
```

## 测试

```bash
pytest -q
```

如果你愿意，我下一步可以继续补一版“架构导览文档”（包含请求链路图：`router -> service -> runner/funnel -> store/repository`），让新同学 10 分钟内能快速上手。
