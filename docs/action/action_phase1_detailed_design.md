# Action 阶段一详细实现方案（商用部署版，核心能力优先）

> 文档目标：基于 `action_design_general.md` 的“阶段 1：Action 主流程（单服务边界内）”，结合调研与核心设计文档，给出可直接指导落地开发、测试、上线与首批大客户（金融/制造）部署的详细方案。  
> 本阶段聚焦核心主链路与治理闭环，不引入 DFX、跨系统副作用、Saga/Outbox 等阶段二能力。

---

## 1. 设计输入与约束基线

本方案严格继承以下既有结论：

1. **Function 只负责产出编辑意图，不直接写库**；真正提交由 Action Runtime 驱动。
2. **Capture 与 Apply 两阶段必须分离**：函数执行期收集 `TransactionEdit`，提交期统一校验并单事务落图。
3. **阶段一只保证单服务边界内正确性**：Graph 事务原子性强保证；Graph 与 Relational 元数据跨库仅保证“可追踪 + 可恢复”，不追求强一致分布式事务。
4. **可审计与可治理是第一优先级**：每次执行必须可以完整还原“谁在何时、通过哪个版本函数、改了什么、为什么失败”。

---

## 2. 阶段一产品范围（Scope）

## 2.1 In-Scope

- ActionDefinition / FunctionDefinition / ActionExecution / ActionLog 元数据模型。
- Action 提交流程：`定义解析 -> 权限/提交条件 -> 沙箱执行 -> Edit 校验 -> 图事务提交 -> 执行日志`。
- 五类基础 `TransactionEdit`：`addObject / modifyObject / deleteObject / addLink / removeLink`。
- 基于对象版本号（或快照令牌）的乐观冲突检测。
- 执行审计、错误分类、可观测性（日志 + 基础指标）。

## 2.2 Out-of-Scope（明确不做）

- Webhook、通知、外部系统写回（Side Effects）。
- Outbox / Reconciler / Saga / Compensation。
- 多租户复杂计费、审批流、灰度编排引擎。
- DFX、低代码可视化编排、复杂 UI 配置器。

---

## 3. 总体架构与职责拆分

## 3.1 组件视图

- **Ontology Action Service（编排核心）**
  - API 入口、参数校验、权限与 submission criteria 校验。
  - 执行状态流转（`PENDING -> RUNNING -> SUCCEEDED/FAILED`）。
  - 调 Sandbox 执行函数，调 Instance Service 提交编辑。
  - 写入 ActionExecution 与 ActionLog。

- **Sandbox Service（函数执行隔离）**
  - 加载函数版本产物，注入执行上下文。
  - 提供受控 SDK 能力（查询 + 编辑捕获）。
  - 严格资源与网络策略；超时/异常隔离。

- **Ontology SDK（沙箱内库）**
  - 提供对象读取代理、`OntologyEdits` 容器、`TransactionEdit` 归一化输出。
  - 屏蔽底层服务细节，禁止直接写存储。

- **Ontology Search Service（读路径）**
  - 支撑函数执行期对象/关系查询。
  - 默认读取提交前快照，不承诺“读己之写”。

- **Ontology Instance Service（写路径）**
  - 对 `TransactionEdit` 做 schema/权限/约束/冲突校验。
  - 在 Graph DB 单事务 apply，确保全成或全回滚。

- **Graph DB（数据面）**
  - 对象实例、关系实例、版本号、约束索引。

- **Relational DB（控制面）**
  - Action/Function 定义、执行记录、事件日志、失败上下文。

## 3.2 关键边界

- **写边界**：只有 Instance Service 可落图。
- **执行边界**：Sandbox 只返回结构化编辑，不返回直接 SQL/Graph 脚本。
- **审计边界**：Action Service 是唯一执行状态写入者，避免多源状态冲突。

## 3.3 基于当前仓库代码的现状与差距

当前 `ontology` 仓库已经有可运行 Action 主体代码（`api / execution / storage / edits`），但从阶段一目标看存在三类差距：

