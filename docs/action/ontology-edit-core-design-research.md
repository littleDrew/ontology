# Ontology Edit 设计（Palantir 对齐版，聚焦实现）

## 0. 关键结论

1. Ontology Edit 必须拆为两阶段：**Capture（函数内收集变更）** 与 **Apply（Action 触发提交）**。  
2. 按 Palantir 语义，**函数本身不是直接写库入口**；要通过 function-backed action 才会应用 edits。  
3. Python 侧实现建议：**Builder/Command 为主、Proxy 为辅（语法糖）**，统一产出 `EditPlan` 后由 Runtime 校验并提交。

---

## 1. Palantir 文档关键语义（结合你给的重点）

## 1.1 When edits are applied

- 函数里收集的是 `OntologyEdit`（变更意图）。
- 真正更新对象，需通过配置 Action 使用该函数（function-backed action）来触发 apply。
- 因此系统必须有清晰边界：
  - Function Runtime：只负责生成 edits；
  - Action Runtime：负责权限/条件校验 + 提交。

## 1.2 Edits and object search（重要 caveat）

Palantir 示例表明：
- 在同一次函数执行中，修改 `editable_employee.name = "Bob"` 后，立刻走对象搜索统计 `name == "Bob"`，结果仍可能为 0。
- 即：**函数内搜索读取通常看不到尚未应用的 edits**（读写可见性不是“读己之写”）。

对我们系统的约束：
- 函数执行期读取默认是提交前快照；
- 文档与 API 返回要明确“函数内可见状态”与“提交后状态”不同。

## 1.3 Python Ontology edits container 语义

- 通过 `FoundryClient().ontology.edits()` 构造 edits 容器。
- 对象默认只读；要先 `.edit(...)` 获得可编辑视图。
- 数组属性要“复制 -> 修改副本 -> 整体回写”，不能原地修改。
- 已有对象主键不可更新。
- 链接更新用显式方法（`set/clear/add/remove`）。
- 支持 `create()` 与 `delete()`，且可用对象实例或主键。

---

## 2. Python SDK 五类 TransactionEdit properties（来自官方 markdown）

### ModifyObjectEdit

| Name | Type | Required | Description |
|---|---|---|---|
| `object_type` | `ObjectTypeApiName` | Yes |  |
| `primary_key` | `PropertyValue` | Yes |  |
| `properties` | `Dict[PropertyApiName, Optional[DataValue]]` | Yes |  |
| `type` | `Literal["modifyObject"]` | Yes | None |

### DeleteObjectEdit

| Name | Type | Required | Description |
|---|---|---|---|
| `object_type` | `ObjectTypeApiName` | Yes |  |
| `primary_key` | `PropertyValue` | Yes |  |
| `type` | `Literal["deleteObject"]` | Yes | None |

### AddObjectEdit

| Name | Type | Required | Description |
|---|---|---|---|
| `object_type` | `ObjectTypeApiName` | Yes |  |
| `properties` | `Dict[PropertyApiName, Optional[DataValue]]` | Yes |  |
| `type` | `Literal["addObject"]` | Yes | None |

### DeleteLinkEdit

| Name | Type | Required | Description |
|---|---|---|---|
| `object_type` | `ObjectTypeApiName` | Yes |  |
| `primary_key` | `PrimaryKeyValue` | Yes |  |
| `link_type` | `LinkTypeApiName` | Yes |  |
| `linked_object_primary_key` | `PrimaryKeyValue` | Yes |  |
| `type` | `Literal["removeLink"]` | Yes | None |

### AddLinkEdit

| Name | Type | Required | Description |
|---|---|---|---|
| `object_type` | `ObjectTypeApiName` | Yes |  |
| `primary_key` | `PrimaryKeyValue` | Yes |  |
| `link_type` | `LinkTypeApiName` | Yes |  |
| `linked_object_primary_key` | `PrimaryKeyValue` | Yes |  |
| `type` | `Literal["addLink"]` | Yes | None |

---

## 3. 仅靠对象 Proxy 是否足够？

结论：**不够，不能单独作为核心捕获机制**。

- `modifyObject`：Proxy 对属性赋值拦截很合适。
- `addObject`：是“创建命令”，不是既有对象字段变化，Proxy 不自然。
- `deleteObject`：是“删除命令”，需要显式安全控制与审计原因。
- `addLink/removeLink`：涉及双端主键与链接类型，单对象属性代理难完整表达。

