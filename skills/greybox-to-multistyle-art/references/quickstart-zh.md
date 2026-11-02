# 从一个玩法灰盒开始多风格制作

[English](quickstart-en.md) · [宿主安装与配置](hosts-v04.md) · [当前范围与限制](candidate-status.md)

核心任务是：**从同一玩法灰盒，批量换皮多种美术风格的可玩原型。** 保留玩法和所有选定风格，先验证优先风格的完整样段，再扩展其他风格。

## 1. 安装完整 Skill

从仓库首页取得固定版本的完整目录或版本包。需要 Python 3.10+；macOS/Linux 用 `python3`，Windows 用 `py -3` 或实际 Python 路径。在解压后的 **Skill 目录**执行：

```sh
python3 scripts/install.py --host auto --replace
```

Windows 将前缀替换为 `py -3`。宿主识别有歧义时加 `--host codex`、`--host claude-code` 或 `--host workbuddy`；自定义发现目录用 `--skills-dir PATH`。安装器验证 manifest、复用相同文件、保留旧版回退，并返回实际安装路径。宿主需要时刷新 Skill 列表；只下载 `SKILL.md` 不能运行完整流程。升级与回退见[宿主配置](hosts-v04.md#install-once-preserve-the-selected-version)。

## 2. 给 agent 一个明确任务

```text
使用 greybox-to-multistyle-art，把下面同一个可玩灰盒制作成两种美术风格的可玩原型。
工程位置：<实际工程路径>
目标风格：<指定风格，或请 agent 提出方向>
目标设备：<桌面/Web/其他实际目标>
保留：现有玩法、控制、碰撞和核心空间关系。
先检查工程与现有记录，再给出多风格方案和优先完整样段。
具体资产生产前展示参考、参数和费用；保留全部选定风格的交付目标。
```

这段提示可改成三种或更多风格；明确单风格任务按用户范围执行。**概念探索方向数与最终制作风格数是两件事**：默认探索为 8–10 个方向，用户可指定数量；已给定方向或局部修订不重新跑一轮探索。Agent 在执行前说明适用的出图工作量和费用范围，不把“两种交付风格”解释为固定的探索调用量。

## 3. Agent 检查当前环境

Agent 读取 `SKILL.md`、工程说明和 PLAN/PROGRESS/FOCUS，复用已有安装与工程。已有可玩灰盒直接进入美术；不能因为缺少新格式 manifest 就重建玩法。

以安装返回的实际 `$SKILL` 目录为准：

```sh
python3 "$SKILL/scripts/greybox.py" host setup --host auto --scope art --project "$PROJECT"
python3 "$SKILL/scripts/greybox.py" knowledge next --stage intake
```

setup 返回真实项目根、所选 Python/命令前缀、就绪情况和缺项；后续采用该前缀。当前会话的工具绑定只记录已知事实，未知模型/工具 schema 不需要用户编造。已有能力报告和当前会话 ID 按需传入，见[宿主配置](hosts-v04.md)。

仅准备本次需要的依赖：有可用原生生图工具就复用，不额外配置图像服务；无合适工具才配置所选[图像服务](image-services.md)。实际裁图需要 Pillow；若当前环境缺少它，运行下面命令只准备可复用的私有图像处理环境，再采用返回的 Python 前缀。它不要求图像 profile 或 API 凭据，也不提交生图：

```sh
python3 "$SKILL/scripts/greybox.py" host setup --host auto --scope runtime --runtime image
```

需要资产生成才配置所选供应商；需要对应处理才准备 Blender。原生引擎沿用工程版本。配置、检查和余额不构成付费生产授权；第一次已获授权的实际调用可提供宿主执行证据，无需额外购买能力探针。

## 4. 按同一条主线推进

1. **玩法基线**：查看真实入口、镜头、控制、空间和对象绑定；记录保护范围。结构化入口示例是 [art intake](../schemas/intake-art-request-template.json)，将 source_ref 替换为真实用户请求；风格数量记录在 overview/plan，不添加 intake 不接受的字段。
2. **选择多风格**：按[概念方法](concept-authoring.md)查看真实产物，由用户选择交付风格和优先风格（H1）。
3. **设计与生产准备**：按[空间方法](spatial-contract.md)与[组合方法](hybrid-production.md)确定主要形态、功能物件、环境、材质光影及接口；低成本原生预演后，确认设计（H2）、完整首样参考/资产/参数/费用（H3）。两项可合并展示，已确认同范围不重问。
4. **优先风格完整样段**：新原生建模参考任务使用 `boards start`；WorkBuddy 使用 `boards workbuddy start`；配置型图像服务保留其 prepared-request 路线。具体参数与逐图审查遵循[参考方法](modeling-references.md)。新 AI 网格必须使用批准的实际参考图。
5. **批量扩展与交付**：优先样段完成原生玩法和整景检查并获 H4 接受后，释放其他所选风格。依赖和账户容量决定并行度；局部失败保留成功成果与原任务。全部承诺风格完成后呈现准确版本、剩余缺陷与 H5 交付对象。

每个阶段只读取 `knowledge next` 返回的当前方法。用户检查实际方向、设计、生产方案、完整样段和最终交付，普通命令、查询和同范围返修不增加确认。

## 5. 找到结果并处理失败

Agent 在 PLAN/FOCUS 中给出实际 case、共享资源、各风格原生入口、最新画面和下一动作。工作区通常位于 `art/<case>/shared/` 与 `art/<case>/styles/<style>/`，实际资源根按引擎映射；见[项目布局](project-layout.md)。完成标准是各选定风格能在约定原生目标中运行并保留玩法，图片或模型下载成功不是完整交付。

失败时保留当前版本和原账本，提供版本/manifest、宿主/引擎、阶段、报错和小范围脱敏证据。按[连续任务恢复](continuity.md)继续原任务；未知提交先核对原 ID，不能新建任务重发。只重新验证改动影响的结果，不复制整工程或静默换掉任务版本。技术、画面、性能和人工接受分别报告。

Agent 在有意义的失败、用户纠正和返工时维护[使用反馈摘要](usage-feedback.md)，并在暂停、交接或完成时给出文档入口，无需另填复盘表。直接说 **“导出这次使用反馈”**，即可取得简短 Markdown、完整 JSON 与本地 Issue 草稿。检查文本后，将 Markdown 和 JSON 一起交给维护者；导出本身不会提交 Issue 或上传工程。未记录的情况保持未知，不能视为没有问题。

## 其他适配场景

[创建/修改灰盒与 Blender 空间](greybox-authoring.md)可在原生基线或 `.blend` 停止；[局部画面修订](visual-harness.md)复用已接受方向；讨论只交付方案；继续旧任务先恢复原记录。这些终点由实际请求决定，不自动扩展成多风格生产。
