# 安装与配置

[English](INSTALL.md) · [简体中文](INSTALL.zh-CN.md) · [README](../README.zh-CN.md)

## 获取完整安装包

完整图像流程使用 [Python 3.11+](https://www.python.org/downloads/)，离线安装与 CLI 命令也支持 Python 3.10。从 [GitHub Release](https://github.com/hbzheng0942/grey2art/releases/latest) 下载 Skill ZIP 和校验文件；ZIP 约 1 MB，无需下载游戏或全部案例媒体。解压后进入 `greybox-to-multistyle-art/`：

```sh
python3 scripts/install.py --verify-only
python3 scripts/install.py --host auto --replace
```

## 从源码安装

也可克隆源码；以下命令在仓库根目录 `grey2art/` 执行：

```sh
git clone https://github.com/hbzheng0942/grey2art.git
cd grey2art
python3 skills/greybox-to-multistyle-art/scripts/install.py --verify-only
python3 skills/greybox-to-multistyle-art/scripts/install.py --host auto --replace
```

Windows 将 `python3` 替换为 `py -3`。保持完整 Skill 目录，单独的 `SKILL.md` 不能运行全部工具。校验不安装或提交生成任务；仅安装 Skill 无需引擎或供应商账户。[包校验方法](RELEASE-PACKAGING.md)

## 选择当前宿主

只为实际使用的宿主安装。`--host auto` 使用当前会话或已有安装的证据；有歧义时不会安装，改为指定一个宿主：

```sh
python3 skills/greybox-to-multistyle-art/scripts/install.py --host codex --replace
```

其他宿主使用 `claude-code` 或 `workbuddy`。默认位置如下：

- Codex：`~/.codex/skills/greybox-to-multistyle-art`；已配置 `CODEX_HOME` 时使用其中的 `skills/greybox-to-multistyle-art`。
- Claude Code：`~/.claude/skills/greybox-to-multistyle-art`。
- WorkBuddy：已有的 `~/.workbuddy/skills`；无法发现时，通过 `--skills-dir` 指定真实 Skill 目录。

显式 `--skills-dir` 指向宿主真正扫描的位置。已有宿主配置可能复用之前的权威安装；安装器始终返回实际路径。不必复制到所有宿主目录。

安装后刷新 Skill 发现或开启新会话，再调用 `greybox-to-multistyle-art`。保留返回的安装路径、版本和旧安装路径。MCP 注册与可选 WorkBuddy 连接器是独立选择；普通使用直接运行同一 Python CLI。

## 生产前先检查

将安装路径交给 agent，先要求离线检查。它可以校验包并检查当前方法：

```sh
python3 "$SKILL/scripts/install.py" --verify-only
python3 "$SKILL/scripts/greybox.py" --version
python3 "$SKILL/scripts/greybox.py" knowledge audit
```

其中 `SKILL` 为安装器返回的路径。这些检查无需服务凭据，不调用生成。宿主 setup 单独检查就绪条件，不证明已经生成有用图片、执行原生操作或得到可玩结果。首次任务见[快速开始](../skills/greybox-to-multistyle-art/references/quickstart-zh.md)。

## 只配置当前操作所需依赖

**制作与验证工具。** 沿用已有引擎与版本。原生装配、可玩检查要求 Godot 或 Unity 已安装且 agent 可调用。准备 Skill 不下载引擎，也不迁移工程。原生路线见[功能页](CAPABILITIES.zh-CN.md)。

**图像。** 合适的宿主原生生图工具可以生成概念和参考图，无需额外图像服务账户。本地解码、裁图使用 Python 3.11+ 与 Pillow 13+。当前宿主缺少可用生图工具时，再按[图像服务](../skills/greybox-to-multistyle-art/references/image-services.md)配置一个服务，保持推理模型不变。生成、读取像素和展示结果是分别验证的能力。

**模型。** 需要新 AI 网格时再配置一个 3D 供应商；复用资产与原生修改可能无需供应商。新网格使用批准的图像参考。首次生产授权前，agent 提出路线、模型／版本、参数、后处理和费用。减面、绑骨、动作是独立操作，可能另外收费。

**Blender。** 作为 DCC 工具，用于空间灰盒、尺度、镜头、几何和离线验证；纯空间或 `.blend` 交付无需游戏引擎。按选定操作准备，复杂拓扑、材质与动作仍需分别验证。

**Python 包。** 核心 CLI 使用标准库。选定图像操作会在独立、可复用的私有环境中准备 HTTP／解码依赖。环境保留在 Skill 和工程之外，不使用全局 pip，不把缓存打入交付。发布验证记录实测依赖组合，操作依赖允许的版本范围可能更宽。

## 选择 AI 3D 供应商

需要生成新模型时，选择一家并开通其 API；仅安装 Skill 或制作灰盒不需要注册这些账户。

| 供应商 | 注册与 API 入口 | Skill 配置方法 |
|---|---|---|
| Lux3D | [中国站](https://lux3d.aholo3d.cn/)／[国际站](https://lux3d.aholo.ai/) · [密钥指南](https://aholo.featurebase.app/zh-CN/help/articles/6916933-dashboardji-fen-yu-api-mi-yao) | [Lux 本地配置](../skills/greybox-to-multistyle-art/references/lux-bridge.md#local-setup)，选择实际账户地区。 |
| Meshy | [官网](https://www.meshy.ai/) · [创建 API Key](https://docs.meshy.ai/en/api/authentication) | [配置方法](../skills/greybox-to-multistyle-art/references/provider-meshy-tripo.md#private-credential-setup)，供应商选 `meshy`。 |
| Tripo | [官网](https://www.tripo3d.ai/) · [开发者密钥](https://developers.tripo3d.ai/en/keys) | [配置方法](../skills/greybox-to-multistyle-art/references/provider-meshy-tripo.md#private-credential-setup)，供应商选 `tripo`。 |
| Rodin / Hyper3D | [官网](https://hyper3d.ai/) · [API Dashboard](https://hyper3d.ai/workspace/api-dashboard) | [配置方法](../skills/greybox-to-multistyle-art/references/provider-rodin-hi3d.md)，供应商选 `rodin`。 |
| Hi3D / Hitem3D | [官网](https://www.hitem3d.ai/) · [API 开通指南](https://docs.hi3d.ai/en/api/getting-started/quickstart) | [配置方法](../skills/greybox-to-multistyle-art/references/provider-rodin-hi3d.md)，供应商选 `hitem3d`。 |

以上为已接入的 API 路线；各家的模型、后处理操作和账户额度分别配置。网站会员与 API 可用额度需在所选平台确认。新模型使用先确认过的图片参考；Lux3D 默认 G1 标准版。

## 账户与凭据

配置前选择真实账户体系。国内与国际账户可能使用不同 key、API 域名、钱包和权益；切换网页语言不会迁移账户。认证失败时不要向另一个地区尝试同一 key。

Lux 配置在用户自己的交互终端运行，使用真实安装路径：

```sh
python3 "$SKILL/scripts/greybox.py" setup --region cn --install-dependencies --configure-key
```

国际账户使用 `--region international`。终端隐藏输入 key，不要把 key 粘贴到 agent 对话。桥接使用支持的凭据存储或明确的地区环境变量。见 [Lux 配置](../skills/greybox-to-multistyle-art/references/lux-bridge.md#local-setup)。

其他内置供应商的[凭据配置](../skills/greybox-to-multistyle-art/references/provider-meshy-tripo.md#private-credential-setup)在 macOS／Linux 支持本地隐藏输入和限制权限的明文文件，该文件并未加密。Windows 使用传入 agent 进程的环境凭据；POSIX 文件辅助工具不声称能设置 Windows ACL。共享配置只记录凭据变量名，不能记录变量值。[账户与恢复身份](../skills/greybox-to-multistyle-art/references/provider-accounts.md)说明地区配置。

配置与余额不授予收费权限。图像探索、模型和后处理费用分别确认；报价、估算、实际扣费分别记录，不合并不同钱包的积分。已有生产范围各自有费用上限，多个 run 的授权不会自动合并为整个案例的总封顶。

## 升级与接续

获取选定固定标签的新 checkout，校验后用相同安装器加 `--replace` 安装。旧安装保存在宿主扫描范围外，返回值给出回退路径；相同包直接复用。

回退使用安装器实际返回的旧路径：

```sh
python3 skills/greybox-to-multistyle-art/scripts/install.py --host codex --rollback "/path/reported/by/installer"
```

随后刷新宿主发现。进行中的案例保留原先绑定的包／运行时和供应商账本。升级不会重写历史接受，也不会自动允许在运行时字节改变后继续提交剩余任务。要求 agent 从已有 task context 接续，先恢复已知供应商任务，再安排新工作。

## 失败时如何处理

- **宿主识别歧义：**指定一个 `--host` 或实际 `--skills-dir`。
- **Manifest 不符：**获取同版本完整包，保留编辑过的安装和进行中的案例。
- **缺少 Python／venv／pip：**图像操作选择已有 Python 3.11+（离线命令支持 3.10+），保留旧环境，跟随当前 setup 诊断处理。
- **依赖下载失败：**修正连接或包索引配置，再重试同一操作，不反复创建完整环境。
- **认证失败：**检查声明的地区账户及 agent 进程可见凭据，不轮流尝试无关账户。
- **生成超时／结果未知：**保留原任务与恢复 ID；查询和下载原任务不需要重新生成。
- **已完成供应商产物缺失或改变：** 保留账本与变动文件。Agent 使用 `supplier-jobs recover-artifacts --run-dir RUN --operation-id ID --source-ref ACTUAL_OBSERVATION` 排队，再恢复原 executor 或 `supplier-jobs step`。只从原任务重取并核对原哈希，不重新生成替代品。

普通脱敏报告见[支持与反馈](SUPPORT.md)，敏感问题见[安全报告](../SECURITY.md)。
