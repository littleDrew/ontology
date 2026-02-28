# Object Monitor 对标方案调研与设计文档（金融/制造，私有云）

## 1. 背景与目标

本文面向“本体（Ontology）系统 + Object Monitor”建设，目标行业为金融与制造。目标是对标 Palantir Foundry Object Monitor 的核心能力，并形成可商用、可私有化部署、可持续演进的技术方案。

### 1.1 目标约束（来自需求）
- 行业：金融、制造（示例：银行级客户）。
- 对象规模：约 100 万。
- 规则规模：约 1000。
- 用户规模：数千（含 Agent 调用 Action）。
- 执行模式：流式 + 批量。
- SLO：可用性 >=95%，RTO <= 1 小时。
- 部署：私有云优先。
- 成本：客户自有机器部署（偏向开源与可控组件）。

---

## 2. Palantir Object Monitor 能力拆解与关联模型

> 注：Palantir 文档页面显示 `Object Monitors [Sunset]`，因此对标应聚焦“能力与机制”而非界面/名词 1:1 复刻。

### 2.1 核心能力域

1. **Ontology 域**：Object Type、Link Type、Object Set、属性模型。
2. **Monitor 定义域**：监控范围、输入（Input）、条件（Condition）、评估（Evaluation）。
3. **执行域**：流式触发、定时触发、批量重算、回放。
4. **结果域**：Activity（评估活动）、告警通知（Notifications）、自动动作（Actions）。
5. **治理域**：权限、配额、审计、限流、失败恢复。

### 2.2 与本项目的映射

- 本体对象状态变化 -> Monitor 输入事件。
- 持续时长（如高温 1 小时） -> 流式状态机/窗口计算。
- 命中后 -> 通知 + Action 编排 + 全链路审计。

---

## 3. 竞品全景调研（产品/平台/开源）

本节按“可直接对标”与“组合对标”分类，强调与 Object Monitor 的关联关系。

## 3.1 企业产品（可直接采购或深度集成）

### 3.1.1 ServiceNow Event Management + CMDB
- **实现特点**：CI（配置项）模型 + 事件归并 + 告警到工单闭环。
- **与 Object Monitor 关联**：
  - 近似于“对象 + 规则 + 动作”的运营闭环。
  - 但对象语义表达能力更偏 IT 资产，不是通用 Ontology。
- **适配建议**：可作为通知/工单动作域，不建议作为主 Ontology 引擎。

### 3.1.2 Datadog Monitors + Workflow Automation
- **实现特点**：监控规则、异常检测、告警路由与自动化动作。
- **关联关系**：
  - 强在监控/告警执行域。
  - 对“对象关系语义 + 业务本体”支持较弱。
- **适配建议**：适合做外层告警通道，不适合承载核心本体模型。

### 3.1.3 Splunk ES/ITSI
- **实现特点**：事件关联、风险分析、SOC/运维告警。
- **关联关系**：
  - 强在事件聚合与调查。
  - Object-centric 语义需额外构建。
- **适配建议**：可作为安全运营侧的下游分析系统。

### 3.1.4 Dynatrace（Davis AI + Automation）
- **实现特点**：异常检测、根因分析、自动化。
- **关联关系**：更偏应用拓扑与性能对象，不是通用业务对象监控。
- **适配建议**：适合作为“技术监控”平行能力，不替代业务本体监控。

### 3.1.5 Elastic Watcher / Kibana Alerting
- **实现特点**：基于索引查询的条件告警，动作可扩展。
- **关联关系**：
  - 可实现 Monitor 的 condition/evaluation。
  - 对对象关系/图语义与复杂持续状态表达有限。
- **适配建议**：适合中等复杂度规则场景。

### 3.1.6 云厂商告警（AWS/Azure/GCP）
- **实现特点**：指标/日志/事件告警成熟、可托管。
- **关联关系**：执行层可用；对象本体层不足。
- **适配建议**：私有云场景通常仅借鉴设计，不直接采用。

---

## 3.2 开源组合方案（扩展，超出此前两种）

以下方案均可达到“Object Monitor 对标”能力，但侧重点不同。