1. **模块边界混叠**：对象读取与图写入能力目前集中在 `ontology/action/storage/*`，尚未抽离为 `instance`、`search` 两个轻量模块。
2. **阶段混叠**：`ActionService` 中已有 outbox/reconciler/saga/通知等阶段二语义，阶段一应先降维为“核心主链路优先、阶段二能力可关闭”。
3. **API 与版本规范不足**：当前路由不是 `/api/v1/*` 前缀，且动作提交接口风格仍为 `/actions/submit`，与阶段一标准化接口不一致。

## 3.4 代码重构目标结构（阶段一）

建议在 `ontology/` 下新增 `instance/` 与 `search/`，并与 `action/` 一样按典型后端结构组织：

```text
ontology/
  action/
    api/
    execution/
    storage/
  instance/
    api/
    storage/
  search/
    api/
    storage/
```

### 3.4.1 现有代码到目标模块的迁移建议

- `ontology/action/storage/graph_store.py`
  - **迁移到**：`ontology/instance/storage/graph_store.py`
  - **原因**：图实例读写底座属于 Instance Service 数据面能力。
- `ontology/action/storage/apply.py`
  - **迁移到**：`ontology/instance/storage/apply_service.py`
  - **原因**：编辑应用（validate/apply）应归属 Instance Service。
- `ontology/action/api/router.py` 中对象查询接口（`/objects/...`）
  - **迁移到**：`ontology/search/api/router.py`
  - **原因**：对象查询应由 Search Service 统一对外。
- `ontology/action/storage/edits.py`
  - **保留在 action**，但建议拆分为：
    - `ontology/action/contracts/edits.py`（对外契约）
    - `ontology/instance/storage/edit_apply.py`（应用策略）

### 3.4.2 兼容迁移策略（避免一次性大改风险）

1. 首批 PR 只做“新增模块 + 软迁移”：新路径实现并保留旧导入 re-export。
2. 第二批 PR 完成 Action 对新模块依赖切换，旧路径打 `DeprecationWarning`。
3. 第三批 PR 清理旧路径并更新测试、文档与示例。

> 该策略可降低金融/制造客户升级风险，避免一次性重构导致回归面过大。


## 3.5 阶段一暂不启用功能梳理与临时调整方案

结合当前代码，以下能力已存在实现但**不属于阶段一上线必需能力**，建议做“保留代码、默认关闭、可观测可回退”的临时治理：

| 能力 | 当前代码位置 | 阶段属性 | 阶段一处理策略 |
|---|---|---|---|
| Notification 分发 | `ontology/action/execution/notifications.py`、`NotificationEffectHandler` | 阶段二 | 不删除代码；通过 `FEATURE_SIDE_EFFECTS=false` 全局关闭调用入口，仅保留单元测试与接口契约。 |
| Webhook 分发 | `WebhookEffectHandler` | 阶段二 | 与 Notification 同策略，默认不注册 handler。 |
| SideEffect Outbox Worker | `SideEffectWorker`、`claim_pending_outbox` | 阶段二 | worker 进程默认不启动；outbox 表可保留但不写入业务数据。 |
| Reconciler | `ActionReconciler` | 阶段二 | 关闭定时任务，仅保留“控制面 repair job”（阶段一一致性补全）能力。 |
| Saga 编排 | `ActionDefinition.saga_steps`、`SagaStep` | 阶段二 | 暂停执行 saga steps；字段可保留但 API 不暴露。 |
| Compensation / Revert | `compensation_fn`、`revert()`、`action_reverts` | 阶段二 | `revert` 接口不对外发布；补偿逻辑迁入 stage2 命名空间，阶段一仅记录失败与人工处置。 |
| ActionState 持久化 | `ActionStateModel` 与相关仓储方法 | 阶段二 | 可保留表结构，阶段一不作为主状态源；主状态以 `ActionExecution` 为准。 |

### 3.5.1 代码层临时调整原则（建议按 PR 渐进实施）

