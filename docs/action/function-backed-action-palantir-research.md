# Palantir Ontology 中 Function-backed Action 调研（含可落地实现建议）

## 1) 调研范围与结论速览

本次重点围绕以下主题做了系统梳理：

- Ontology 的核心抽象（对象、属性、链接、Action Type）。
- Action Type 的执行模型（权限、提交条件、监控、回滚、日志）。
- Function-backed Action 的设计目标、创建流程、版本治理与批处理执行。
- Ontology Edit Function 的编程模型（TS v1 / TS v2 / Python）、编辑语义与 caveats。
- 社区实践中的常见坑（部署后调试、入口定位、inline edit 结合 function-backed action）。

**核心结论（给你系统设计时最关键的三点）**：

1. **Function-backed Action 本质是“受控写事务入口”**：函数只是生成/组织 edits，真正写入必须通过 Action 路由执行，便于权限、审计、监控统一治理。
2. **Action 与 Function 要解耦版本治理**：Action 绑定函数版本（或版本范围）是稳定性的关键，避免函数升级导致生产动作行为漂移。
3. **批处理与冲突控制是规模化门槛**：同样的 Action 在 inline edit / automate 场景下吞吐与冲突模型不同，必须从一开始设计 batch contract 与幂等键。

---

## 2) Palantir 官方语义模型（你可以直接借鉴的抽象）

### 2.1 Ontology 与 Action 的关系

从官方 Ontology core concepts + action types 文档可抽象为：

- Ontology 是业务语义层；
- Action 是对对象/属性/链接进行一次“原子变更事务”；
- Action Type 是这类事务的“模板定义”（参数、规则、权限、校验、UI 行为等）。

这意味着你自己的系统里，**Action Type 应当是一等元数据对象**，而不是“函数 + 某个按钮”的临时组合。

### 2.2 为什么会出现 Function-backed Action

官方说明里明确：rule-based action 适合简单编辑；当出现跨对象复杂逻辑、条件分支、复杂链接更新时，需要函数承载逻辑。这正是 function-backed action 的定位。

可借鉴设计：

- 规则引擎可覆盖 80% 简单场景；
- 函数模式覆盖复杂场景，并且仍通过同一 action 治理面（权限/审计/监控）。

---

## 3) Function-backed Action 的标准执行链路（建议你在系统中一一对应）

推荐你在系统中实现如下 8 步流水线：

1. **Resolve Action Type**：确定 action schema、参数定义、目标对象范围。
2. **Authorization**：校验“可执行动作权限 + 目标对象编辑权限 + side effects 权限”。
3. **Submission Criteria**：在执行前进行参数/对象状态条件校验（失败给用户可读消息）。
4. **Invoke Function**：将 action 参数、当前用户上下文、目标对象上下文注入函数。
5. **Collect Edits**：函数返回 edit batch（create/update/delete/link/unlink）。
6. **Validate Edits**：类型校验、约束校验、冲突检测、幂等校验。
7. **Atomic Commit**：统一提交为单事务（或批次内原子单元）。
8. **Observability**：记录 action log、指标、告警、失败上下文。

Palantir 文档里有关 permission / submission criteria / monitoring / action log / metrics 的分层，基本就是围绕这个流水线组织。

---

## 4) Ontology Edit Function 编程模型：可迁移到你的平台的关键能力

### 4.1 语言与声明方式

官方当前支持 TS v1 / TS v2 / Python 的编辑函数路线（TS v1 用装饰器语义，TS v2/Python 提供更现代接口）。

你的系统可采用：

- `@actionFunction`（声明函数元信息）；
- `EditBatch`（显式收集 edits）；
- `return EditBatch`（禁止函数里直接写库，统一由 action runtime 提交）。

### 4.2 Edits 的原语集合

官方文档中 edits 的核心原语可归纳为：

- 更新属性（对象属性、接口属性、结构化字段）；
- 更新链接（新增/删除关系）；
- 创建对象；
- 删除对象。

你的系统最小可用集也建议按这四类建模，避免过早引入过度复杂的“领域特化写 API”。

### 4.3 重要语义 caveats（非常值得照搬）

官方 edits-overview 中提到一些容易踩坑的语义，建议你实现时默认支持：