### 方案 A：Kafka + Flink CEP + Temporal + PostgreSQL + OpenSearch + Keycloak
- **优势**：
  - 流式与持续时长规则能力最强（CEP 原生支持）。
  - 动作编排（Temporal）支持重试/补偿/幂等。
  - 审计与检索清晰分层。
- **劣势**：组件较多，平台运维复杂。
- **适用**：你当前场景（金融+制造）首选。

### 方案 B：Kafka + Kafka Streams + Drools + Argo Workflows + PostgreSQL
- **优势**：组件相对轻量，Java 生态成熟。
- **劣势**：复杂事件模式能力弱于 Flink CEP，状态管理需精心设计。
- **适用**：规则复杂度中等、团队 Java 强。

### 方案 C：Pulsar + Flink + OPA/CEL + Temporal + ClickHouse
- **优势**：流式吞吐强，分析存储成本可控。
- **劣势**：生态整合与团队学习成本较高。
- **适用**：高吞吐、多租户、强分析回查。

### 方案 D：Debezium + PostgreSQL + NATS JetStream + CEL + Prefect
- **优势**：架构较简洁、私有化成本低。
- **劣势**：在超大规模下弹性不如 Kafka/Flink 组合。
- **适用**：中小规模起步，快速 MVP。

### 方案 E：Neo4j + Kafka + Flink + Temporal（图中心方案）
- **优势**：对象关系查询/路径规则表达自然。
- **劣势**：图数据库成本与运维复杂度较高。
- **适用**：关系/关联规则密集型行业（反欺诈、供应链）。

### 方案 F：JanusGraph + Cassandra + Kafka + Flink（全开源横向扩展）
- **优势**：大规模分布式扩展能力强。
- **劣势**：部署运维复杂度最高，研发门槛高。
- **适用**：超大规模、多数据中心企业。

---

## 4. Palantir OSv2 存储模式分析（推断型）

> 说明：公开文档对 OSv2 内部实现细节披露有限。以下为基于常见企业数据平台架构、Palantir 文档语义和工程实践的“高可信推断”，用于设计决策。

## 4.1 两类数据模式

### 模式 1：Non-copy / Virtualized（非复制）
- 核心思想：对象层不复制完整原始数据，依赖外部源（湖仓/DB）映射或按需读取。
- 优势：避免数据冗余、减少存储成本、与源系统一致性高。
- 挑战：查询延迟与可用性受源系统影响；评估时要做缓存与快照策略。

### 模式 2：Copy / Materialized（复制）
- 核心思想：对象后端持有投影/副本（全量或增量）。
- 优势：评估性能好、规则计算稳定、可重放与审计更容易。
- 挑战：数据同步延迟、存储成本、去重与版本治理复杂。

## 4.2 去重（de-duplicate）机制推断

在复制模式中，典型实现是：
1. 以业务主键 + 版本号 + 来源系统标识构建唯一键。
2. CDC 事件进入去重器（按主键/序列号幂等）。
3. 仅保存最新快照 + 变更日志（可配置保留窗口）。
4. 对大字段做列式压缩/外部对象存储引用，减少重复存储。

---

## 5. 不同数据模式下的 Object Monitor 机制设计

## 5.1 复制模式（Copy/Materialized）

### 机制
- Monitor Evaluation 主要读取本地对象投影（低延迟）。
- 流式规则读取 CDC 事件，批量规则扫描投影快照。
- Activity 与审计记录完整保存在平台侧。

### 适配图数据库后端（Neo4j / pggraph）
- 关系条件规则（如 2-hop 邻接约束）直接在图查询层求值。
- 持续时长规则仍建议在流处理层做状态机，避免图库成为高频计算引擎。

## 5.2 非复制模式（Non-copy/Virtualized）

### 机制
- 评估前通过 Data Access Adapter 拉取最新状态。
- 需要“短期状态缓存 + 输入快照”保证评估一致性。
- 对持续时长规则必须维护平台侧状态存储（不能每次回源重算）。

### 关键补偿设计
1. **快照一致性**：每次评估写入 input snapshot hash。
2. **回源容错**：源不可用时降级为“延迟评估 + 补偿重算”。
3. **审计可复现**：记录外部数据版本戳（watermark/LSN）。

