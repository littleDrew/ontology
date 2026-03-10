# Object Monitor Phase 1 CDC 集成方案（Neo4j Kafka Connector）

## 1. 结论（先回答你的核心问题）

**Phase 1 需要按 Neo4j 版本分层集成**：

- Neo4j Enterprise/Aura：使用 Neo4j Kafka Connector（CDC strategy）；
- Neo4j Community 4.4.48：不具备 `db.cdc.*` 与 CDC connector 路径，优先 `Outbox + Neo4j Streams + Reconcile`，次选 `Outbox + APOC Trigger + Reconcile`；

并统一定位为：

- `Outbox` 的并行兜底通道，覆盖“直写 Neo4j / 外部同步写入 Neo4j”场景；
- 与现有 `object_change_raw -> normalize/dedupe -> object_change` 流水线统一汇流；
- 在归一化层做幂等去重，避免 outbox+cdc 双发导致重复动作。


## 1.1 你当前环境（Neo4j Community 4.4.48）的关键结论

你当前判断是正确的：**Neo4j Community 4.4.48 无法按本方案直接使用 Neo4j CDC Connector**。

原因：

1. 现有 connector 的 CDC strategy 依赖 `db.cdc.current / db.cdc.query` 相关能力；
2. 该能力在 Community 4.4.48 不可用；
3. 仓库内 `test_neo4j_cdc_capture_integration.py` 已对该能力缺失做 `skip` 分支。

因此，Phase 1 不能把“CDC connector 可用”作为前置条件，必须提供 Community 可落地路径。

## 2. 当前仓库补齐内容

### 2.1 事件语义补齐（属性级变化）

`ObjectChangeEvent` 已支持：

- `object_type`
- `object_id`
- `changed_fields`
- `changed_properties[]`（`field/old_value/new_value`）
- `event_time`
- `change_source`

这满足“先聚焦对象属性变化”的阶段目标。

### 2.2 CDC 接入代码（不再只有 mock payload）

新增/增强：

1. `Neo4jKafkaSourceConfig`
   - 按 Neo4j 官方 CDC source 配置键生成 payload：
   - `neo4j.source-strategy=CDC`
   - `neo4j.cdc.topic.<topic>.patterns=...`
2. `KafkaConnectClient`
   - 通过 Kafka Connect REST `PUT /connectors/<name>/config` 执行 upsert。
3. `Neo4jKafkaCdcEventMapper`
   - 支持 **Kafka Connector message** 映射；
   - 支持 **`CALL db.cdc.query` 实际返回行** 映射（用于真实 CDC 捕获验证）。
4. `KafkaCdcIngestor`
   - 从 Kafka topic 拉取 CDC 消息，映射后进入 `DualChannelIngestionPipeline`。
5. `scripts/object_monitor/register_neo4j_cdc_connector.py`
   - 可直接注册/更新 connector。

## 3. 推荐端到端拓扑

```text
Neo4j (CDC enabled)
  -> Neo4j Kafka Connector (source strategy = CDC)
  -> Kafka topic: object_change_raw
  -> KafkaCdcIngestor / DualChannelIngestionPipeline
  -> ChangeNormalizer (dedupe + reconcile)
  -> object_change (标准事件)
  -> filter -> evaluator -> action dispatcher
```

并行保留：

```text
ontology write path -> Tx outbox -> object_change_raw
```

## 4. Neo4j Kafka Connector 配置要点（官方 CDC 风格）

关键配置（示例）：

```json
{
  "name": "objm-neo4j-cdc",
  "config": {
    "connector.class": "org.neo4j.connectors.kafka.source.Neo4jConnector",
    "tasks.max": "1",
    "neo4j.source-strategy": "CDC",
    "neo4j.server.uri": "bolt://127.0.0.1:7687",
    "neo4j.authentication.basic.username": "neo4j",
    "neo4j.authentication.basic.password": "***",
    "neo4j.database": "neo4j",
    "neo4j.cdc.poll-interval": "1s",
    "neo4j.cdc.poll-duration": "5s",
    "neo4j.cdc.from": "NOW",
    "neo4j.cdc.topic.object_change_raw.patterns": "(:Device)",
    "neo4j.cdc.topic.object_change_raw.key-strategy": "ELEMENT_ID"
  }
}
```

## 5. 验证策略

### 5.1 单元/组件层

- 校验 connector payload 是否符合 CDC 键命名。
- 校验 connector message 与 neo4j cdc query row 的映射正确性。

### 5.2 集成层（真实 Neo4j CDC 捕获）

新增测试：`tests/object_monitor/test_neo4j_cdc_capture_integration.py`

逻辑：

1. 连接真实 Neo4j；
2. 调 `CALL db.cdc.current()` 获取 cursor；
3. 执行 Device 属性更新；
4. 调 `CALL db.cdc.query(cursor)` 获取 CDC 真实事件；
5. 使用 `Neo4jKafkaCdcEventMapper.from_neo4j_cdc_query_event(...)` 映射并断言 old/new。