1. **入口收敛**：`ActionService.execute()` 仅保留阶段一主链路（运行函数、校验、apply、记录日志）；阶段二逻辑放入可选分支。
2. **显式开关**：引入统一配置项：
   - `FEATURE_SIDE_EFFECTS`（默认 `false`）
   - `FEATURE_SAGA`（默认 `false`）
   - `FEATURE_REVERT`（默认 `false`）
3. **默认安全值**：当开关为 `false` 时，相关参数（`side_effects`、`saga_steps`、`compensation_fn`）即使传入也不执行，并打审计告警日志。
4. **代码位置治理**：建议新增 `ontology/action/stage2/` 保存上述暂不启用实现，避免污染阶段一主路径。
5. **测试分层**：
   - `tests/stage1/*`：只测核心主链路；必须通过。
   - `tests/stage2/*`：开关打开后验证；默认不作为阶段一发布门禁。

### 3.5.2 运维与发布策略（避免“代码在但误开启”）

- 生产配置中心将阶段二开关强制写死为 `false`，并加启动时断言。
- 若检测到 `side_effects`/`saga_steps` 非空，返回 warning 日志（不影响主流程结果）。
- 发布清单中新增“阶段二开关核验项”，确保金融/制造首批环境不误用。

---

## 4. 领域模型与数据表设计（阶段一可落库版）

## 4.1 ActionDefinition

建议字段：
- `id` (PK, UUID)
- `name` (全局唯一或按命名空间唯一)
- `status` (`DRAFT|ACTIVE|DEPRECATED`)
- `input_schema` (JSON)
- `output_schema` (JSON, nullable)
- `function_ref` (`function_id + function_version`)
- `submission_criteria` (JSON rules)
- `created_at/updated_at`

约束：
- 仅 `ACTIVE` Action 可执行。
- `function_ref` 固定到函数“已发布具体版本”（`function_id + version`，阶段一不做版本范围解析）。

阶段一补充约束（面向目标类型治理）：
- `target_type`（可选）：`entity | relation`。
- `target_api_name`（可选）：目标类型对应的 API 名称（例如实体 `User`，关系 `MEMBER_OF`）。
- 若配置了 `target_type/target_api_name`，则在输入实例解析后进行强校验，不匹配直接失败（进入 `FAILED@validating`）。

设计意图：
- 保留 Action 在治理面上的“目标范围”语义，避免函数内任意 `search` 导致隐式批量改写。
- 与权限/提交条件配合，保证“谁可对什么类型执行动作”可审计。


版本策略建议：
- `ActionDefinition`：**就地修改（in-place）** 为主，保持 `name` 稳定；阶段一避免复杂多版本并存。
- `FunctionDefinition`：**版本化管理**（不可变发布单元），每次代码变更产生新版本。
- 运行时绑定规则：Action 持有固定 `function_id + function_version`（阶段一不做范围解析），执行时解析到具体函数版本后写入 `ActionExecution.function_version_resolved`。
- 变更约束：Action 就地修改仅允许非破坏性变更（描述、展示元数据、默认参数、criteria）；涉及函数语义变化时必须通过 Function 新版本发布实现。

## 4.2 FunctionDefinition（阶段一精简与实现导向）

结合当前目标（函数核心是 Python implementation 代码），`FunctionDefinition` 建议最小化为：
- `function_id`（业务稳定标识）
- `version`（不可变，语义版本或自增版本）
- `name`（展示名，可变）
- `language`（固定 `python`）
- `runtime`（如 `python3.11`）
- `implementation_code`（TEXT，保存函数实现源码）
- `input_schema` / `output_schema`
- `status` (`ACTIVE|DISABLED`)
- `created_at`

可暂缓字段（避免阶段一过度设计）：
- `artifact_uri`：当前无需引入外部产物仓库时可移除。
- `entrypoint`：阶段一约定统一函数签名（如固定 `def run(context, **kwargs)`），无需单独字段。
- `execution_policy`：阶段一可由平台全局配置统一控制（Sandbox 限额），无需函数级配置。
- `provenance`：可先通过 `ActionLog` 与 Git 提交记录外部追溯，后续再结构化入库。

### 4.2.1 FunctionDefinition 具体存储方案（Python implementation）

