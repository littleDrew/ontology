# Reference Digest: 调研与分析资料（链接 + 价值要点）

## 1) 需求澄清与系统设计流程

### The Anatomy Of A System Design Interview
- Link: https://blog.pramp.com/system-design-interview-process-e91aae2dbe83
- Value:
  - 强调先澄清需求和约束，再进入方案设计。
  - 适合用于需求访谈 checklist 的框架搭建。

### How to Succeed in a System Design Interview
- Link: https://blog.pramp.com/how-to-succeed-in-a-system-design-interview-27b35de0df26
- Value:
  - 提供分阶段表达方式，减少“先入为主选技术”。
  - 可作为输出结构（先问题空间、后解空间）的参考。

### System Design Primer: How to approach a system design interview question
- Link: https://github.com/donnemartin/system-design-primer
- Value:
  - 四步法：需求与约束 -> 高层设计 -> 核心组件 -> 扩展与权衡。
  - 对容量估算、瓶颈定位、trade-off 有体系化清单。

---

## 2) 竞品/开源/技术选型调研

### checkcheckzz/system-design-interview (README)
- Link: https://github.com/checkcheckzz/system-design-interview
- Value:
  - 提供大量真实系统案例与延伸链接，可作为竞品/同类系统调研入口。
  - 强调 user cases + constraints + component design 的三段式。

### SourceMaking: Design Patterns & Tips
- Link: https://sourcemaking.com/design-patterns-and-tips
- Value:
  - 对组件级职责划分、模式选型、重构路径有实操价值。
  - 可用于将“高层架构”落地到“模块内部设计”。

### CAP FAQ
- Link: https://github.com/henryr/cap-faq
- Value:
  - 帮助明确一致性与可用性的边界，避免模糊表述。

### Scalable System Design Patterns
- Link: http://horicky.blogspot.com/2010/10/scalable-system-design-patterns.html
- Value:
  - 常见扩展策略与稳定性策略概览，适合候选架构对比时快速校验。

---

## 3) 容量评估与性能推导

### Use back-of-the-envelope calculations
- Link: http://highscalability.com/blog/2011/1/26/google-pro-tip-use-back-of-the-envelope-calculations-to-choo.html
- Value:
  - 快速估算吞吐、存储、带宽，用于方案可行性初筛。

### Latency numbers every programmer should know (via system-design-primer appendix)
- Link: https://github.com/donnemartin/system-design-primer
- Value:
  - 帮助建立组件间时延预算，避免不现实的SLO。

---

## 4) 可靠性与分布式一致性

### Paxos Made Simple
- Link: http://research.microsoft.com/en-us/um/people/lamport/pubs/paxos-simple.pdf
- Value:
  - 在涉及强一致场景时，帮助理解复制与共识代价。

### Intro to Architecting Systems for Scale
- Link: http://lethain.com/introduction-to-architecting-systems-for-scale/
- Value:
  - 适合从单体向分布式扩展阶段的演进参考。

---

## 5) 使用建议（在本skill中的落地方式）
- 需求确认阶段：优先使用第1组资料完善问题定义。
- 调研阶段：按“竞品 -> 开源 -> 技术栈 -> 约束”顺序用第2组资料补证据。
- 推导阶段：使用第3组资料补容量与时延估算。
- 风险阶段：结合第4组资料说明一致性/可用性取舍。

If a referenced link is unavailable, preserve citation metadata and switch to the nearest equivalent source with the same topic coverage.
