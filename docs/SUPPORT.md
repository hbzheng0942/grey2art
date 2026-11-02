# Support and feedback / 支持与反馈

[English README](../README.md) · [中文首页](../README.zh-CN.md) · [Community / 社区](COMMUNITY.md)

Use this repository's **Issues** for reproducible bugs and feature proposals. English and Chinese are welcome. For questions and prototype sharing, join [Discord](https://discord.gg/BKAVwyEMQh) or the [WeChat group](COMMUNITY.zh-CN.md).

可复现缺陷与功能建议提交到本仓库 **Issues**，中英文均可。使用问题和原型分享可到 [Discord](https://discord.gg/BKAVwyEMQh) 或[微信群](COMMUNITY.zh-CN.md)。

## Report a reproducible problem / 提交可复现问题

Include the following; unknown values can remain unknown:

- Skill version and source commit if known / Skill 版本及已知源码提交。
- Host, OS, engine and their versions / 宿主、系统、引擎及版本。
- Stage and intended result / 当前阶段和预期结果。
- Small reproduction steps and actual error / 最小复现步骤及实际错误。
- Whether a provider accepted the operation, and whether the result is known, unknown or downloaded / 供应商是否已接受，结果是已知、未知还是已下载。
- Relevant redacted logs or screenshots / 必要的脱敏日志或截图。

Keep original task IDs and full recovery records privately. Include only the minimum redacted summary in the issue. Do not upload keys, private credential files, signed download URLs, whole case ledgers, personal conversations or full game assets. Review exported feedback before sharing it.

原任务 ID 与完整恢复记录保留在私有环境，issue 只提供最少必要的脱敏摘要。不要上传 key、私有凭据文件、签名下载 URL、完整案例账本、私人对话或游戏资产。分享导出的反馈前仍需人工检查。

Ask your agent to **export usage feedback**. It creates local `usage-feedback.md`, `usage-feedback.json` and `issue-draft.md`; review them, paste the issue draft and attach both feedback files. Nothing is submitted automatically. The Markdown is a short current summary; the JSON preserves recorded history and diagnostic context. [Recording, export and maintainer collection](../skills/greybox-to-multistyle-art/references/usage-feedback.md).

可直接对 agent 说：**「导出这次使用反馈」**。检查生成的 `issue-draft.md` 后粘贴到 Issue，并附 `usage-feedback.md` 和 `usage-feedback.json`。Markdown 提供当前简短摘要，JSON 保留已记录历史和诊断上下文；导出不会自动提交。持续记录、导出与维护者汇总见[使用反馈方法](../skills/greybox-to-multistyle-art/references/usage-feedback.md)。

## Choosing a supported combination / 选择适配组合

[Capabilities](CAPABILITIES.md) describes the available routes and tools. Include the actual package, host and engine versions when reporting a problem.

[功能说明](CAPABILITIES.zh-CN.md)介绍可用路线与工具。反馈时附实际包版本、宿主和引擎版本。

For new features and integration proposals, explain the task, expected input/output and current workaround. For example submissions, follow [contributing](../CONTRIBUTING.md). For credential exposure, unintended uploads or other security-sensitive problems, read [security reporting](../SECURITY.md); keep sensitive details out of public issues and group chats.

功能或适配建议请说明任务、输入／输出与当前替代做法，案例提交参照[贡献说明](../CONTRIBUTING.zh-CN.md)。凭据泄露、非预期上传等敏感问题参照[安全报告](../SECURITY.md)，不要将敏感细节发到公开 issue 或群聊。