建议采用“元数据 + 源码”双层存储：

1. **关系库主表（FunctionDefinition）存元数据与源码**
   - `implementation_code` 使用 `TEXT`（MySQL）/ `TEXT`（SQLite）。
   - 单条代码大小建议上限（例如 256KB），超过则拒绝发布或转阶段二产物模式。
2. **执行时加载流程**
   - Action Runtime 按 `function_id+version` 读取 `implementation_code`。
   - 写入沙箱临时文件（如 `fn_<version>.py`），再按约定入口函数执行。
   - 执行后仅保留 `function_version_resolved` 与摘要日志，不回写源码副本。
3. **发布与校验**
   - 发布前做静态校验：语法检查、入口函数存在、schema 对齐。
   - 发布后版本不可变，若修改逻辑必须新建版本。
4. **为什么阶段一优先源码入库**
   - 实现简单，去掉 artifact 仓库依赖，便于快速商用落地。
   - 与 SQLite/MySQL 兼容性好，迁移成本低。
   - 后续若要升级为 `artifact_uri` 模式，可平滑加字段并做双读迁移。

### 4.2.2 输入协议补充（实体实例 + 关系实例）

阶段一允许两类输入实例：

1) **实体输入**（兼容现有协议）
```json
{
  "loan": {"object_type": "Loan", "primary_key": "loan-1", "version": 1}
}
```

2) **关系输入**（新增）
```json
{
  "membership": {
    "link_type": "MEMBER_OF",
    "from": {"object_type": "User", "primary_key": "u1"},
    "to": {"object_type": "Group", "primary_key": "g1"}
  }
}
```

关系输入在验证期需要满足：
- `link_type`、`from`、`to` 字段完整；
- `from/to` 端点对象存在；
- 若 Action 配置了 `target_type=relation`，则 `link_type` 需匹配 `target_api_name`。

## 4.3 ActionExecution（阶段一最小必要模型）

`ActionExecution` 在阶段一**仍然必要**，原因：
- 它是“动作执行状态”的单一事实源（source of truth），承接 API 查询与运维排障。
- 没有该表就无法稳定实现：幂等去重、执行追踪、失败归因、审计回放。
- `ActionLog` 适合记录事件流，但不适合作为当前状态查询主表。

为聚焦核心能力，建议字段压缩为：
- `id` (PK, UUID)
- `action_id`
- `function_version_resolved`
- `status` (`QUEUED|VALIDATING|EXECUTING|APPLYING|SUCCEEDED|FAILED`)
- `failed_stage`（`validating|executing|applying|unknown`, nullable）
- `idempotency_key`（nullable，建议生产必填）
- `input_payload` (JSON)
- `output_payload` (JSON, nullable)
- `error_code` / `error_message`（`error_details` 可先不落库）
- `submitted_at` / `started_at` / `finished_at`

可以先移除/暂缓字段：
- `request_id`（可先放日志链路，不强制入库）
- `ontology_edit` 全量原文（阶段一仅存摘要，避免大对象膨胀）
- `tenant_id` / `submitter`（当前仓库未实现权限与租户体系，可暂缓）

## 4.4 ActionLog（事件溯源）

建议事件：
- `EXECUTION_CREATED`
- `CRITERIA_VALIDATED`
- `FUNCTION_STARTED`
- `FUNCTION_FINISHED`
- `EDIT_VALIDATED`
- `APPLY_STARTED`
- `APPLY_SUCCEEDED`
- `APPLY_FAILED`
- `EXECUTION_FINISHED`

字段：
- `id`、`action_execution_id`、`event_type`、`payload`、`created_at`

## 4.5 索引与保留策略（阶段一精简版）

- `UNIQUE(action_id, idempotency_key)`（`idempotency_key` 为空时可跳过唯一约束）
- `ActionExecution(status, failed_stage, submitted_at desc)`
- `ActionExecution(action_id, submitted_at desc)`
- `ActionLog(action_execution_id, created_at asc)`
- 审计保留建议：
  - 金融客户：`>= 3650 天`（按合规策略可归档）
  - 制造客户：`>= 1095 天`