## 5.3 混合模式（推荐）

- 高频监控字段复制（hot projection）。
- 低频/大字段虚拟化访问（cold virtualized）。
- 同时获得低延迟和低存储成本。

---

## 6. 对标 Object Monitor 的目标架构（建议）

```text
[Source Systems]
   | CDC/Event API
   v
[Ingestion Bus: Kafka/Pulsar]
   |--> [Projection Builder] --> [Object Store: PG + Graph(optional)]
   |--> [Stream Evaluator: Flink CEP]

[Monitor Service]
   |- Monitor DSL / Versioning / RBAC
   |- Input Resolver
   |- Condition Engine (CEL/Drools)
   |- Evaluation Orchestrator (stream + batch)

[Action & Notification]
   |- Temporal/Argo workflows
   |- Email/SMS/IM/Webhook/ITSM connector

[Activity & Audit]
   |- Immutable logs (OpenSearch/ClickHouse)
   |- Replay & Forensics
```

### 6.1 关键模块
- `MonitorDefinitionService`
- `InputBindingService`
- `ConditionCompiler`
- `EvaluationRuntime`
- `DurationStateStore`
- `NotificationRouter`
- `ActionOrchestrator`
- `ActivityLedger`
- `TenantQuotaService`

### 6.2 关键能力
- 流式 + 批量双引擎。
- 持续时长规则（duration windows）。
- 幂等动作执行与失败补偿。
- 私有云部署与多租户隔离。

---

## 7. 规格建议（按当前规模）

### 7.1 目标规格（首版）
- 对象：100 万。
- 规则：1000。
- 峰值评估吞吐：建议按 300~800 eval/s 设计。
- 持续时长规则状态键：按 100 万对象 * 活跃规则比例估算状态容量。

### 7.2 SLO/SRE
- 可用性：建议从 95% 逐步提升到 99.5%。
- RTO：<=1 小时（通过分层恢复 + 重放队列实现）。
- RPO：建议 <= 5 分钟（关键元数据强一致备份）。

---

## 8. 风险与治理

1. **规则爆炸风险**：规则组合指数增长导致评估风暴。
   - 对策：规则分层、租户配额、复杂度评分、熔断。
2. **动作风暴风险**：同一事件触发大量下游动作。
   - 对策：去重键、抑制窗口、最大并发限制。
3. **非复制模式可用性风险**：外部源不稳定导致漏评估。
   - 对策：快照缓存 + 回补重算 + source watermark 审计。
4. **图数据库热点风险**：高频规则全打到图查询。
   - 对策：图关系预计算 + 缓存 + 流式状态化。

---

## 9. 分阶段实施计划

### Phase 1（8~10 周）
- Monitor DSL、规则管理、基础流式评估、通知、活动日志。

### Phase 2（8~12 周）
- 动作编排、持续时长高级规则、批量回补、审计回放。

### Phase 3（持续）
- 混合存储优化（复制/非复制协同）、行业模板（金融/制造）、智能规则推荐。

---

## 10. 下一步（用于 PR 持续迭代，已展开为可执行设计）

本节将上一版“后续任务”落地为可以直接进入研发排期的设计产物。

### 10.1 竞品矩阵（产品 / 组合 / 开源）

> 目标：从“功能可比”升级到“实现可比 + 可落地可运维可迁移”。

