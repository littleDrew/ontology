# Object Monitor Phase 1 服务拉起与 REST 端到端联调

新增了三个可独立启动的 FastAPI 服务，分别对应阶段 1 设计中的三个进程边界：

1. **Ontology Main Server（Control Plane + Action API）**
   - 启动命令：`python -m ontology.servers.main_server --port 8765`
   - 提供：
     - Monitor 控制面：`/api/v1/monitors/*`
     - Action 创建：`POST /api/v1/actions`
     - Action 执行：`POST /api/v1/actions/{action_id}/apply`

2. **Object Monitor Data Plane Server**
   - 启动命令：`python -m ontology.servers.object_monitor_server --port 8771 --action-base-url http://127.0.0.1:8765`
   - 提供：
     - 加载生效 Artifact：`POST /api/v1/data-plane/reload-artifacts`
     - 处理对象变更事件：`POST /api/v1/data-plane/events/object-change`
     - 运行结果查询：`GET /api/v1/data-plane/evaluations`、`GET /api/v1/data-plane/activities`

3. **Neo4j & Change Capture Server（简化）**
   - 启动命令：`python -m ontology.servers.change_capture_server --port 8770 --data-plane-base-url http://127.0.0.1:8771`
   - 提供：
     - Streams 事件归一化并转发：`POST /api/v1/change-capture/neo4j/streams`

## 一键拉起（本地）

```bash
bash scripts/object_monitor/start_server.sh
```

## 推荐联调顺序

1. 在 Main Server 创建并发布 Monitor。
2. 从 `GET /api/v1/monitors/active-artifacts` 获取运行时 Artifact。
3. 调用 Data Plane 的 `reload-artifacts` 装载规则。
4. 向 Change Capture 或 Data Plane 直接发送对象变更事件。
5. 通过 Data Plane `activities/evaluations` 校验命中和动作执行状态。


## 目录组织（Phase 1 结构重组）

当前 `object_monitor` 目录已按 `define` 与 `runtime` 进行第一阶段结构重组：

- `ontology/object_monitor/define/api/*`：Monitor 定义/发布控制面接口与服务
- `ontology/object_monitor/define/storage/*`：Definition 侧仓储抽象与实现导出
- `ontology/object_monitor/runtime/api/*`：Data Plane / Change Capture 的 FastAPI 入口
- `ontology/object_monitor/runtime/storage/*`：Runtime 侧 evaluation/activity 仓储导出
- `ontology/object_monitor/runtime/capture/*`：Runtime 内部 capture 能力（pipeline/normalizer/reconcile 与 source 适配）

当前为首版本开发态：**不保留兼容转发层**，统一按真实路径导入。


## 当前边界收口（开发态）

- Runtime 代码统一依赖 `ontology/object_monitor/runtime/*`，其中存储在 `runtime/storage/*`。
- Define 代码统一依赖 `ontology/object_monitor/define/*`，其中发布仓储在 `define/storage/*`。
- 共享 ORM 模型统一在 `ontology/object_monitor/persistence/sql_models.py`。
- legacy `ontology/object_monitor/storage/*` 已移除。


## 开发态导入约束

- Define：`ontology.object_monitor.define.*`
- Runtime：`ontology.object_monitor.runtime.*`
- Runtime capture 统一落在：
  - `ontology/object_monitor/runtime/capture/*`
  - `ontology/object_monitor/runtime/capture/sources/*`
- 开发态请勿再使用旧路径（如 `ontology.object_monitor.api.*`、`ontology.object_monitor.compiler.*`、`ontology.object_monitor.data_plane_app`、`ontology.object_monitor.storage.*`、`ontology.object_monitor.shared.*`）。
