# Object Monitor Implementation Explain

> 面向新同学的走读文档：从“配置发布”到“实时评估再到动作执行”的完整代码路径说明。

## 1. 模块目标与边界

`object_monitor` 的职责是：

1. 接收/管理监控定义（monitor definition），编译成可执行 artifact；
2. 在对象变更进入后做标准化、上下文补全、过滤与规则评估；
3. 基于评估结果触发 action，并把全过程写入 ledger 以支持幂等与审计。

代码目录按职责分为：

- `api/`：对外服务接口（定义创建、发布、查询、运行时入口）；
- `compiler/`：DSL 与编译逻辑；
- `runtime/`：事件处理主链路（normalize/context/filter/evaluator/dispatcher）；
- `define/storage/` + `runtime/storage/`：分域持久化（in-memory/sqlite/sqlalchemy）；
- `persistence/sql_models.py`：SQLAlchemy ORM 模型定义（define/runtime 共用）。
- `__init__.py`：对外导出公共能力。

---

## 2. 控制面：Definition -> Artifact -> 发布/回滚

### 2.1 API 层入口

`api/service.py` 的 `ObjectMonitorService` 组织控制面流程：

- `create_definition(...)`：校验定义并编译；
- `publish_version(...)`：切换 active 版本；
- `rollback(...)`：回退至历史版本；
- `get_active_artifact(...)`：运行时读取当前生效 artifact。

控制面接口通过 `MonitorReleaseService` 抽象，所以上层逻辑不关心落地存储是 in-memory、SQLite 还是 SQLAlchemy。

### 2.2 编译链路

- `compiler/dsl.py`：定义 DSL 数据结构与校验约束；
- `compiler/service.py`：将 DSL 编译为运行时 artifact（规则表达式、字段依赖、动作配置等）。

编译产物在发布后与版本绑定，由 release service 存储。

---

## 3. 数据面主链路：事件进入后如何处理（阶段 1 裁剪版）

主链路围绕 runtime 组件串联。

### 3.1 入口与单通道主流程

阶段 1 默认只启用 **Neo4j Streams/APOC 单通道**，对应 `runtime/change_pipeline.py` 的 `SingleChannelIngestionPipeline`：

- Streams/APOC 事件映射：把输入 payload 映射成统一变化事件；
- `SingleChannelIngestionPipeline`：处理单链路输入，做去重、规范化和 raw 事件发布；
- `InMemoryRawEventBus`：最小可运行 raw bus（测试/本地验证可用）。

`DualChannelIngestionPipeline` 仍保留用于后续恢复双链路（Outbox + Secondary Source）时复用，但不是阶段 1 默认主流程。

补充（Streams 事件映射）：

- `runtime/api/change_capture_app.py` 已支持 Neo4j Streams 的 `node` 与 `relationship` 两类 payload：
  - `node`：`object_type` 取节点 label，`object_id` 取 payload.id；
  - `relationship`：`object_type` 取关系 label（如 `WORKS_AS`），`object_id` 取关系 id（缺失时退化为 `start->label->end`）。
- `ObjectChangeEvent` 仍保持统一领域模型，但 REST 入参中的 `tenant_id` 提供默认值 `global`，避免 Streams 接入时引入业务租户前置依赖。

### 3.2 标准化与去重

`runtime/normalizer.py` 负责：

- 事件 canonical 化（关键字段统一）；
- 基于 event key / idempotency token 去重；
- 识别版本回退或乱序情形并输出 reconcile 信号。

### 3.3 上下文构建与直接查询兜底

`runtime/context_builder.py` 同时支持两类 context 来源：

- `ContextBuilder + InMemoryContextStore`：复制模式（本地物化）；
- `Neo4jQueryContextStore`：阶段 1 裁剪时可直接查 Neo4j 的 provider 兜底实现。

### 3.4 过滤

`runtime/event_filter.py` 先做粗过滤（例如对象类型、变更字段），再做细过滤（规则依赖字段是否命中），减少无效评估。

### 3.5 评估与幂等

`runtime/evaluator.py` 执行规则计算并写 `EvaluationLedger`：

