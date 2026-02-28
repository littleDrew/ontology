# Research Map (curated from requested sources)

## 1) SourceMaking: design patterns and refactoring index
Primary page: https://sourcemaking.com/design-patterns-and-tips

Use for:
- Component-level object design
- Collaboration and responsibility partitioning
- Refactoring path from naive implementation to maintainable architecture

High-value pattern families:
- Creational: Abstract Factory, Builder, Factory Method, Prototype, Singleton
- Structural: Adapter, Bridge, Composite, Decorator, Facade, Proxy
- Behavioral: Chain of Responsibility, Command, Iterator, Mediator, Observer, State, Strategy, Template Method

High-value refactoring families:
- Composing methods (Extract Method, Replace Temp with Query)
- Moving features between objects (Extract Class, Move Method/Field)
- Organizing data (Encapsulate Field, Replace Type Code)
- Simplifying conditionals (Guard Clauses, Replace Conditional with Polymorphism)

Practical use rule:
- During Step 4 derivation, map each high-risk module to one pattern choice + one refactoring fallback.

---

## 2) checkcheckzz/system-design-interview
Primary README: https://github.com/checkcheckzz/system-design-interview

Core methodology extracted from “System Design Interview Tips”:
1. Clarify constraints and user cases
2. High-level architecture design
3. Component/API/schema level detail

Representative linked readings from README (for rapid grounding):
- The Anatomy Of A System Design Interview: https://blog.pramp.com/system-design-interview-process-e91aae2dbe83
- How to Succeed in a System Design Interview: https://blog.pramp.com/how-to-succeed-in-a-system-design-interview-27b35de0df26
- How to Rock a Systems Design Interview: https://www.palantir.com/2011/10/how-to-rock-a-systems-design-interview/
- Scalability for Dummies: http://www.lecloud.net/tagged/scalability
- Scalable System Design Patterns: http://horicky.blogspot.com/2010/10/scalable-system-design-patterns.html
- Intro to Architecting Systems for Scale: http://lethain.com/introduction-to-architecting-systems-for-scale/
- CAP FAQ: https://github.com/henryr/cap-faq
- Paxos Made Simple: http://research.microsoft.com/en-us/um/people/lamport/pubs/paxos-simple.pdf

Practical use rule:
- Reuse this 3-step spine for meeting facilitation and requirement elicitation.

---

## 3) donnemartin/system-design-primer
Primary README: https://github.com/donnemartin/system-design-primer

Core methodology extracted from “How to approach a system design interview question”:
1. Outline use cases, constraints, assumptions
2. Create high-level design
3. Design core components
4. Scale the design + discuss trade-offs

High-value linked references in this section:
- System design template: https://leetcode.com/discuss/career/229177/My-System-Design-Template
- Back-of-envelope article: http://highscalability.com/blog/2011/1/26/google-pro-tip-use-back-of-the-envelope-calculations-to-choo.html
- Intro to Architecture and Systems Design Interviews: https://www.youtube.com/watch?v=ZgdS0EUmn70

Foundational topic clusters from primer index:
- Performance vs scalability; latency vs throughput
- CAP, consistency patterns, availability patterns
- DNS/CDN/load balancer/reverse proxy/application layer
- Database (replication/federation/sharding/denormalization, SQL vs NoSQL)
- Cache strategies (cache-aside, write-through, write-behind, refresh-ahead)
- Asynchronism (queues, back pressure)
- Communication (HTTP/TCP/UDP/RPC/REST)
- Security and reliability trade-offs

Practical use rule:
- Use primer clusters as a checklist to prevent blind spots in final方案.
