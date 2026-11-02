# Near-term roadmap / 近期路线图

[English homepage](../README.md) · [中文首页](../README.zh-CN.md) · [Capabilities / 功能](CAPABILITIES.md) · [功能中文版](CAPABILITIES.zh-CN.md)

Development focuses on **one gameplay greybox → multiple playable art styles**. Priorities below cover workflow reliability, resource processing and distribution. Completed changes are recorded in [release notes](../CHANGELOG.md).

后续围绕**同一玩法灰盒→多风格可玩原型**，完善工作流稳定性、资源处理与分发。[发行说明](../CHANGELOG.md)记录已完成的变化。

| Priority / 优先级 | Work / 工作 | Completion evidence / 完成依据 |
|---|---|---|
| First / 优先 | Make the product understandable / 补齐产品表达 | Bilingual pages expose real gameplay, concrete capabilities, workflow outputs, installation and support scope; actual repository rendering checked. / 双语页面直接展示实际玩法、功能与中间产物、安装和支持范围，并检查仓库实际渲染。 |
| First / 优先 | Finish reproducible distribution / 完成可复现分发 | Source, manifest, CLI version, archive and install commands identify the same package; a clean installation and rollback are exercised. / 源码、清单、CLI、压缩包与安装命令指向同一包，实际执行干净安装和回退。 |
| First / 优先 | Verify actual agent execution / 验证实际 Agent 执行 | A real host completes a small two-style case with asset-route decisions, required intermediate work, native gameplay and accurate completion state; interventions recorded. / 真实宿主完成小规模双风格案例，落实资产选路、中间成果、原生玩法与准确终点，并记录人工介入。 |
| Next / 随后 | Measure useful resource processing / 测量有用的资源处理 | A representative before/after asset retains required appearance and is compared on the same native scene/device/workload; failed or ineffective attempts retained. / 代表资产处理前后保留必要外观，在同原生场景、设备与负载中比较，保留无效与失败尝试。 |
| First / 优先 | Verify feedback and release channels / 验证反馈与发布入口 | Installation, support and private-report routes work for external users; CI and included-content review bind the released revision. / 外部用户可用安装、支持和私密报告入口；CI 与纳入内容审查绑定实际发布版本。 |

Track current scope in [capabilities](CAPABILITIES.md). Production and performance improvements require comparisons on actual projects and target devices.

当前范围见[功能页](CAPABILITIES.zh-CN.md)。生产与性能改进以实际工程和目标设备上的对照结果为依据。
