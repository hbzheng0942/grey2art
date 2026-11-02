# 一手资料与证据边界

资料更新：2026-10-20。以下是能力与设计参考，不是工具普及率排名，也不证明已在此 skill 接入。具体引擎/插件版本必须随用户工程锁定。本表是上游资料来源，具体候选的实测结果以 candidate-status／release-validation 为准，不由本表推定。

| ID | 一手来源 | 本文使用范围 | 地址 |
|---|---|---|---|
| S01 | Epic：PCG Overview | 属性化空间数据、参数、实例/子图、调试；据此建议可复用构建图 | `https://dev.epicgames.com/documentation/en-us/unreal-engine/procedural-content-generation-overview` |
| S02 | Epic：PCG Generation Modes | 分区/分层生成；区分生产粒度与运行时流式粒度 | `https://dev.epicgames.com/documentation/en-us/unreal-engine/using-pcg-generation-modes-in-unreal-engine` |
| S03 | Epic：Landscape Edit Layers | 无损层、锁定、可见性、样条/patch；据此建议保留生成层与直接修整层 | `https://dev.epicgames.com/documentation/en-us/unreal-engine/landscape-edit-layers-in-unreal-engine` |
| S04 | SideFX：TOP Network Cooking | dirty/局部 recook/命令行构建；不当作美术批准或账单保证 | `https://www.sidefx.com/docs/houdini/tops/cooking.html` |
| S05 | SideFX：Local Scheduler | 资源槽、并行、输出检查、日志和失败策略 | `https://www.sidefx.com/docs/houdini/nodes/top/localscheduler.html` |
| S06 | Unity：Terrain Tools 5.1.2 文档 | 侵蚀、雕刻、mask、tile、heightmap/splatmap；并不宣称这是用户应升级到的最新版本 | `https://docs.unity3d.com/Packages/com.unity.terrain-tools@5.1/manual/index.html` |
| S07 | SideFX：Heightfields/Terrains | height/mask层、投影、地貌工具与高度场表示边界 | `https://www.sidefx.com/docs/houdini/heightfields/index.html` |
| S08 | SideFX：HeightField Erode | 水力/热力侵蚀、特征尺度、冻结输出、辅助 masks | `https://www.sidefx.com/docs/houdini/nodes/sop/heightfield_erode.html` |
| S09 | MapMagic 2 作者在 Unity Asset Store 的产品页 | 节点式地形工具候选；具体附加模块不推定可用 | `https://assetstore.unity.com/packages/tools/terrain/mapmagic-2-165180` |
| S10 | Terrain3D 官方文档 | Godot 原生可编辑地形、导入/实例/碰撞相关接口入口 | `https://terrain3d.readthedocs.io/en/stable/` |
| S11 | Voxel Tools 官方文档 | Godot 体积地形候选 | `https://voxel-tools.readthedocs.io/en/latest/` |
| S12 | Gaea 官方文档入口 | 图节点、生产与自动化资料候选；未核验具体收费/CLI能力 | `https://docs.gaea.app/` |
| S13 | World Machine 官方站 | 地貌/侵蚀/河流/masks、图与宏、分块导出参考；不沿用旧的仅高度场/仅Windows假设 | `https://www.world-machine.com/` |
| S14 | Pillow Castle 在 Steam 的 Superliminal 页面 | 第一人称、强制透视和视觉错觉；据此推导应保护感知契约 | `https://store.steampowered.com/app/1049410/Superliminal/` |
| S15 | Cities: Skylines II 官方发行商商店页 | 城建/模拟类别定位；不把静态城市场景当城市模拟器 | `https://store.steampowered.com/app/949230/Cities_Skylines_II/` |

## R3 供应商、宿主与交换格式资料

以下链接描述上游接口／产品，不证明本包已实现或验证对应适配器。价格、权限、模型版本和限制会变化；计价优先从官方目录／API 手册本地计算并保留来源和日期；不要求先查询价格 API 或试生成。必要时核对具体账号、动态价格或厂商要求的 quote ID。供应商的“优势／弱项”应落到版本、资产任务和证据，不能从宣传页面推定综合质量排名。