| 类别 | 方案 | Object Model | Rule/Eval | Duration Rule | Action Orchestration | Audit/Replay | 私有云适配 | 与 Palantir Object Monitor 关系 |
|---|---|---|---|---|---|---|---|---|
| 厂商产品 | ServiceNow Event Mgmt + CMDB | 强（CI） | 中 | 弱-中 | 强（工单/流程） | 中 | 强 | 运维对象闭环近似，但通用本体语义不足 |
| 厂商产品 | Datadog Monitors + Workflow | 中 | 强 | 中 | 强 | 中 | 中 | 执行层强，Ontology 层弱 |
| 厂商产品 | Splunk ITSI/ES | 中 | 强 | 中 | 中 | 强 | 中 | 事件关联强，业务对象语义需外置 |
| 厂商产品 | Dynatrace + AutomationEngine | 中 | 强 | 中 | 中-强 | 中 | 中 | 技术拓扑监控强，不是业务本体中心 |
| 厂商产品 | Elastic Alerting/Watcher | 弱-中 | 中-强 | 弱-中 | 中 | 中 | 强 | 可构建 condition/eval，复杂关系表达有限 |
| 云原生 | AWS/Azure/GCP Alerting | 弱 | 强 | 中 | 中 | 中 | 弱（私有云） | 可借鉴机制，不是私有化首选 |
| 开源组合 | Kafka + Flink CEP + Temporal + PG | 中-强 | 强 | 强 | 强 | 强 | 强 | 能力面最接近，可工程化复刻 |
| 开源组合 | Kafka Streams + Drools + Argo | 中 | 中-强 | 中 | 强 | 中 | 强 | 轻量可行，复杂 CEP 不如 Flink |
| 开源组合 | Pulsar + Flink + ClickHouse | 中 | 强 | 强 | 中-强 | 强 | 中-强 | 高吞吐强，整合复杂 |
| 开源组合 | Debezium + NATS + CEL + Prefect | 中 | 中 | 中 | 中 | 中 | 强 | MVP 速度快，峰值弹性一般 |
| 图中心 | Neo4j + Kafka + Flink + Temporal | 强 | 强 | 强 | 强 | 强 | 中-强 | 关系规则最佳，成本与运维较高 |
| 图中心 | JanusGraph + Cassandra + Flink | 强 | 强 | 强 | 中 | 中-强 | 中 | 超大规模扩展强，工程门槛高 |

**结论**：当前约束（金融/制造 + 私有云 + 100w 对象 + 1000 规则）下，首选仍是 `Kafka + Flink CEP + Temporal + PostgreSQL(+可选图库)`。

### 10.2 Object Monitor DSL 草案（可进入 PoC）

#### 10.2.1 语法草案（简化 BNF）

```bnf
monitor          ::= "monitor" IDENT "{" scope input condition schedule action notify policy "}"
scope            ::= "scope" "{" object_type object_filter? "}"
object_type      ::= "objectType" ":" IDENT
object_filter    ::= "filter" ":" EXPR
input            ::= "input" "{" binding+ "}"
binding          ::= IDENT ":" source_expr
condition        ::= "condition" ":" bool_expr
schedule         ::= "schedule" ":" ("event"|cron_expr)
action           ::= "action" "{" action_call* "}"
notify           ::= "notify" "{" channel_rule* "}"
policy           ::= "policy" "{" dedup cooldown severity retry "}"
dedup            ::= "dedupKey" ":" EXPR
cooldown         ::= "cooldown" ":" DURATION
severity         ::= "severity" ":" ("P1"|"P2"|"P3"|"P4")
retry            ::= "retry" ":" retry_spec
```

#### 10.2.2 示例 1：状态变化触发

```yaml
monitor HighTempSpike {
  scope {
    objectType: Boiler
    filter: region == "CN-NORTH"
  }
  input {
    t: object.temperature
    threshold: object.maxSafeTemperature
  }
  condition: t > threshold
  schedule: event
  action {
    call CreateMaintenanceTicket(priority="P2")
  }
  notify {
    channel email(to="ops@company.com") when severity in ["P1","P2"]
    channel webhook(url="https://alert-gw/internal")
  }
  policy {
    dedupKey: object.id + ":" + monitor.name
    cooldown: 10m
    severity: P2
    retry: exp(backoff=5s,max=5)
  }
}
```

#### 10.2.3 示例 2：持续时长规则（高温持续 1 小时）

```yaml
monitor HighTempFor1h {
  scope {
    objectType: Furnace
  }
  input {
    t: object.temperature
  }
  condition: duration(t > 120, "1h")
  schedule: event
  action {
    call StopProductionLine(lineId=object.lineId)
  }
  notify {
    channel sms(to=object.ownerPhone)
    channel im(room="manufacture-warroom")
  }
  policy {
    dedupKey: object.id + ":high-temp-1h"
    cooldown: 30m
    severity: P1
    retry: exp(backoff=10s,max=8)
  }
}
```