> 该测试不是 mock payload，而是直接从 Neo4j CDC procedure 拉取变更事件。

## 6. 风险与边界

1. Neo4j CDC procedure 能力依赖 CDC-enabled 环境（通常需 Enterprise/Aura）；
2. 本仓库测试环境若无 Neo4j CDC 能力，集成测试会 `skip`；
3. 在本地/CI建议采用“默认单元测试 + 外部栈集成测试（夜间）”两层模式。

## 7. 运行指引（最小）

### 7.1 注册 connector

```bash
python scripts/object_monitor/register_neo4j_cdc_connector.py \
  --connect-url http://127.0.0.1:8083 \
  --connector-name objm-neo4j-cdc \
  --neo4j-uri bolt://127.0.0.1:7687 \
  --neo4j-user neo4j \
  --neo4j-password your-password \
  --kafka-topic object_change_raw \
  --pattern '(:Device)'
```

### 7.2 跑真实 CDC 捕获测试

```bash
export NEO4J_URI=bolt://127.0.0.1:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD=your-password
pytest -q tests/object_monitor/test_neo4j_cdc_capture_integration.py
```

## 8. 本体（ontology）仓库验证所需环境搭建与完整验证步骤

> 本节面向“在本仓库做真实 CDC 联调验证”的操作手册，包含依赖组件、启动顺序、关键检查点与验收标准。

### 8.1 环境依赖

建议准备如下组件：

1. **Neo4j（CDC-enabled）**
   - 需要支持 `db.cdc.current` / `db.cdc.query`；
   - 建议 Neo4j 5 Enterprise 或 Aura Enterprise。
2. **Kafka Broker**
3. **Kafka Connect**
   - 安装 Neo4j Kafka Connector 插件（与 Neo4j 版本匹配）。
4. **Python 运行环境（本仓库）**
   - `pip install -r requirements.txt`

### 8.2 本仓库依赖安装

```bash
cd /workspace/ontology
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 8.3 Neo4j 侧前置检查

确保 Neo4j 可连通并且 CDC procedure 可用：

```cypher
SHOW PROCEDURES YIELD name
WHERE name STARTS WITH 'db.cdc.'
RETURN name;
```

预期至少包含：

- `db.cdc.current`
- `db.cdc.query`

若缺失，说明当前 Neo4j 环境未开启/不支持 CDC，后续真实 CDC 验证会被 `skip`。

### 8.4 注册 Neo4j Kafka Connector（CDC source）

使用仓库内脚本注册 connector：

```bash
python scripts/object_monitor/register_neo4j_cdc_connector.py \
  --connect-url http://127.0.0.1:8083 \
  --connector-name objm-neo4j-cdc \
  --neo4j-uri bolt://127.0.0.1:7687 \
  --neo4j-user neo4j \
  --neo4j-password your-password \
  --neo4j-database neo4j \
  --kafka-topic object_change_raw \
  --pattern '(:Device)'