| ID | 一手来源 | 使用范围 | 地址 |
|---|---|---|---|
| R01 | WorkBuddy Skill 规范 | 技能打包与宿主适配入口；不是本包端到端验证 | https://open.workbuddy.cn/docs/skill |
| R02 | WorkBuddy Connector 规范 | MCP／CLI 连接器契约，实际能力仍需预检 | https://open.workbuddy.cn/docs/connector |
| R03 | WorkBuddy Expert Team | 宿主协作能力入口；无此能力时顺序执行 | https://open.workbuddy.cn/docs/expert-team |
| R04 | Meshy API 文档 | 计费、异步任务与操作范围；API 与网页产品不能混算 | https://docs.meshy.ai/en/api/pricing |
| R05 | Meshy 官方 MCP | 可复用的上游连接器，需安装／账号／精确工具验证 | https://www.meshy.ai/mcp |
| R06 | Tripo Developer 平台 | 模型、操作与任务生命周期入口 | https://developers.tripo3d.ai/en/docs |
| R07 | Tripo API Pricing | API 价格目录；不是本包固定报价或质量承诺 | https://developers.tripo3d.ai/en/pricing |
| R08 | Hyper3D/Rodin API 文档 | API v2、任务／作业身份和输出语义入口 | https://docs.hyper3d.ai/en |
| R09 | Hi3D/Hitem3D 官方价格页 | 产品身份与定价入口；需确认实际 API 产品和账号 | https://www.hitem3d.ai/pricing |
| R10 | Adobe Mixamo FAQ 与工作流 | 网页绑骨／动画与角色限制；不据此声称有公共 API | https://helpx.adobe.com/creative-cloud/faq/mixamo-faq.html |
| R11 | Adobe Mixamo 上传／绑骨说明 | 可选 human/assisted 节点的输入和操作依据 | https://helpx.adobe.com/creative-cloud/help/mixamo-rigging-animation.html |
| R12 | Blender Modifiers | 几何后端适用操作；效率收益需任务实测 | https://docs.blender.org/manual/en/4.5/modeling/modifiers/introduction.html |
| R13 | Blender CLI | 可重复批处理入口，具体版本和脚本需锁定 | https://docs.blender.org/manual/en/4.1/advanced/command_line/arguments.html |
| R14 | Godot 3D formats | `.blend` 经 Blender/glTF 导入，不是无损原生互通 | https://docs.godotengine.org/en/stable/tutorials/assets_pipeline/importing_3d_scenes/available_formats.html |
| R15 | Unity 3D formats | DCC 依赖与 FBX 转换边界 | https://docs.unity3d.com/6000.0/Documentation/Manual/3D-formats.html |
| R16 | Unity ProBuilder | 引擎内建模／灰盒工具候选 | https://docs.unity3d.com/Packages/com.unity.probuilder@6.0/manual/index.html |
| R17 | Unity glTFast | Editor／runtime 导入能力；不等于完整引擎适配 | https://docs.unity3d.com/Packages/com.unity.cloud.gltfast@6.14/manual/index.html |
| R18 | Unity 6 支持与 URP 模板 | 新适配项目选 6.3 LTS／URP；实际补丁由安装时锁定 | https://unity.com/releases/unity-6/support |
| R19 | Three.js GLTFLoader | Web runtime 加载入口；不证明物理／玩法链 | https://threejs.org/docs/pages/GLTFLoader |
| R20 | Khronos glTF 2.0 规范 | 单位、坐标、节点和扩展／extras 交换约定 | https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html |

补充检索中 Gaia、MicroVerse 的部分官方地址未成功读取；没有将其具体功能或自动化支持作为此轮结论依据。Blender／受控 DCC 作为可选几何后端的具体地形生产器，仍需各自实现和测试；上游具备功能不代表本候选已接入。

## 用户材料

- 上传 `greybox-art-prototype-0.1.0-internal-alpha.zip`：此次直接检查 SKILL、quickstart、CLI 与 core，用于解释流程入口差异。
- `art-vnext-paper-pilot.md`：方向创作、首样、迁移、用户纠偏、费用/耗时边界。
- `paper-atlas-seven-node-structure.md`：空间语言、概念特征→单元、共享边界、原机位与未验证假设。
- `paper-atlas-scene-composition-revision.md`：接口小样不等于完整场景、单体面数不能代替空间组织。
- `paper-atlas-assembly-plan.md`：六生产包、组装依赖、代理内部收敛与用户授权范围。
- 上一轮 REVIEW/EVIDENCE：用于列出原问题；本候选另附离线测试，不重复声称原生复跑。