- **Edits 何时生效**：函数执行阶段是“收集编辑”，提交阶段才真正写入。
- **搜索可见性时序**：同一次函数中的读取操作未必能看到尚未提交 edits。
- **可选数组/结构属性处理**：函数输入输出的可空与数组语义要严格定义。

---

## 5) 批处理（Batched execution）设计建议

官方专门强调 batched execution 在 inline edits / automate 中的重要性。结合实践建议你实现两种模式：

- **模式 A：逐请求函数调用，事务末尾统一提交**（简单、隔离好、吞吐一般）。
- **模式 B：batch 输入一次调用**（高吞吐，适合批量改写，需更严格冲突策略）。

你可以在 Action Type 上提供 `executionMode = SEQUENTIAL | BATCHED`，并配套：

- 最大批量大小；
- 冲突重试策略（指数退避 + 去重键）；
- 幂等键（例如 `actionInvocationId + targetObjectRid`）。

---

## 6) 版本治理与发布策略（Function 与 Action 解耦）

官方 getting-started 文档里强调 action 与函数版本变更关系（自动升级、安全性、breaking changes、provenance）。

在你的系统中建议强制：

- Action 绑定函数 `semantic version range`（例如 `^2.3.0`）；
- 提供“冻结版本”与“自动升级”两种策略；
- 函数升级前做 contract check（参数、返回 edit schema、权限声明）；
- Action 执行日志中记录 `functionVersionResolved`，便于追溯。

---

## 7) 权限、安全、审计（实现 Function-backed Action 必须具备）

参考官方 action permissions / submission criteria / monitoring，建议你的最小治理面包含：

- **Apply 权限**：谁能执行此 action。
- **Object-level 编辑权限**：谁能改哪些对象或字段。
- **Side-effect 权限**：调用外部系统（webhook/通知）单独授权。
- **Submission Criteria**：执行前状态机条件检查。
- **审计链路**：谁在何时以什么参数触发、命中了哪些对象、落了哪些 edits。
- **监控告警**：失败率、延迟、冲突率、回滚率、重试次数。

---

## 8) 你可采用的参考架构（实现蓝图）

### 8.1 领域模型

- `ActionTypeDefinition`
  - 参数 schema
  - 目标对象 scope resolver
  - 绑定函数 ref（repo/tag/version-range）
  - permission policy
  - submission criteria
  - execution mode（single/batch）
- `FunctionArtifact`
  - 语言 runtime（ts/python）
  - contract（input schema / edit capability）
  - provenance（发布来源、commit、tag）
- `EditBatch`
  - operations[]（create/update/delete/link）
  - metadata（invocationId、idempotencyKey）

### 8.2 Runtime 组件

- Action Gateway
- Permission Engine
- Function Sandbox Runner
- Edit Validator
- Transaction Coordinator
- Audit & Metrics Pipeline

### 8.3 API 形态（建议）

- `POST /action-types/{id}/apply`
- `POST /action-types/{id}/apply-batch`
- `GET /action-invocations/{invocationId}`（状态 + edits + 版本 + 审计）
- `POST /action-types/{id}/validate`（仅校验不提交）

---

## 9) 社区侧实践洞察（非官方产品文档，但很有实现价值）

从 Palantir Developer Community 可观察到几个“真实落地”问题：

1. **Marketplace 部署后函数调试可见性弱**：社区提到部署时通常只带产物（如 transpiled JS），不是完整仓库；这提示你在系统设计中要保留“发布产物可回看能力”。
2. **文档与界面入口映射问题**：用户经常找不到 “Rules section”；说明 Action 配置 UX 需要“引导式向导 + 文档深链”。
3. **Inline edit 可走 function-backed action**：说明函数动作应是“交互组件可复用后端能力”，而不是某单一入口专属能力。

---

## 10) 你项目的落地路线图（建议 3 个迭代）

### 迭代 1（MVP）

- 支持单对象 action + function 返回 edits + 原子提交。
- 支持最小权限（apply + object edit）。
- 提供 action log。

### 迭代 2（生产可用）

- 引入 submission criteria。
- 引入函数版本范围与冻结策略。
- 提供 batched execution 与冲突重试。
- 增加 metrics / alert。

### 迭代 3（平台化）

- 支持 side effects（webhook/notification）与独立权限。
- 提供 dry-run / validate-only。
- 提供可视化 provenance（action->function->artifact->commit）。

---

## 11) 逐链接深度整理（官方文档）