### 10.3 复制 / 非复制 模式 API 与一致性策略（详细）

#### 10.3.1 控制面 API（两种模式通用）
- `POST /v1/monitors`：创建监控规则（返回 monitorId + version）。
- `POST /v1/monitors/{id}/publish`：发布到运行态。
- `POST /v1/monitors/{id}/pause`：暂停。
- `GET /v1/monitors/{id}/activity?from=&to=`：查询评估活动。
- `POST /v1/monitors/{id}/replay`：按时间窗重放评估。

#### 10.3.2 数据面 API（复制模式）
- `POST /v1/object-events`：接收 CDC/事件。
- `GET /v1/object-projection/{objectType}/{objectId}`：读取投影快照。
- 一致性：`at-least-once event + idempotent projection + version watermark`。

#### 10.3.3 数据面 API（非复制模式）
- `POST /v1/evaluation/pull`：触发回源评估。
- `POST /v1/input-resolver/cache/refresh`：刷新输入缓存。
- 一致性：`snapshot-hash + source-version(lsn/watermark) + delayed-compensation`。

#### 10.3.4 关键一致性约束
1. 每次评估必须写 `evaluation_id`、`monitor_version`、`input_snapshot_hash`。
2. 每次动作执行必须写 `action_idempotency_key`。
3. 回放评估不得覆盖原活动记录，只能 append 新纪录并链路关联。

### 10.4 性能与可靠性验证设计（压测 / 演练）

#### 10.4.1 基线压测场景
- 对象 100w，规则 1000，活跃规则比例 20%。
- 变更事件峰值：2000 events/s，持续 30 分钟。
- 目标：评估延迟 P95 < 3s；通知成功率 > 99.9%。

#### 10.4.2 故障注入场景
- Kafka Broker 故障（单点/双点）。
- Flink TaskManager 重启。
- 图数据库热点查询超时。
- 外部通知网关不可用 15 分钟。

#### 10.4.3 验收门槛（首期）
- 可用性 >= 95%（建议冲刺 99.5%）。
- RTO <= 1h。
- 关键事件零丢失（允许延迟，不允许无审计漏记）。

### 10.5 研发拆解（可直接进 Jira）

1. **M1 - DSL 与编译器**：语法、静态检查、版本化。
2. **M2 - 流式运行时**：duration 状态机、去重、冷却窗口。
3. **M3 - 批量回补**：日/小时重算、结果对账。
4. **M4 - Action 编排**：幂等、重试、补偿、死信。
5. **M5 - 审计与回放**：活动账本、法务导出、可追溯。
6. **M6 - 多租户治理**：配额、限流、权限边界。
7. **M7 - 观测与 SRE**：SLI/SLO、看板、告警、演练。

### 10.6 下一轮文档增量（PR-2 目标）

- 增加《Object Monitor DSL 规范（v0.1）》独立文档。
- 增加《Copy/Non-copy 一致性协议》时序图与状态机图。
- 增加《竞品矩阵 CSV》可排序版本（含成本/运维评分）。
- 增加《压测与故障演练报告模板》。

---

## 11. Phase 1（8~10 周）详细设计方案

> 目标：在 8~10 周内交付“可上线试运行”的第一版能力：Monitor DSL、规则管理、基础流式评估、通知、活动日志。

### 11.1 Phase 1 范围边界（In Scope / Out of Scope）

#### In Scope
1. Monitor DSL v0.1（阈值 + 持续时长条件，含基础去重/冷却策略）。
2. 规则管理控制台/接口（创建、发布、暂停、版本回滚）。
3. 基础流式评估引擎（事件驱动 + 状态机）。
4. 通知通道（Email/Webhook/企业IM 三选二起步）。
5. 活动日志（评估记录、命中记录、通知记录，支持审计检索）。

#### Out of Scope（Phase 2+）
1. 复杂动作编排（多步补偿、跨系统事务）。
2. 批量全量回补与高级对账。
3. AI 规则推荐、复杂图推理。

### 11.2 逻辑架构（Phase 1）

