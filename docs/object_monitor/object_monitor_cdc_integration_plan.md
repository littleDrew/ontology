# Object Monitor Phase 1 变更接入方案（Neo4j Community 4.4.48：Streams + Kafka）

## 1. 一阶段目标与结论

Phase 1 在当前仓库与部署假设下，主路径统一为：

- **事实写入主通道**：Ontology 写路径产出 Tx Outbox -> `object_change_raw`；
- **直写补齐副通道**：Neo4j Community 4.4.48 通过 **Neo4j Streams 插件**推送变更到 Kafka；
- **最终一致性补偿**：Reconcile Scanner 扫描 `updated_at`/删除审计并补发 raw 事件；
- **统一归一化**：全部进入 `object_change_raw -> normalize/dedupe -> object_change`。

这与 Phase 1 设计文档中“Community 4.4 优先 Streams，APOC 次选，Reconcile 兜底”的约束保持一致。

## 2. 为什么 Phase 1 选 Streams + Kafka（Community 4.4.48）

1. Community 4.4.48 不具备 `db.cdc.*` 能力，不能把 CDC procedure 当作一阶段前提。
2. Streams 是社区版可落地的库级变更外送机制，能覆盖外部同步/人工直写 Neo4j。
3. Kafka 已在 monitor runtime 的事件总线方案内，接入 Streams 成本最低。
4. 通过 normalizer 的版本去重键（`tenant+type+id+object_version`）可消除 Outbox/Streams 双发重复。

## 3. 端到端架构（Phase 1）

```text
A. Ontology Write Path -> Tx Outbox -------------------------------> object_change_raw
B. Neo4j Streams Plugin -> Kafka(neo4j 变更 topic) -> Streams Mapper -> object_change_raw
C. Reconcile Scanner(updated_at/tombstone) -----------------------> object_change_raw

object_change_raw -> ChangeNormalizer(dedupe/regression check) -> object_change
object_change -> ContextBuilder -> EventFilter -> L1Evaluator -> ActionDispatcher -> Activity/Evaluation Ledger
```

关键点：
- A 提供最完整业务语义（actor/trace/业务上下文）；
- B 补齐“绕过应用写路径”的变更可见性；
- C 保证最终一致性，不追求毫秒级实时。

## 4. Neo4j Community 4.4.48 + Streams + Kafka 落地方案（可执行）

### 4.1 Neo4j 侧配置

在 `neo4j.conf` 启用 Streams 插件能力（以测试中验证过的配置为基线）：

- `dbms.unmanaged_extension_classes=streams.kafka=streams.kafka,streams.events.source=streams.events.source`
- `kafka.bootstrap.servers=<kafka-broker>`
- `streams.source.enabled=true`
- `streams.sink.enabled=true`
- `streams.procedures.enabled=true`

> 以上组合已在仓库集成测试中用于拉起 Neo4j 4.4.48 + Streams 4.1.9。

### 4.2 Kafka topic 约定

建议区分两个 topic：

1. `neo4j_streams_raw`：仅接收 Streams 原始消息；
2. `object_change_raw`：Monitor 统一 raw 入口（Outbox/Streams/Reconcile 汇流）。

使用独立 topic 的好处：
- 保留 Streams 原始证据便于排障；
- mapping/归一化失败不会污染主 raw topic。

### 4.3 Streams 消息映射

由 `Neo4jStreamsEventMapper` 执行映射，输出 `ObjectChangeEvent`：

- `change_source='neo4j_streams'`
- 从 `before/after` 差异计算 `changed_fields` 与 `changed_properties`
- `object_id` 从配置主键字段回填（缺失时回退到 payload/id）
- `source_version/object_version` 优先取 `txSeq/txId`

映射后投递到 `object_change_raw`，再走统一 normalizer。

### 4.4 去重与一致性约束

在 `ChangeNormalizer` 执行：

1. 去重键：`tenant_id + object_type + object_id + object_version`；
2. 短窗口去重：消除 Outbox + Streams 同版本双发；
3. 版本回退检测：`object_version < latest_seen` 时产出 `ReconcileEvent`；
4. 字段归并：同版本重复到达时合并 `changed_properties`，避免信息丢失。

### 4.5 Reconcile 兜底

周期任务扫描：

- `updated_at > watermark` 的对象，补发 upsert raw event；
- 删除场景依赖 tombstone/delete_audit 表补发 delete 事件。

触发条件建议：
- Streams lag 超阈值；
- 检测到版本回退/上下文缺失；
- 人工执行定时补偿窗口。

## 5. CDC Connector（仅保留一阶段说明，非主路径）

Neo4j CDC Connector 在 Phase 1 **不是 Community 4.4.48 主方案**。  
仅在 Enterprise/Aura 且具备 `db.cdc.*` 能力时作为可选副通道评估。  
即便启用，也必须汇入同一 `object_change_raw` 并复用相同 dedupe 键。  
一阶段验收不以 CDC Connector 联通为前置条件。  
当前阶段以 Streams+Kafka 跑通直写覆盖与闭环稳定性为优先。  
后续若升级 Neo4j 版本/许可，再将 CDC Connector 作为替换或增强选项。

## 6. Phase 1 验证清单（按优先级）

1. **单元/组件**：
   - `Neo4jStreamsEventMapper` 字段映射与属性 diff 正确；
   - `ChangeNormalizer` 对双发去重、版本回退分流正确。
2. **链路级**：
   - Outbox 与 Streams 同时输入时不重复触发 action；
   - Streams-only 输入可完成 filter/evaluate/dispatch 闭环。
3. **集成级**：
   - `test_neo4j_streams_user_money_integration.py`（有外部依赖时执行）；
   - 无 Neo4j/Kafka 环境时允许跳过，但保留组件测试必跑。

## 7. 一阶段实施建议（精简）

- 先把 Streams 通道做成可稳定运行的“副通道标准件”；
- 维持 Outbox 为语义主通道，避免因插件波动影响主业务写路径；
- 把“映射 + 去重 + 补偿”作为同一质量域治理（统一指标、统一告警、统一回放工具）；
- 文档与代码导出层统一声明：Community 4.4.48 的推荐顺序为  
  **Outbox > Neo4j Streams > APOC Trigger > Reconcile**。