---

## 5. TransactionEdit 规范（阶段一冻结契约）

统一采用以下结构（与既有研究对齐）：

- `addObject { object_type, properties }`
- `modifyObject { object_type, primary_key, properties }`
- `deleteObject { object_type, primary_key }`
- `addLink { object_type, primary_key, link_type, linked_object_primary_key }`
- `removeLink { object_type, primary_key, link_type, linked_object_primary_key }`

关键规则：

1. `modifyObject` 仅允许更新白名单属性，主键不可改。
2. 数组/结构属性按“整体回写”语义，不支持原地局部 patch。
3. 单次执行内，`create -> delete` 可抵消；同对象多次 modify 合并为最后值。
4. edit 列表顺序可用于冲突解读，但 apply 时必须经规范化。

---

## 6. 核心执行流程设计（阶段一）

## 6.1 提交接口

`POST /api/v1/actions/{action_id}/apply`

请求体：
- `input`：动作参数
- `targets`：可选目标对象集合
- `client_request_id`：幂等键（建议必填；重复提交返回已有 execution，不重复执行）

返回：
- `execution_id`
- `status`
- `submitted_at`

## 6.2 编排时序（同步版）

1. Action Service 读取 ActionDefinition + FunctionDefinition。
2. 校验 Action 是否 ACTIVE、函数是否可执行。
3. 执行 submission criteria（参数、对象状态、租户策略）。
4. 执行基础请求校验（身份上下文存在性、action 状态、输入 schema）。
5. 写 `ActionExecution(QUEUED->VALIDATING->EXECUTING)` 状态流转。
6. 调 Sandbox 执行函数，传入 context（用户、租户、request id、限制策略）。
7. Sandbox 返回 `list[TransactionEdit]` 或错误。
8. Action Service 将状态置为 `APPLYING`，并调 Instance Service 执行 `validate+apply`。
9. Instance Service Graph 事务提交或回滚。
10. Action Service 更新 ActionExecution 终态并追加 ActionLog。
11. 返回执行结果。

## 6.3 Validate 与 Apply 分层

- **预校验（Action Service）**
  - schema、criteria、基础身份/上下文校验。
- **强校验（Instance Service）**
  - 对象存在性、属性类型、链接合法性、版本冲突。
- **提交（Instance Service）**
  - begin tx -> apply edits -> commit / rollback。

这样可以保证：无论函数如何生成编辑，最终写入总会经过统一强校验。

---

## 7. 失败模型与错误码体系（商用可运维）

## 7.1 错误分类

- `E_ACTION_NOT_ACTIVE`
- `E_FUNCTION_DISABLED`
- `E_CRITERIA_FAILED`
- `E_PERMISSION_NOT_IMPLEMENTED`（阶段一固定返回未启用或跳过）
- `E_SANDBOX_TIMEOUT`
- `E_SANDBOX_RUNTIME`
- `E_EDIT_SCHEMA_INVALID`
- `E_EDIT_CONFLICT`
- `E_APPLY_CONSTRAINT_VIOLATION`
- `E_APPLY_INTERNAL`

## 7.2 可观测错误上下文

每次失败必须记录：
- `execution_id`
- `action/function version`
- `failed_stage`（criteria/function/validate/apply）
- `error_code`
- `retryable`（bool）
- `redacted_context`（脱敏输入与 edit 摘要）

## 7.3 返回语义

- 对用户：稳定错误码 + 可读消息。
- 对运维：完整事件链与堆栈（仅内部可见）。

---

## 8. 并发控制与一致性策略

## 8.1 冲突策略

阶段一统一采用 **乐观并发控制（OCC）**：
- 每个对象维护 `version`。
- `modify/delete/link` 必须基于读取时版本（或快照 token）。
- 版本不一致即 `E_EDIT_CONFLICT`。

## 8.2 决策理由

- 金融/制造场景更关注“正确优先于吞吐”；冲突直接失败比隐式覆盖更安全。
- 为阶段二重试与对账保留清晰语义，不引入早期 LWW 复杂度。