> 说明：以下为“按链接逐条提炼”的结构化摘要，重点抽取可用于系统设计的机制、约束与实现细节；避免全文翻译复制。

### 11.1 Ontology core concepts  
链接：https://palantir.com/docs/foundry/ontology/core-concepts/

**核心内容提炼**
- 该文档把 Ontology 明确为业务语义层（digital twin），并强调对象类型、属性、链接类型、动作类型是并列一等概念。
- Action type 被定义为业务用户“可执行变更”的封装，而不是底层字段直接写入，这为“治理先于写入”提供了产品语义基础。
- Functions 在 Ontology 语境下不是单纯计算函数，而是“可与对象和链接交互”的操作能力单元。
- Interfaces / Object Views 的存在说明：同一底层对象可以以不同业务视角暴露；这对 action 参数设计（按接口暴露 vs 按对象暴露）很关键。

**对你系统的直接启发**
- Action、Function、Object、Link 应全部建成可治理元模型，不建议将函数能力“外挂”到对象模型外。
- 后续做多应用复用时，建议加“视图层（view/interface）”避免 action 与单一 UI 耦合。

### 11.2 Action types overview  
链接：https://palantir.com/docs/foundry/action-types/overview/

**核心内容提炼**
- Action 是一次事务性修改（可涉及多个对象），Action type 是该修改的模板定义。
- Action type 除了“要改什么”，还包括参数、可见性、校验、权限、后续 side effects 等执行元数据。
- Action 不是仅用于表单提交；它是跨产品（Workshop、Automate 等）通用的可执行操作层。

**对你系统的直接启发**
- 应把 Action type 当作“可编排写接口”而不是“UI 按钮配置”。
- 你的 API 层可以以 action invocation 作为标准写入口，避免应用各自绕过治理直接写库。

### 11.3 Function-backed actions overview  
链接：https://palantir.com/docs/foundry/action-types/function-actions-overview/

**核心内容提炼**
- 文档直接给出 function-backed action 的适用边界：当规则式编辑无法描述复杂业务逻辑时（跨对象、多分支、多步联动），由函数生成 edits。
- 函数的职责是表达复杂变更逻辑；action 的职责是承接治理（权限、日志、观测、回滚面）。
- 该文档强调 function-backed action 并非“另一套 action 体系”，而是 action 的一种规则实现方式（Function 规则）。

**对你系统的直接启发**
- 推荐保留统一 Action 运行时，只在“规则解释器”中引入 FunctionRule 分支。
- 这样能保持普通 action 与 function-backed action 在治理面和观测面一致。

### 11.4 Function-backed actions getting started  
链接：https://palantir.com/docs/foundry/action-types/function-actions-getting-started/

**核心内容提炼**
- 标准流程是：先写 Ontology Edit Function，再在 Ontology Manager 的 Action Type 中创建 Function 规则并绑定。
- 文档对“Changing function version”写得很细，覆盖自动升级、安全性、breaking changes、provenance。
- 这说明在官方产品语义中，“函数版本解析”是 action 执行前置步骤，而不是部署时一次性决议。

**对你系统的直接启发**
- Action 绑定函数建议支持版本范围 + 冻结版本两模式。
- 必须记录每次执行最终解析到的函数版本（provenance/audit）。
- 需要提供“变更影响预警”：函数版本升级可能改变 action 行为。

### 11.5 Function-backed actions batched execution  
链接：https://palantir.com/docs/foundry/action-types/function-actions-batched-execution/

**核心内容提炼**
- 文档指出批触发场景（如 inline edits、automate）下，默认可能是逐请求顺序调用；同时提供整批输入调用来提升性能并减少冲突。
- “何时整批、何时逐条”是性能与一致性的权衡，不是纯技术细节，而是 action 配置语义的一部分。

**对你系统的直接启发**
- 在 Action type 显式暴露 `SEQUENTIAL` 与 `BATCHED` 执行模式。
- 结合对象级冲突率与吞吐目标设默认策略，并支持按 action 覆盖。
- 增加批处理幂等键与冲突重试策略，否则在高并发下难稳定。

### 11.6 Functions overview  
链接：https://palantir.com/docs/foundry/functions/overview/