- 首次命中写入评估结果；
- 重复事件按幂等键抑制重复写入/重复触发；
- 对异常状态可以输出 `ReconcileEvent` 进入修复链路（`runtime/reconcile.py`）。

### 3.6 动作执行（薄执行层）

阶段 1 主流程使用 `runtime/thin_action_executor.py` 的 `ThinActionExecutor`：

- 幂等键生成；
- 同步调用 Action Gateway；
- 返回成功/失败结果。

`runtime/action_dispatcher.py`（重试、DLQ、重放、Activity ledger）保留为下一阶段增强能力，不作为本阶段主链路依赖。

`runtime/action_gateway_adapter.py` 提供与 action 模块的 HTTP 适配，隔离 monitor 与 action 内部实现差异。

### 3.7 阶段 1 明确延后项

- Tx Outbox publish 启用（接口保留）；
- Reconcile Scanner 定时补偿；
- Activity 审计落库、Retry Topics、DLQ replay；
- Dispatcher 编排增强（指数退避、死信重放）。

---

## 4. 存储层实现：从内存态到关系型

### 4.1 统一抽象

仓储抽象按域拆分：

- `define/storage/*`：`MonitorReleaseService` 能力（定义发布/回滚）
- `runtime/storage/*`：`EvaluationLedger` / `ActivityLedger` / `ChangeOutboxRepository`
- `persistence/sql_models.py`：SQLAlchemy ORM 共享模型

上层只依赖域内抽象，不直接依赖数据库驱动。

### 4.2 现有实现

- runtime 侧：`runtime/storage/models.py` + `sqlite_repository.py` + `sqlalchemy_repository.py`；
- define 侧：`define/storage/sqlalchemy_repository.py`；

SQLAlchemy 实现重点：

- 统一 ORM model 管理 release/evaluation/activity/outbox 表；
- 事务内幂等写入（依赖唯一键/冲突处理）；
- `claim` 语义支持 outbox 消费竞争。

这样可以在不改运行时主流程的情况下切换数据源。

---

## 5. 代码阅读顺序（推荐）

给新同学建议按以下顺序走读：

1. `api/contracts.py`（先看领域对象与接口）；
2. `api/service.py`（理解控制面编排）；
3. `runtime/interfaces.py`（理解运行时组件边界）；
4. `runtime/normalizer.py` → `context_builder.py` → `event_filter.py` → `evaluator.py` → `thin_action_executor.py`（阶段 1 主链路）；
5. `runtime/change_pipeline.py`（单通道主流程与去重；双通道为后续保留）；
6. `define/storage/*` + `runtime/storage/*` + `persistence/sql_models.py`（持久化替换机制）；
7. `tests/object_monitor/` 对应测试（按功能反向验证实现）。

---

## 6. 测试分层与验证建议

当前测试可分为：

- 合约/编译与发布；
- normalize/filter/evaluate/action 链路；
- SQLAlchemy 持久化；
- 单通道 streams/apoc 去重与端到端执行；
- Neo4j 端到端集成（依赖外部环境）。

建议 CI 采用“两层跑法”：

1. 默认层：SQLite + 单元/组件测试（快速、稳定）；
2. 扩展层：MySQL + Neo4j 集成测试（夜间或预发布环境）。

---

## 7. 你最常改的三个位置

1. 新增规则语义：优先改 `compiler/dsl.py` 与 `compiler/service.py`；
2. 新增事件来源：优先改 `runtime/change_pipeline.py` 的 mapper/adapter；
3. 新增持久化字段：同步修改 `persistence/sql_models.py` 与 define/runtime repository 实现，并补回归测试。

---

## 8. 总结

`object_monitor` 当前实现已经具备“可运行链路 + 可替换存储 + 阶段化接入框架”。
对新手来说，抓住两条主线就不容易迷路：

- **控制面**：definition/version 的生命周期管理；
- **数据面**：change event 到 evaluation/action 的流水线。

只要沿着“接口抽象 -> 组件编排 -> 仓储落地 -> 测试验证”这条路径阅读，基本可以快速进入可开发状态。