## 8.3 跨库一致性（阶段一处理）

- 允许出现 `Graph 成功但 Relational 更新失败` 的极端窗口。
- 通过以下机制收敛：
  1. ActionLog 先写“APPLY_STARTED”。
  2. 应用成功后若元数据更新失败，落本地补偿队列（轻量表）。
  3. 后台 repair job 根据 `execution_id` 补写终态。

> 注：该 repair 仅用于控制面补全，不属于阶段二 SideEffect Outbox。

---

## 9. 安全与合规设计（首批商用最小闭环）

## 9.1 Sandbox 安全基线

- 只读根文件系统 + 临时工作目录。
- 默认禁网，按 allowlist 开启 Search/Metadata 内网访问。
- 限制 CPU/内存/FD/执行时长，超限强制 kill。
- 禁止加载未签名函数产物。

## 9.2 权限能力处理（阶段一暂缓实现）

考虑当前本体系统尚未形成完整权限机制，阶段一建议：
- **不实现**细粒度权限引擎（`action/object/property/link`）。
- 在接口层仅保留基础身份字段透传与审计记录能力（谁触发、何时触发）。
- 将权限校验点作为扩展钩子预留到阶段二/后续版本，避免当前过度设计阻塞主链路落地。

## 9.3 审计合规

必须落审计字段：
- 执行人、租户、客户端来源、请求时间、函数版本、对象主键列表、变更字段摘要。
- PII/敏感字段按字段级脱敏策略入日志（如卡号仅后四位）。

---

## 10. 性能与容量规划（阶段一目标）

## 10.1 SLO 建议（可作为商用承诺初版）

- 单次 Action（<=50 edits）P95 `< 1.5s`。
- Sandbox 启动 + 执行 P95 `< 800ms`（不含重型查询）。
- 可用性目标：`99.9%`（月度）。

## 10.2 容量参数（初始）

- 单租户并发执行上限：`20`（可配置）。
- 单执行最大 edit 数：`500`。
- 单次请求 payload 上限：`1MB`。

## 10.3 背压策略

- Action Service 本地队列 + 令牌桶限流。
- 超载返回 `429 E_SYSTEM_THROTTLED`。

---

## 11. API 设计（阶段一最小集合）

统一前缀：`/api/v1`

1. `POST /api/v1/actions/{action_id}/apply`：提交并执行。
2. `POST /api/v1/actions/{action_id}/validate`：仅校验（不落图）。
3. `GET /api/v1/actions/executions/{execution_id}`：查询状态与结果。
4. `GET /api/v1/actions/executions/{execution_id}/logs`：查询执行事件。
5. `GET /api/v1/objects/{object_type}/{primary_key}`：对象详情查询（Search 模块）。
6. `GET /api/v1/objects/{object_type}`：对象列表查询（Search 模块）。

响应要求：
- 所有接口返回统一 `request_id`。
- `apply` 接口支持 `Idempotency-Key` header 或 `client_request_id`（二选一）。
- 错误统一 `{ code, message, details }`。

### 11.1 当前代码的 API 调整清单

- 当前 `POST /actions/submit` -> 迁移为 `POST /api/v1/actions/{action_id}/apply`。
- 当前 `GET /actions/{execution_id}` -> 迁移为 `GET /api/v1/actions/executions/{execution_id}`。
- 在 `ontology/main.py` 中 `include_router(..., prefix="/api/v1")` 统一挂载。

### 11.2 `apply` 幂等设计（`Idempotency-Key` / `client_request_id`）

> 目标：把“同一业务请求的重试”变为“同一执行结果的复用”，避免网络抖动、用户重复点击、网关重试导致重复执行。

#### 11.2.1 设计原则

1. **同键同语义**：同一个幂等键必须绑定同一个请求语义（`action_id + version + submitter + input_payload + input_instances`）。
2. **先登记后执行**：在真正执行函数前先占位幂等记录，防止并发双写。
3. **状态可观测**：调用方能区分“首次执行 / 命中历史结果 / 正在执行中”。
4. **失败可重试**：对明确可重试失败可允许重新执行；对已成功执行必须严格复用结果。