**核心内容提炼**
- Functions 的定位是“在操作型场景快速执行的服务端逻辑”，并强调隔离环境执行。
- 文档突出函数与 Ontology 的一等集成：读取对象属性、遍历链接、执行编辑。
- 这意味着函数既可做 query/计算，也可做 edits，但 edits 要配合 action 才能进入受控落库流程。

**对你系统的直接启发**
- 函数运行时要与“事务提交运行时”解耦：函数可以无状态执行，提交由 action runtime 负责。
- 函数平台应支持“读函数”和“编辑函数”两类契约。

### 11.7 Ontology edits overview  
链接：https://palantir.com/docs/foundry/functions/edits-overview/

**核心内容提炼**
- 明确 Ontology edit 的定义：创建/修改/删除对象与关系。
- 强调“编辑函数返回 edits，真正应用由 action 执行时触发”。
- 文档专门列出 caveats：编辑生效时机、与对象搜索可见性的关系、可选数组在 function-backed action 中的语义。

**对你系统的直接启发**
- 必须定义“收集 edits”和“提交 edits”两个阶段，并保证用户可观察（日志可区分）。
- 对“函数内读到的状态”与“提交后状态”要在文档和 API 中清晰声明，避免开发者误判。

### 11.8 Ontology edit APIs（函数编辑 API）  
链接：https://palantir.com/docs/foundry/functions/api-ontology-edits/

**核心内容提炼**
- 提供了 edit function 的核心原语：更新属性、更新链接、创建对象、删除对象。
- 解释了 edits 捕获机制、如何回读编辑后的值，以及 `@Edits` 装饰器语义（TS v1）。
- 文档再次强调：要在操作场景落地，编辑函数必须配置为 Action。

**对你系统的直接启发**
- 编辑 API 应保持“少而稳”的原语集合，不要把业务流程细节掺进底层编辑语义。
- 在 SDK 中提供“edits 追踪对象”，便于调试和审计。

### 11.9 TypeScript v2 Ontology edits  
链接：https://palantir.com/docs/foundry/functions/typescript-v2-ontology-edits/

**核心内容提炼**
- TSv2 语义强调“构建 edits batch 再返回”，与现代 TS/JS 生态（OSDK）更一致。
- 文档覆盖对象属性、接口属性、链接、对象/接口创建删除、struct 属性编辑等细粒度能力。
- 对复杂结构属性（如 struct）给出专门章节，说明真实业务经常涉及嵌套结构编辑。

**对你系统的直接启发**
- 你的下一代 SDK 可优先按 TSv2 风格设计（显式 batch builder + 强类型 API）。
- 结构化属性编辑需有稳定 patch 语义（整替换/局部更新），并在 action 契约中声明。

### 11.10 Action permissions  
链接：https://palantir.com/docs/foundry/action-types/permissions/

**核心内容提炼**
- 权限不是单层“能否执行 action”，而是至少包含 apply action、对象编辑权限、side effect 权限。
- Submission criteria 与权限共同构成执行前门禁：前者偏业务条件，后者偏安全授权。

**对你系统的直接启发**
- 授权模型建议拆为：`invoke permission`、`data mutation permission`、`external effect permission`。
- 审计日志需记录“哪一层权限拒绝了执行”。

### 11.11 Submission criteria  
链接：https://palantir.com/docs/foundry/action-types/submission-criteria/

**核心内容提炼**
- 文档给出条件构建维度：当前用户、参数、对象字段、操作符、逻辑组合，以及失败提示信息。
- 这本质上是执行前策略引擎，避免把所有业务校验都塞进函数内部。

**对你系统的直接启发**
- 推荐把 submission criteria 做成可组合表达式 DSL（AND/OR、比较、集合运算）。
- 将“失败消息”纳入配置，减少前端各自重复实现错误文案。

### 11.12 Action monitoring  
链接：https://palantir.com/docs/foundry/action-types/monitoring/

**核心内容提炼**
- 文档重点是“可配置监控规则 + 告警触发”，帮助持续观察 action 运行健康度。
- 监控对象不只成功率，也包括失败类别和运行异常趋势。

**对你系统的直接启发**
- 至少提供：失败率阈值、延迟阈值、连续失败次数等基础告警规则。
- 监控规则建议归属 Action type 而非应用页面，保证跨入口一致。

### 11.13 Action log  
链接：https://palantir.com/docs/foundry/action-types/action-log/

