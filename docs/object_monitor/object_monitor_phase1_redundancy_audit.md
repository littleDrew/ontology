# Object Monitor 一阶段冗余实现排查与收敛建议

> 目标：基于当前代码实现与 `docs/object_monitor` 下的调研/设计文档，对“Phase 1 是否过度实现”进行一次工程化盘点，给出可执行的收敛清单。

## 1. 排查范围

本次排查覆盖两类输入：

1. 设计文档约束（尤其是一阶段范围）：
   - `object_monitor_design_phase1.md`
   - `object_monitor_design_general.md`
   - `object_monitor_palantir_research.md`
2. 当前代码主干：
   - `ontology/object_monitor/api|compiler|runtime|storage`
   - `tests/object_monitor/*`

## 2. 一阶段“必须/非目标”对照基线

按 `object_monitor_design_phase1.md` 的边界，一阶段核心是：

- 仅 Copy 模式、L1 无状态评估、主对象+一跳关系。
- 命中后仅 Action（HTTP）闭环，具备幂等/重试/DLQ。
- 变更入口统一，但以“稳定闭环”优先，不做过早复杂编排。

同时文档明确非目标包括：

- L2/CEP 持续时长窗口；
- 多 effect DAG/fallback 编排/人工审批节点；
- 非复制模式与自动迁移策略。

## 3. 发现的冗余点（按优先级）

## 3.1 P0（建议立即收敛）

### 3.1.1 运行时接口已提前引入 Phase 2 语义

`runtime/interfaces.py` 当前暴露了 `evaluate_l2`、`execute_notification`、`ReplayService`，并在 `runtime/__init__.py` 对外导出。这些能力在 Phase 1 非目标中明确未纳入交付。

**风险**：
- 对外 API 过宽，团队容易误判“这些能力已经可用”；
- 测试矩阵被动扩张，接口兼容包袱提前形成。

**建议**：
- Phase 1 对外协议收敛为 `evaluate_l1 + execute_action`；
- L2/Replay/Notification 迁移到 `phase2/` 或 `experimental/` 命名空间；
- `__init__.py` 默认导出只保留 Phase 1 能力。

### 3.1.2 L2 占位代码已进入核心类

`runtime/evaluator.py` 在主类 `L1Evaluator` 中直接暴露 `evaluate_l2(...): NotImplementedError`。

**风险**：
- 主执行类混入未来能力，增加阅读与维护噪音；
- 容易在业务代码中误调用，造成线上不可预期报错。

**建议**：
- 将 L2 占位从 `L1Evaluator` 移除，改为独立 `L2Evaluator` 抽象（可空实现）；
- 或保留但转到单独 mixin / experimental 模块，避免主类 API 污染。

### 3.1.3 CDC 映射能力存在双实现并行

当前同时存在：

- `change_pipeline.Neo4jCdcMapper`
- `cdc_connector.Neo4jKafkaCdcEventMapper`

两者都在做 CDC payload -> `ObjectChangeEvent` 的映射。

**风险**：
- 字段语义漂移（同一源事件在不同 mapper 中得到不同 event_id/source_version）；
- 用例覆盖分散，后续修 bug 容易只改一处。

**建议**：
- 一阶段只保留单一 canonical mapper；
- 另一实现退化为 adapter（先标准化 schema，再委托 canonical mapper）；
- 契约测试以同一组 CDC 样例比对映射结果。

## 3.2 P1（建议近期收敛）

### 3.2.1 RawEventBus 默认落内存全量缓存，偏测试化

`DualChannelIngestionPipeline` 默认使用 `InMemoryRawEventBus` 并累计 `events`。

**风险**：
- 生产长跑时内存增长不可控；
- 运行时行为偏测试语义（append-only list），与生产消息系统模型不一致。

**建议**：
- 默认 sink 改为 no-op 或可观测计数器；
- `InMemoryRawEventBus` 仅在测试显式注入。

### 3.2.2 `KafkaCdcIngestor.poll_once` 每次新建 consumer

当前 `poll_once` 内部每次构建并关闭 `KafkaConsumer`。

**风险**：
- 高频轮询时连接开销明显；
- consumer group 再均衡频繁，吞吐与延迟抖动。

**建议**：
- 改为生命周期级 consumer（init 创建，close 销毁）；
- `poll_once` 仅执行 poll + map + commit。

### 3.2.3 发布/存储实现并存较多，阶段内“主实现”不够明确

当前有 in-memory / sqlite / sqlalchemy 三套路径并行。

**风险**：
- 接口变更需要三处同步，降低迭代效率；
- 一阶段交付口径不清（到底哪个是生产推荐）。

**建议**：
- 一阶段明确“1 套生产实现 + 1 套测试实现”；
- 其余实现降级为兼容层，冻结新增字段。

## 3.3 P2（可保留但需显式标记）

### 3.3.1 Rollout gate 属于上线治理增强项

`runtime/rollout.py` 已有较完整门禁逻辑。该能力与灰度门禁相关，方向正确，但不应影响主链路开发优先级。

**建议**：
- 保留，但在文档与导出层标记为“可选运维组件”；
- 不作为 Phase 1 核心功能验收阻塞项。

## 4. 建议的一阶段“收敛后最小闭环”

建议将一阶段主干收敛为以下 8 个必需模块：

1. Definition/Compile/Publish（控制面）
2. Outbox+CDC/Streams 统一归一化 + 去重
3. Context Builder（主对象+一跳）
4. Event Filter（objectType + changed_fields + scope）
5. L1 Evaluator（无状态）
6. Activity/Evaluation Ledger（持久化）
7. Action Dispatcher（幂等 + Retry + DLQ）
8. Reconcile Queue（版本回退与上下文缺失补偿）

其余模块统一进入“Phase 2 预留”标签，不参与一阶段主路径承诺。

## 5. 建议执行顺序（两周收敛版）

### Week A：接口与导出瘦身

- 收缩 runtime 对外导出，仅保留 Phase 1 API；
- 把 L2/Replay/Notification 迁移到 experimental 命名空间；
- 文档增加“Phase 1 可用能力清单”。

### Week B：实现去重与生产语义对齐

- 合并 CDC mapper 为单一 canonical 实现；
- `KafkaCdcIngestor` 改成长生命周期 consumer；
- raw sink 默认 no-op，测试专用内存 sink 显式注入。

## 6. 最终结论

当前仓库的总体方向与 Phase 1 设计文档是一致的：端到端闭环已具备雏形。但确实存在“Phase 2 语义提前渗透、接入层双实现并行、测试语义默认化”三类冗余。

如果目标是“尽快稳定一阶段上线版本”，建议优先做 API/导出收敛 + CDC 映射单一化，这两项收益最高、改动面也最可控。