#### 11.2.2 适用入口与键来源

- 仅对 `POST /api/v1/actions/{action_id}/apply` 生效。
- 客户端可二选一提供键：
  - `Idempotency-Key`（HTTP Header，优先级更高）；
  - `client_request_id`（请求体字段）。
- 两者都提供时：以 `Idempotency-Key` 为准，并在日志中记录冲突告警字段。

#### 11.2.3 控制面数据模型（建议）

新增表：`action_idempotency_records`

- `idempotency_key`（字符串，业务可读键）
- `action_name`
- `submitter`
- `request_hash`（规范化请求体哈希）
- `execution_id`（关联 `action_executions.id`）
- `status`（`in_progress | succeeded | failed_retryable | failed_non_retryable`）
- `response_payload`（可选，缓存响应）
- `created_at / updated_at / expires_at`

索引与约束：

- 唯一键：`UNIQUE(action_name, submitter, idempotency_key)`
- 查询索引：`(status, updated_at)` 便于清理与巡检

#### 11.2.4 `apply` 时序（伪流程）

1. 解析并校验幂等键（长度、字符集、TTL）。
2. 计算 `request_hash`（请求规范化后哈希）。
3. `INSERT ... ON CONFLICT` 抢占幂等记录：
   - 插入成功：说明首个请求，状态置 `in_progress`，继续执行。
   - 冲突命中：读取已有记录并执行分支：
     - `succeeded`：直接返回历史执行结果（HTTP 200，`idempotency_hit=true`）。
     - `in_progress`：返回“处理中”（建议 HTTP 409/425 + 可轮询 execution_id）。
     - `failed_retryable`：允许重试抢占（CAS 更新后重跑）。
     - `failed_non_retryable`：直接返回历史失败。
4. 对命中记录校验 `request_hash`：
   - 不一致则返回 `409 E_IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_PAYLOAD`。
5. 执行当前主流程（submit -> execute -> apply）。
6. 按执行终态回写幂等记录：
   - 成功：`succeeded`
   - 可重试失败：`failed_retryable`
   - 不可重试失败：`failed_non_retryable`

#### 11.2.5 请求哈希规范（避免“同键异义”）

`request_hash` 必须基于规范化 JSON：

- 字段排序稳定；
- 忽略非语义字段（如 trace 字段）；
- 保留 `action_id/version/submitter/input_payload/input_instances`；
- 建议算法：`SHA-256(canonical_json)`。

#### 11.2.6 失败语义与错误码

新增错误码：

- `E_IDEMPOTENCY_KEY_REQUIRED`：该 Action 要求幂等但未提供键。
- `E_IDEMPOTENCY_KEY_INVALID`：键格式非法。
- `E_IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_PAYLOAD`：同键不同请求体。
- `E_IDEMPOTENCY_IN_PROGRESS`：已有同键请求正在执行。

与既有失败码并存，最终统一进入 ActionLog 的 `error_code` 维度。

#### 11.2.7 与阶段一边界的关系

- 幂等是**阶段一主链路稳定性能力**，不依赖 Outbox/Saga；
- 可在不启用阶段二能力的前提下独立上线；
- 与修复任务（repair job）兼容：repair 仅修复执行状态，不覆盖成功幂等记录。

#### 11.2.8 最小实现范围（建议按 PR 拆分）

- **PR-1（最小可用）**：
  - Header/body 取键；
  - `UNIQUE(action_name, submitter, idempotency_key)`；
  - 命中成功直接返回历史 execution；
  - 同键异义 409 拒绝。
- **PR-2（并发完善）**：
  - `in_progress` 状态与超时恢复；
  - retryable/non-retryable 分流。
- **PR-3（运维完善）**：
  - TTL 清理任务；
  - 命中率、冲突率、重复提交率指标。

---

## 12. 测试与验收方案（阶段一 Gate）

## 12.1 功能验收

- 提交成功路径：执行状态完整流转，图数据正确更新。
- 五类 edit 覆盖：create/modify/delete/addLink/removeLink。
- validate-only：通过时不写图，失败返回具体字段错误。

