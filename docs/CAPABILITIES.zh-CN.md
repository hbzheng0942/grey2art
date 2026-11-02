# 功能、工具与实测范围

[English](CAPABILITIES.md) · [简体中文](CAPABILITIES.zh-CN.md) · [首页](../README.zh-CN.md) · [安装](INSTALL.zh-CN.md)

**Grey2Art 从同一玩法灰盒，批量制作多种美术风格的可玩原型。** 从现有工程出发，选定交付风格，先完成优先风格的完整可玩样段，再扩展其余风格；产物保留在可编辑的原生工程中。

下表列出制作路线、工具入口和实测范围。[版本记录](../CHANGELOG.md)

## 可以制作什么

| 任务 | 实际产物 | 方法与当前边界 |
|---|---|---|
| 从玩法需求或参考搭灰盒 | 小型原生可玩关卡、可编辑玩法代码与检查记录 | [灰盒创作](../skills/greybox-to-multistyle-art/references/greybox-authoring.md)。先实现明确的核心循环；截图未展示的规则与尺寸保留待确认。可继续进入单风格或多风格美术。 |
| 探索多个美术世界 | 编号概念候选、选定风格和优先风格 | [概念方法](../skills/greybox-to-multistyle-art/references/concept-authoring.md)。实际图片需要审阅；探索方向数与最终交付风格数分别决定。 |
| 把选定概念变成制作方案 | 关键视图、空间设计、资产职责、接口和早期原生整景预演 | [空间设计](../skills/greybox-to-multistyle-art/references/spatial-contract.md)与[整景比较](../skills/greybox-to-multistyle-art/references/scene-comparison.md)。概念图本身不证明精确几何或场景可运行。 |
| 准备与制作资产 | 独立参考图、必要多视图、生成／复用／制作的模型和装配方案 | [参考图方法](../skills/greybox-to-multistyle-art/references/modeling-references.md)与[生产方法](../skills/greybox-to-multistyle-art/references/hybrid-production.md)。新 AI 网格使用批准的实际图片；每项主要视觉特征选择适合的制作路线。 |
| 装配多个可玩美术版本 | 各风格原生场景与资源、实际截图、相关玩法检查 | [引擎适配](../skills/greybox-to-multistyle-art/references/engine-adapters.md)。Godot、Unity 有原生路线；完整美术、玩法和性能接受仍需按任务验证。 |
| 修改已有结果 | 局部源码改动、可比较画面和受影响交互检查 | [视觉诊断](../skills/greybox-to-multistyle-art/references/visual-harness.md)与[场景效果](../skills/greybox-to-multistyle-art/references/scene-effects.md)。局部修改可沿用已接受方向。 |
| 接续中断的任务 | 当前焦点、原参考与供应商任务、剩余工作 | [任务接续](../skills/greybox-to-multistyle-art/references/continuity.md)。先核对未知提交，再考虑重试；升级不会改写历史接受。 |

灰盒创建／修改、可编辑 Blender 空间是其他适配入口，可在请求的原生基线或 `.blend` 终点停止，不自动开始多风格生产。见[原生创作](../skills/greybox-to-multistyle-art/references/greybox-authoring.md)。

## 选择宿主与原生终点

| 范围 | 可用操作 | 配置 |
|---|---|---|
| Codex、Claude Code、WorkBuddy | 共用 Python CLI，可选包装器／连接器 | 本地命令执行与合适的图像工具。[宿主配置](../skills/greybox-to-multistyle-art/references/hosts-v04.md) |
| Godot | 原生检查、美术装配、捕获、玩法检查与导出 | 使用工程已有的 Godot 安装与版本。 |
| Unity | Editor／PlayMode 装配、材质效果、捕获、玩法 hook 与 Player 导出 | 使用工程已有的 Editor 和渲染管线。[Unity 路线](../skills/greybox-to-multistyle-art/references/unity-runtime.md) |
| Blender | 可编辑空间创作／审阅、静态 GLB 处理、烘焙、散布与渲染 | 按选定操作准备；通用重拓扑、UV 修复、LOD、绑骨和动画清理使用合适的独立工具或供应商。[Blender 操作](../skills/greybox-to-multistyle-art/references/blender-backend.md) |