**核心内容提炼**
- Action log 文档显示官方将动作执行日志“对象化”到独立日志模型中（含 schema 与 timeline 视图）。
- 对 function-backed action 也有专门日志关注点，说明函数动作的可追溯性是重点建设方向。

**对你系统的直接启发**
- 采用统一 `action_invocation` 事件模型，至少记录：触发者、参数摘要、命中对象、edits 摘要、函数版本、耗时、结果。
- 增加 timeline 视图（触发→校验→函数→提交→side effects）会显著提升可运维性。

### 11.14 Action metrics  
链接：https://palantir.com/docs/foundry/action-types/action-metrics/

**核心内容提炼**
- 文档定义 action failure types，并对 metrics 访问权限作了说明。
- 说明官方把“失败分类”作为排障与治理核心维度，而非单纯成功/失败二值指标。

**对你系统的直接启发**
- 建议在指标体系内强制失败分类（权限拒绝、校验失败、函数异常、提交冲突、外部副作用失败等）。
- 让指标看板与 action log 可互跳转，形成“发现问题→定位执行记录”的闭环。

---

## 12) 社区/业界实践链接深度整理

### 12.1 Viewing/debugging deployed function definition for a function-backed action  
链接：https://community.palantir.com/t/viewing-debugging-deployed-function-definition-for-a-function-backed-action/415

**帖内关键信息**
- 社区回复指出：Marketplace 部署后通常不可直接查看“原始仓库代码定义”，运行侧依赖发布时生成的可执行产物（如 transpiled JS）。

**落地启发**
- 你的平台应在发布时保存：源 commit、构建产物 hash、符号映射（source map）与版本清单。
- 调试面板应支持“按 invocation 回看对应产物版本”，避免线上不可追。

### 12.2 Where is the Rules section referenced in the docs  
链接：https://community.palantir.com/t/where-is-the-rules-section-referenced-in-the-creating-a-function-backed-action-section-of-the-documentation/4614

**帖内关键信息**
- 用户困惑“Rules section 在哪”，回复明确入口位于 Ontology Manager 的 Action Type 配置流程。
- 说明文档术语与 UI 入口之间存在认知断层。

**落地启发**
- 你的产品应把“配置动作”的入口统一为向导：选择 Action Type → 添加规则/函数 → 配置权限/校验 → 发布。
- 文档中所有关键术语（Rules、Submission Criteria、Function Version）建议配 UI 截图或深链。

### 12.3 Edit inline object properties with action + TypeScript  
链接：https://community.palantir.com/t/edit-inline-object-properties-ontology-with-action-typescript/6111

**帖内关键信息**
- 官方社区回答确认 inline edit 支持 function-backed action；且提到 TSv1/TSv2/Python 都可作为后端逻辑。
- 帖中也反映 TSv1 与 TSv2 语法范式差异，开发者容易混用。

**落地启发**
- 你的系统应确保“同一个 action”可复用于表单、表格 inline edit、自动化任务等多入口。
- 在 SDK 文档中明确标注版本范式差异，并提供迁移示例（v1 → v2）。

---

## 13) 参考资料链接（汇总清单）

### A. Palantir 官方文档

1. https://palantir.com/docs/foundry/ontology/core-concepts/
2. https://palantir.com/docs/foundry/action-types/overview/
3. https://palantir.com/docs/foundry/action-types/function-actions-overview/
4. https://palantir.com/docs/foundry/action-types/function-actions-getting-started/
5. https://palantir.com/docs/foundry/action-types/function-actions-batched-execution/
6. https://palantir.com/docs/foundry/functions/overview/
7. https://palantir.com/docs/foundry/functions/edits-overview/
8. https://palantir.com/docs/foundry/functions/api-ontology-edits/
9. https://palantir.com/docs/foundry/functions/typescript-v2-ontology-edits/
10. https://palantir.com/docs/foundry/action-types/permissions/
11. https://palantir.com/docs/foundry/action-types/submission-criteria/
12. https://palantir.com/docs/foundry/action-types/monitoring/
13. https://palantir.com/docs/foundry/action-types/action-log/
14. https://palantir.com/docs/foundry/action-types/action-metrics/

### B. 社区/业界实践资料