```text
[Object Event Sources]
   -> [Ingestion Adapter]
   -> [Kafka Topic: object-events]
   -> [Rule Matcher]
   -> [Input Resolver]
   -> [Condition Evaluator + Duration State Store]
   -> [Evaluation Result Topic]
   -> [Notification Dispatcher]
   -> [Activity Log Writer]

[Monitor Control Plane]
   -> [DSL Parser/Validator]
   -> [Rule Registry + Versioning]
   -> [Publish/Pause API]
```

### 11.3 数据模型详细设计

#### 11.3.1 控制面表
- `monitor_definition`
  - `monitor_id`、`tenant_id`、`name`、`dsl_text`、`status`、`created_by`、`created_at`。
- `monitor_version`
  - `version_id`、`monitor_id`、`version`、`compiled_plan`、`checksum`、`published_at`。
- `monitor_publish_history`
  - `id`、`monitor_id`、`version`、`operation(publish/pause/rollback)`、`operator`、`ts`。

#### 11.3.2 运行面表
- `evaluation_activity`
  - `evaluation_id`、`tenant_id`、`monitor_id`、`monitor_version`、`object_ref`、`event_time`、`result`、`latency_ms`、`input_snapshot_hash`。
- `notification_activity`
  - `id`、`evaluation_id`、`channel`、`payload_hash`、`status`、`retry_count`、`sent_at`。
- `duration_state`
  - `state_key(tenant+monitor+object)`、`entered_at`、`last_seen_at`、`state_payload`。

### 11.4 API 详细设计（Phase 1）

#### 控制面
- `POST /v1/monitors`
  - 输入：DSL 文本 + 元数据。
  - 校验：语法、字段类型、引用对象类型存在性。
  - 输出：`monitor_id`。
- `POST /v1/monitors/{id}/publish`
  - 动作：冻结当前版本并下发到运行时缓存。
- `POST /v1/monitors/{id}/pause`
  - 动作：运行时停用，不删除历史。
- `POST /v1/monitors/{id}/rollback?version=x`
  - 动作：回滚到历史稳定版本。
- `GET /v1/monitors/{id}/activities`
  - 支持按时间窗、对象、结果筛选。

#### 数据面
- `POST /v1/object-events`
  - 字段：`tenant_id`、`object_type`、`object_id`、`event_type`、`event_ts`、`payload`、`source_version`。
  - 幂等键：`tenant_id + source + source_event_id`。

### 11.5 核心执行流程与状态机

#### 11.5.1 阈值规则
1. 事件进入 Rule Matcher。
2. 按 object_type + filter 命中规则集合。
3. Input Resolver 提取输入。
4. Condition Evaluator 计算布尔结果。
5. 命中后写 evaluation_activity，异步触发通知。

#### 11.5.2 持续时长规则（duration）
状态机：`IDLE -> ENTERED -> FIRING -> COOLDOWN -> IDLE`
- `IDLE`: 条件不满足。
- `ENTERED`: 首次满足条件，记录 `entered_at`。
- `FIRING`: `now - entered_at >= duration`，触发一次。
- `COOLDOWN`: 冷却期内抑制重复通知。

### 11.6 非功能设计（Phase 1）

#### 性能预算（100w 对象 / 1000 规则）
- 事件摄入目标：>= 1000 events/s（可突发 2000）。
- 评估延迟：P95 < 3s，P99 < 8s。
- 通知投递成功率：> 99.9%（重试后）。

#### 可用性与恢复
- 运行时无状态组件多副本。
- 状态存储（duration_state）使用高可用后端（Redis Cluster 或 RocksDB + checkpoint）。
- RTO <= 1h：基于 Kafka 重放 + 规则版本恢复。

#### 安全与审计
- 租户隔离：所有主键包含 `tenant_id`。
- 审计：发布/暂停/回滚、规则变更、通知发送均落审计日志。
- 权限：`monitor.admin`、`monitor.editor`、`monitor.viewer`。

### 11.7 交付拆解（按周）

- **W1-W2**：DSL 语法、Parser、静态校验、对象类型联调。
- **W3-W4**：规则注册中心、发布/暂停/回滚 API、运行时规则缓存。
- **W5-W6**：流式评估 + duration 状态机 + 活动日志。
- **W7**：通知通道（Email/Webhook/IM）+ 重试与去重。
- **W8**：端到端联调、压测、故障演练。
- **W9-W10（缓冲）**：性能优化、问题修复、试运行验收。