```

### 8.5 Connector 健康检查

```bash
curl -s http://127.0.0.1:8083/connectors/objm-neo4j-cdc/status
```

预期：

- connector 状态 `RUNNING`
- task 状态 `RUNNING`

### 8.6 触发 Neo4j 真实变更并验证 CDC 采集

1. 在 Neo4j 执行对象更新（例如 `Device.temperature/status`）。
2. 在 Kafka 消费 `object_change_raw`，确认有 CDC 消息到达。
3. 用 `Neo4jKafkaCdcEventMapper` 映射后，应可得到：
   - `object_type/object_id`
   - `changed_fields`
   - `changed_properties(field, old_value, new_value)`

### 8.7 在本仓库执行验证测试

#### A. CDC 映射与配置单测

```bash
pytest -q tests/object_monitor/test_cdc_connector.py
```

#### B. 双通道归一化与去重链路

```bash
pytest -q tests/object_monitor/test_dual_channel_pipeline.py tests/object_monitor/test_publish_and_normalize.py
```

#### C. 真实 Neo4j CDC 捕获（非 mock）

```bash
export NEO4J_URI=bolt://127.0.0.1:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD=your-password
pytest -q tests/object_monitor/test_neo4j_cdc_capture_integration.py
```

### 8.8 验收标准（建议）

满足以下条件可视为“本体仓库 CDC Phase 1 验证通过”：

1. `db.cdc.query` 可返回更新事件；
2. Kafka topic `object_change_raw` 可持续收到 CDC 消息；
3. 映射后 `changed_properties` 含 old/new 明细；
4. outbox + cdc 同版本双发时，仅一条事件进入评估链路（去重成立）；
5. 上述测试通过（或在无 CDC 环境时明确 `skip` 原因）。

### 8.9 常见问题排查

- **问题：connector 创建成功但无数据**
  - 检查 pattern 是否匹配（如是否包含 `(:Device)`）；
  - 检查 Neo4j 用户权限与数据库名；
  - 检查 `neo4j.cdc.from` 是否从 `NOW` 导致历史变更不可见。
- **问题：测试被 skip**
  - 检查 `NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD` 是否设置；
  - 检查 Neo4j 是否支持 `db.cdc.*` procedure。
- **问题：收到 CDC 但 object_id 解析为空**
  - 确认 `object_id_field` 与图中主键属性一致（例如 `device_id`）。




## 9. Neo4j Community 4.4.48 的 Phase 1 可落地实现（替代 CDC Connector）

### 9.1 目标重述

在不升级 Neo4j 版本的前提下，完成对象变更捕获（创建、修改、删除）并打通到 `object_change_raw -> normalize/dedupe -> object_change`。

### 9.2 分层方案

1. **L0（必须）Outbox 主通道**
   - 所有通过 ontology 服务层的对象写入，事务提交后发布 raw 事件；
   - 事件必须带 `op_type`（create/update/delete）与 `object_version`。

2. **L1（推荐）Neo4j Streams 直写兜底**
   - 覆盖外部脚本或人工直接写库；
   - 通过 Streams 将节点/关系变更推送到 Kafka，再映射到统一 Trigger Envelope。

3. **L1-B（次选）APOC Trigger 轻触发**
   - 当 Streams 不可用或运维成本不可接受时启用；
   - Trigger 仅提取最小 envelope 并投递，不做复杂逻辑。

4. **L2（必须）Reconcile Scanner 最终一致补偿**
   - 周期扫描 `updated_at` 水位线，生成 upsert 事件；
   - 删除通过 tombstone 表或 delete_audit 表补齐。

### 9.3 Neo4j Streams vs APOC Trigger（Community 4.4）

| 维度 | Neo4j Streams | APOC Trigger |
|---|---|---|
| 采集定位 | 变更事件外送插件（更接近数据通道） | 库内触发器（事务钩子） |
| 对业务逻辑侵入 | 低（配置为主） | 高（Cypher/触发逻辑下沉 DB） |
| 事务路径负担 | 相对更低 | 相对更高，易放大写事务抖动 |
| 运维复杂度 | 中（插件部署 + Kafka 依赖） | 中高（触发器生命周期和回滚复杂） |
| 删除事件可观测性 | 可通过事件流配置和 tombstone 协作增强 | 依赖触发器实现，易遗漏边界 |
| 推荐角色 | Community 首选直写捕获通道 | 受限场景补洞方案 |

结论（Phase 1）：**若团队已有 Kafka/Connect 运维能力，Streams 通常优于 APOC Trigger**；若当前无法稳定运维 Streams，再退回 APOC Trigger，并以 Reconcile 扫描兜底。

### 9.4 事件模型补充（Community 路径）

`ObjectChangeRawEvent` 建议新增字段（若已有同义字段可复用）：

- `op_type`: `create|update|delete|upsert`
- `capture_mode`: `outbox|neo4j_streams|apoc_trigger|reconcile`
- `event_seq`: 递增序列（优先业务版本，其次更新时间戳）

去重键继续使用：`tenant_id + object_type + object_id + object_version`。

### 9.5 删除事件实现建议

Community 下删除最容易丢失，建议二选一：

1. **软删优先**：写 `is_deleted=true, deleted_at`，由扫描器与 Streams/Trigger 都可观察；
2. **硬删 + 墓碑表**：删前写 tombstone，再执行删除。

没有 tombstone 时，Reconcile 只能发现“对象不存在”，无法确定删除时间与操作者。

### 9.6 Phase 1 里程碑修订（Community 版本）

- M1：Outbox 事件字段补齐 + 单元测试（create/update/delete）。
- M2：Neo4j Streams PoC（仅 Device）+ 压测去重正确率；若不可用则切 APOC Trigger PoC。
- M3：Reconcile Scanner + watermark 持久化。
- M4：双通道/三通道冲突演练（outbox+streams/trigger+reconcile 同版本）。
- M5：上线守护指标（延迟、重复率、漏检率、删除补偿率）。

### 9.7 升级路径

后续若升级到 Neo4j 5 Enterprise/Aura：

- 保持 `object_change_raw` 契约不变；
- 仅替换“变更捕获适配层”（`streams|apoc/reconcile -> cdc connector`）；
- normalize/dedupe、evaluator、activity/action 链路无需重写。


## 10. Community 4.4 Streams 端到端验证（新增）

- 用例目标：验证 `User.money` 从 50 更新到 150 后，Monitor 命中 `money > 100`，并触发 Action 将 `User.tag` 从 `poor` 更新为 `rich`。
- 集成测试：`tests/object_monitor/test_neo4j_streams_user_money_integration.py`。
- 组件测试：`tests/object_monitor/test_streams_connector.py`（Streams 消息映射）。
- 运行命令：

```bash
pytest -q tests/object_monitor/test_streams_connector.py tests/object_monitor/test_neo4j_streams_user_money_integration.py
```

说明：集成测试依赖可访问 Neo4j（`NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD`），缺失时会自动 `skip`。