1. https://community.palantir.com/t/viewing-debugging-deployed-function-definition-for-a-function-backed-action/415
2. https://community.palantir.com/t/where-is-the-rules-section-referenced-in-the-creating-a-function-backed-action-section-of-the-documentation/4614
3. https://community.palantir.com/t/edit-inline-object-properties-ontology-with-action-typescript/6111

> 注：社区帖子属于实践经验来源，不等同于官方稳定契约；落地时请以官方文档与你自身系统的合规要求为准。

---

## 14) `foundry-platform-python` 仓库深度调研：Action / Function / Ontology Edit 接口与实现推导

> 调研对象：`https://github.com/palantir/foundry-platform-python`（该仓库是 Foundry Platform SDK，不是 Developer Console 生成的 OSDK）。

### 14.1 先澄清：这是 Platform SDK，不是“业务本体 OSDK”

从仓库 README 可确认：
- 该 SDK由 Foundry API 规范自动生成；
- 官方建议“凡是深度使用 Ontology 业务对象的应用，优先使用 Ontology SDK（OSDK）”；
- 但本仓库仍包含 Ontologies 相关 API（对象类型、动作类型、查询、对象读写入口等）。

**结论**：你给的仓库不是“按某个业务 Ontology 生成、带业务类型封装”的 OSDK，而是更底层、通用、偏 API 映射的 Platform SDK。

### 14.2 SDK 模块分层（与 Action/Function/Ontology Edit 相关）

在 v2 客户端中，核心入口是：
- `client.ontologies.*`：Ontology 资源（Action、ActionType、Object、Query、Transaction、Metadata）。
- `client.functions.*`：Functions 资源（Query、ValueType）。

可理解为两套并行面：
1. **Ontologies 命名空间**：以“本体上下文”为中心，URL 多为 `/v2/ontologies/{ontology}/...`。
2. **Functions 命名空间**：以“函数资产”为中心，URL 多为 `/v2/functions/...`。

### 14.3 Action 相关接口梳理（SDK 实际暴露）

`Ontologies.Action` 暴露三类调用：

1. `apply`  
   `POST /v2/ontologies/{ontology}/actions/{action}/apply`
   - 输入：`parameters` + 可选 `branch` / `transactionId` / `options`。
   - 输出：`SyncApplyActionResponseV2`（含 `validation` 与可选 `edits`）。

2. `apply_batch`  
   `POST /v2/ontologies/{ontology}/actions/{action}/applyBatch`
   - 输入：同一 ActionType 的多请求批量参数。
   - 输出：`BatchApplyActionResponseV2`（批次结果、编辑结果集合）。

3. `apply_with_overrides`（private beta）  
   `POST /v2/ontologies/{ontology}/actions/{action}/applyWithOverrides`
   - 支持覆盖 `UniqueIdentifier` / `CurrentTime` 这类生成参数。

**关键语义**：
- HTTP 200 不等于动作一定业务成功，需要看响应内 `validation`。
- API 文档强调 OSv1/OSv2 可见性差异（OSv2 完成后更快可见）。

### 14.4 ActionType 与执行元数据接口

ActionType 不挂在 `client.ontologies.ActionType`，而是挂在 `client.ontologies.Ontology.ActionType`（这是仓库一个容易误用的点）。

主要接口：
- `get`：按 API name 获取动作类型定义。
- `get_by_rid` / `get_by_rid_batch`：按 RID 获取。
- `list`：分页列出 ActionTypes。

模型层显示：
- `ActionTypeV2.operations` 是 `LogicRule` 列表；
- 支持 `FunctionLogicRule` 与 `BatchedFunctionLogicRule`（说明 function-backed action 在 API 模型层是规则类型之一，而非独立资源）。

### 14.5 Function 相关接口梳理

#### A) `v2.functions.Query`（函数资产视角）
- `execute`: `POST /v2/functions/queries/{queryApiName}/execute`
- `get` / `get_by_rid` / `get_by_rid_batch` / `list`

特点：
- 文档标注 `execute` 为兼容保留，建议新实现优先 streaming execute（若可用）。
- 支持 `version`、`branch`、`transactionId` 等版本/事务参数。

#### B) `v2.ontologies.Query`（本体语义视角）
- `execute`: `POST /v2/ontologies/{ontology}/queries/{queryApiName}/execute`

特点：
- 多了 `ontology` 作用域，参数模型更贴近 Ontology 查询语义。
- 适合与 `Action`、`Object` 在同一业务上下文里组合。