### 11.8 验收标准（Definition of Done）

1. 支持 200+ 条 DSL 规则稳定发布与执行。
2. 持续时长规则准确率 >= 99.99%（对照离线回算基准）。
3. 可观测指标齐全：吞吐、延迟、命中率、通知失败率、重试次数。
4. 关键审计链路可查询并可导出。

---

## 12. 作为专业架构师的评估、问题识别与优化方案

本节先对“初版 Phase 1 设计”进行批判性评估，再给出修正后的优化版。

### 12.1 架构评估（评审结论）

#### 评分（5 分制）
- 需求覆盖度：4.5
- 可实现性：4.0
- 可运维性：3.8
- 可扩展性：4.2
- 风险可控性：3.7

**总体结论**：方案可落地，但在“规则爆炸防护、状态存储恢复、通知风暴抑制、配置漂移治理”上需强化。

### 12.2 识别到的问题清单

1. **问题 P1：规则匹配效率风险**
   - 现状：按 object_type/filter 动态筛选，规则数增长后匹配开销变大。
   - 风险：高峰期 evaluation 队列积压。

2. **问题 P2：duration 状态恢复缺口**
   - 现状：仅描述了状态机，未定义 checkpoint 与恢复一致性细节。
   - 风险：重启后持续时长判断偏差。

3. **问题 P3：通知风暴与外部依赖抖动**
   - 现状：仅有重试，缺少分级限流与抑制策略矩阵。
   - 风险：下游网关故障时级联放大。

4. **问题 P4：多租户资源竞争**
   - 现状：配额原则有描述，但缺少强制执行点。
   - 风险：大租户挤占资源影响全局。

5. **问题 P5：变更治理不足**
   - 现状：规则发布流程缺“灰度发布 + 自动回滚”机制。
   - 风险：错误规则全量生效造成误报/漏报。

### 12.3 优化后方案（修订版）

#### O1. 规则索引与分片优化（解决 P1）
- 预编译规则为 `match_plan`，构建二级索引：`object_type -> predicate bucket`。
- 按 `tenant_id + object_type` 做运行时分区，减小单分区规则集。
- 增加“规则复杂度评分”，超过阈值需审批发布。

#### O2. 状态一致性与恢复优化（解决 P2）
- duration 状态采用双写策略：
  - 热状态：本地状态存储（Flink state/RocksDB）。
  - 冷恢复：周期 checkpoint + 外部快照（对象存储）。
- 恢复流程：`load checkpoint -> replay from watermark -> reconcile`。

#### O3. 通知稳态控制（解决 P3）
- 引入通知策略矩阵：`severity x channel x retry_policy x throttle`。
- 增加熔断与退避：当下游故障率 > 阈值，自动切换降级通道。
- 同一 dedupKey 在窗口内只发送一次（窗口可按级别配置）。

#### O4. 多租户 QoS（解决 P4）
- 每租户独立配额：`events/s`、`active_rules`、`notifications/min`。
- 调度采用加权公平队列（WFQ），避免大租户抢占。
- 超配额事件进入延迟队列并打审计标记。

#### O5. 发布治理（解决 P5）
- 规则发布改为三段式：`staging -> canary(5%) -> full`。
- Canary 失败触发自动回滚并阻断全量发布。
- 发布前强制执行“静态规则体检 + 小样本回放测试”。

### 12.4 优化后的 Phase 1 目标值（更新）

- 事件峰值能力：2000 events/s 持续 30 分钟不丢失。
- 评估延迟：P95 < 2.5s（较初版收紧）。
- 误通知率：< 0.1%。
- 规则发布失败自动回滚时间：< 2 分钟。

### 12.5 优化后验收清单（新增）

1. 通过“规则风暴压测”与“通知网关故障演练”。
2. 完成一次生产前灰度发布演练（含自动回滚）。
3. 完成一次租户配额冲突演练并验证 WFQ 生效。
4. 完成一次 checkpoint 恢复演练并验证 duration 连续性。