## 12.2 失败验收

- criteria 失败、权限失败、函数异常、超时、冲突失败、约束失败。
- 验证失败分类与 error_code 一致。

## 12.3 一致性验收

- 故障注入：Graph 成功后模拟 Relational 写失败。
- 验证 repair job 能补全 ActionExecution 终态。

## 12.4 性能验收

- 以 100 并发、30 分钟压测，观察 P95/P99、错误率、冲突率。

---

## 13. 面向金融/制造部署的落地建议（阶段一可执行）

## 13.1 金融客户优先项

- 强制开启字段级审计与长周期留存。
- 高风险 Action 配置“二次确认 + validate-only 预演”。
- 函数版本默认冻结，变更需审批。

## 13.2 制造客户优先项

- 加强批量对象冲突可视化（哪些设备/工单冲突）。
- 提升离峰批处理配额，避免影响生产时段。
- 对现场网络波动场景优化重试与超时阈值。

## 13.3 共性上线清单

- 上线前逐 Action 做“输入样本回放 + 冲突演练”。
- 生产开启分租户限流与熔断。
- 审计日志接入企业 SIEM。

---

## 14. 分阶段实施计划（8 周建议）

- **W1-W2**：
  - 新增 `ontology/instance`、`ontology/search` 目录与基础 `api/storage` 结构。
  - API 统一切换 `/api/v1/*`，并保留旧路由兼容层（可配置关闭）。
  - 数据模型与错误码骨架。
  - 完成“阶段二能力清单”盘点并设置默认关闭开关。
- **W3-W4**：
  - Sandbox + SDK（Capture）+ `TransactionEdit` 规范化。
  - 从现有 `action/storage` 向 `instance/search` 做软迁移（re-export）。
- **W5-W6**：
  - Instance Service 强校验 + Graph 事务 apply + OCC。
  - 将 ActionService 中阶段二逻辑（outbox/reconciler/saga）通过 feature flag 默认关闭。
- **W7**：审计日志、可观测性、repair job。
- **W8**：压测、故障演练、首批客户上线 checklist。

---

## 15. 关系型数据库实现策略（MySQL/SQLite）

阶段一建议统一通过 SQLAlchemy 屏蔽数据库差异：

1. **默认连接策略**
   - 优先读取 `DATABASE_URL`。
   - 未配置时默认回落 `sqlite:///./ontology.db`（便于本地与 PoC）。
2. **生产部署建议**
   - 金融/制造生产默认 MySQL 8.x（高可用、备份、审计生态成熟）。
   - SQLite 仅用于单机开发/CI 冒烟，不用于多副本生产。
3. **方言差异处理**
   - 使用 SQLAlchemy ORM + Alembic 迁移。
   - JSON 字段采用统一抽象（MySQL JSON / SQLite TEXT+序列化）。
   - 时间字段统一 UTC，避免方言默认时区差异。

建议配置示例：

```env
# 生产
DATABASE_URL=mysql+pymysql://user:pwd@host:3306/ontology

# 开发/CI 兜底
DATABASE_URL=sqlite:///./ontology.db
```

---

## 16. 阶段一完成定义（Definition of Done）

满足以下条件方可宣告阶段一完成：

1. E2E 主链路在预发稳定运行 2 周，无 P1 数据一致性事故。
2. 五类 `TransactionEdit` 全部支持，且具备冲突检测。
3. 所有失败路径具备可归因错误码与执行日志。
4. 审计轨迹可在 5 分钟内定位到任一执行的“输入-函数版本-编辑-结果”。
5. 基础 SLO 达标并通过一次 30 分钟稳态压测。

---

## 17. 与阶段二接口预留（不提前实现）

为避免后续重构，阶段一需预留：

- `ActionExecution` 的 `state_detail` 扩展字段（用于后续 side effect 状态）。
- `ActionLog` 事件类型扩展命名空间。
- `execution_id` 作为未来外部幂等键种子。

以上预留不引入阶段二运行逻辑，仅保证后续平滑升级。