**设计推导**：
- 后端同时提供“函数中心”和“本体中心”两套入口；
- SDK 对两套入口都映射，开发者可按上下文选择。

### 14.6 Ontology Edit 在 SDK 中的体现：两条路径

#### 路径 1：通过 Action 执行（最常见）
- 编辑函数本身不直接暴露“函数写入端点”；
- 常见路径是 Action apply / applyBatch，返回 `validation` + `edits` 摘要。
- 模型有 `BatchActionObjectEdit` / `BatchActionObjectEdits` / `ActionResults` 等。

#### 路径 2：通过 Ontology Transaction 直接提交 edits（实验性能力）
- `POST /v2/ontologies/{ontology}/transactions/{transactionId}/edits`
- 由 `OntologyTransaction.post_edits` 承接 `TransactionEdit[]`。

**结论**：SDK 并非只支持“动作触发编辑”，也支持“事务直接 post edits”，但后者更底层、使用门槛更高，且偏实验能力。

### 14.7 SDK 与后端交互机制：不是“仅调用本体检索接口”

你问到“是否就调用了本体检索接口”，基于代码可得明确答案：**不是**。

SDK 调的是多类后端端点，至少包括：

1. **元数据检索类**：
- `/v2/ontologies/{ontology}`
- `/v2/ontologies/{ontology}/fullMetadata`
- `/v2/ontologies/{ontology}/metadata`

2. **对象检索/统计/聚合类**：
- `/v2/ontologies/{ontology}/objects/{objectType}/{primaryKey}`
- `/aggregate`、`/count` 等

3. **查询执行类**：
- `/v2/functions/queries/.../execute`
- `/v2/ontologies/{ontology}/queries/.../execute`

4. **动作写入类**：
- `/v2/ontologies/{ontology}/actions/{action}/apply`
- `/applyBatch`、`/applyWithOverrides`

5. **事务写入类**：
- `/v2/ontologies/{ontology}/transactions/{transactionId}/edits`

也就是说，SDK 与后端交互覆盖“读元数据 + 读对象 + 执行函数 + 执行动作 + 提交事务编辑”全链路，不是单一检索 API。

### 14.8 具体实现方案推导（从仓库代码反推）

该 SDK 的生成实现模式非常统一，可归纳为 8 步：

1. 每个资源一个 Client（如 `ActionClient`）。
2. 方法上使用 `@pydantic.validate_call` 做入参校验。 
3. 构造 `RequestInfo`（method/path/query/header/body/response_type）。
4. 通过 `core.ApiClient.call_api()` 发起请求。
5. URL 统一拼接为 `/api` + `resource_path`。
6. 认证统一在 header 注入 `Authorization: Bearer ...`。
7. 响应按 `response_type` 反序列化为 Pydantic 模型。
8. 错误按 HTTP code + 错误体映射到 SDK 异常。

并且额外提供：
- `with_raw_response`（保留原始响应对象）；
- `with_streaming_response`（流式读取）；
- Sync/Async 双客户端。

### 14.9 对你要做 Function-backed Action 能力建设的直接建议（基于该 SDK 约束）

1. **优先走 Ontologies.Action.apply / applyBatch 做执行入口**，不要把编辑直接等同于“函数调用”。
2. **把 ActionType.operations 作为能力探针**：识别 `function`/`batchedFunction` 规则决定执行策略。
3. **同时接入 metadata 与 apply 链路**：
   - metadata 用于构建参数表单/权限提示；
   - apply 用于真实写入与结果回执。
4. **可选补充 transaction edits 通道**：仅用于平台内部高级工作流，不作为普通业务入口。
5. **将 branch/version/transactionId 暴露为高级参数**，否则难以支持灰度、回放和审计追溯。

### 14.10 一句话回答你的核心问题

- `foundry-platform-python` 在 action/function/ontology edit 方面是“**API 映射型 SDK**”：通过 REST 端点直接与 Foundry 后端交互；
- 它**不只是**调用“本体检索接口”，而是同时调用动作执行、函数执行、对象查询、元数据加载、事务编辑等多类接口；
- function-backed action 的后端执行面在该 SDK里主要体现为 `Action.apply*` + `ActionType.operations(FunctionLogicRule/BatchedFunctionLogicRule)` + `OntologyTransaction.post_edits` 的组合。