推荐模式：
- 核心链路：显式 `Builder/Command` 产出结构化 edits；
- 体验增强：可提供 Proxy API，但最终都降级为 Builder 命令。

---

## 4. 我们系统如何支持 Ontology Edit（实现方案）

## 4.1 可编辑对象/元素白名单（EditableSpec）

每个对象类型维护：
- `editable_properties`
- `editable_links`
- `creatable` / `deletable`
- `constraints`（枚举、范围、主键不可改等）
- `required_permissions`

建议先支持：主对象 + 一跳关联对象。

## 4.2 统一中间模型

```python
@dataclass(frozen=True)
class EditOp:
    op: Literal["addObject", "modifyObject", "deleteObject", "addLink", "removeLink"]
    object_type: str
    primary_key: dict | str | None = None
    properties: dict | None = None
    link_type: str | None = None
    linked_object_primary_key: dict | str | None = None

@dataclass(frozen=True)
class EditPlan:
    action_type: str
    invocation_id: str
    idempotency_key: str
    edits: list[EditOp]
```

## 4.3 Capture 层实现形态（吸收可取方案）

建议采用 **Unit of Work + Dynamic Proxy**，但保持“Proxy 只做捕获，最终落到显式 EditOp”：

- `OntologyEdits`（UoW 容器）
  - 维护会话内新增/修改/删除/链接变更。
  - `get_edits()` 统一输出 `EditPlan.edits`。
- `EditableProxy`
  - 拦截属性赋值，维护 shadow state（同函数内写后读一致）。
  - 将变更记入容器，不直接提交。
- `LinkManager`
  - 拦截 `add/remove/set/clear`，生成 `addLink/removeLink` 指令。

关键约束：
- Proxy 只用于 `modifyObject` 体验增强；
- `addObject/deleteObject` 仍通过容器显式命令 API；
- 最终都归一为 `EditOp`，避免双轨语义。

## 4.4 五类 Edit 的触发点与捕获映射

| Edit 类型 | 触发 API / 动作 | 捕获层拦截点 | 记录内容（归一化） |
|---|---|---|---|
| `addObject` | `edits.objects.Type.create(pk, ...)` | `OntologyEdits.create` | `op=addObject, object_type, primary_key, properties` |
| `modifyObject` | `editable_obj.prop = val` | `EditableProxy.__setattr__` | `op=modifyObject, object_type, primary_key, properties(delta)` |
| `deleteObject` | `edits.objects.Type.delete(obj/pk)` | `OntologyEdits.delete` | `op=deleteObject, object_type, primary_key` |
| `addLink` | `editable_obj.link.add(target)` | `LinkManager.add` | `op=addLink, object_type, primary_key, link_type, linked_object_primary_key` |
| `removeLink` | `editable_obj.link.remove(target)` | `LinkManager.remove` | `op=removeLink, object_type, primary_key, link_type, linked_object_primary_key` |

## 4.5 get_edits() 前清洗（commit 前必做）

`OntologyEdits.get_edits()` 在返回前执行：

1. **抵消规则**：同会话 `create` 后又 `delete` -> 两者都移除。  
2. **合并规则**：同对象多次 `modify` -> 合并为一条，字段取最后写入值。  
3. **链接去重**：重复 `add/remove` 去重，互斥操作按顺序折叠。  
4. **格式化**：输出严格匹配 `TransactionEdit` 结构。

## 4.6 Runtime 主流程（必须）

1. 解析 ActionType 与 Function 版本。  
2. 校验 submission criteria 与权限。  
3. 执行函数，获得 `EditPlan`。  
4. 按 `EditableSpec` 校验字段/链接/主键规则。  
5. 做冲突校验（版本或快照令牌）。  
6. 单事务 apply（全部成功或回滚）。  
7. 写执行日志（edits 摘要 + 结果）。

## 4.7 API 最小集合

- `POST /actions/{actionType}/apply`
- `POST /actions/{actionType}/validate`
- `GET /actions/executions/{executionId}`

---

## 5. “User edits always win” 对系统设计的影响

你给的时序表说明：同一主键对象即使在数据源行消失后重现，历史用户编辑仍会重新生效（用户编辑优先）。

对我们系统的实现要求：
1. 用户 edit 与数据源基线分层存储（不要覆盖同一层）。
2. 物化时定义确定性的合并规则（默认 user edits 覆盖 datasource）。
3. 删除/重现场景要保留 edit 历史并可重放。
4. 审计记录需能解释“为什么当前值不是数据源最新值”。