沿用工程已有的引擎与版本，在目标设备的实际运行包中检查画面、交互与性能。

## 功能工具入口

这些入口接入现有流程，不增加安装要求。`$SKILL` 是安装器返回的真实路径；采用 setup 返回的 Python 命令前缀。

| 需要做什么 | 入口 | 使用结果前检查什么 |
|---|---|---|
| 检查或比较 GLB 资源 | `scripts/asset_metrics.py inspect`／`compare`；[资产检查](../skills/greybox-to-multistyle-art/references/asset-optimization.md#measure-the-supplied-glb-locally) | 测量拓扑、定义／实例与图片编码字节；压缩、稀疏和外部几何有明确限制，不测 draw calls、显存或帧率。 |
| 减面或修复必要资产 | [处理路线](../skills/greybox-to-multistyle-art/references/asset-optimization.md#choose-an-existing-processing-route)：Lux／Meshy／Tripo remesh，或适合的原生 DCC 操作 | 没有打包的本地减面器。保留源文件，比较轮廓、材质并复查原生场景；面数下降本身不证明优化有用。 |
| 检查角色并选择骨架／动作工作 | `scripts/character_check.py inspect`；[角色路线](../skills/greybox-to-multistyle-art/references/character-pipeline.md) | 结构检查不判断解剖或变形。检查实际模型、供应商限制、首个动作及所需终点中的接触表现。 |
| 装配、捕获或检查原生结果 | `scripts/greybox.py engine`；[引擎方法](../skills/greybox-to-multistyle-art/references/engine-adapters.md)与[场景效果](../skills/greybox-to-multistyle-art/references/scene-effects.md) | 使用对应引擎的计划／配置和任务输出；命令成功或取得截图，不等于完整玩法、美术或性能接受。 |
| 恢复任务或缺失下载 | `scripts/progress.py focus`、`scripts/greybox.py task-context inspect`，或[原产物恢复](../skills/greybox-to-multistyle-art/references/suppliers.md#restore-a-completed-local-artifact) | 按真实账本类型和原任务／账户身份接续；不能为了补下载重新生成替代品。 |

例如，本地检查一个资产：

```sh
python3 "$SKILL/scripts/asset_metrics.py" inspect --input "$SOURCE_GLB" --output "$CASE/metrics/source.json"
```

采用新的报告路径，输入保持原样。处理前先读对应方法，确认支持输入、输出处理、失败恢复与原生检查。

## 供应商、图像与费用

- 概念／参考图可使用合适的宿主原生生图工具，或配置一个[图像服务](../skills/greybox-to-multistyle-art/references/image-services.md)。生成、读取像素和展示结果分别验证。
- 打包实现包含 Lux，以及 Meshy、Tripo、Rodin、Hi3D 专用路线，并支持已审阅的自定义命令适配器。专用 API 契约有离线测试；账户就绪、各操作的有用结果与原生接入分别需要证据。[供应商路线](../skills/greybox-to-multistyle-art/references/suppliers.md)
- 新 Lux 生模默认 **G1 标准版**，显式使用 `version: "G1"`，不带 Turbo 专用 `enablePbr`。只有当前任务明确要求时才选 G1-Turbo。已有 Turbo 资产保留来源并可继续复用；减面、材质转移、绑骨和动作沿用各自独立操作／版本合同。
- 只配置当前操作。付费前的具体计划列明参考、供应商／模型／版本、参数、后处理和费用依据；配置与余额不授予生产权限。报价、估算和实际扣费分别记录，未知费用保持未知。

[安装与账户配置](INSTALL.zh-CN.md) · [支持](SUPPORT.md) · [近期路线图](ROADMAP.md)
