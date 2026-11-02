# Changelog

[English](README.md) · [简体中文](README.zh-CN.md)

## 0.15.2-rc.1 — Unreleased / 未发布

- Use non-destructive Windows process checks for executor status and account claims. / 执行器状态与账号占用检查统一使用不会终止 Windows 进程的存活检测。
- Keep workflow locks on stable OS-owned files, automatically releasing ownership on process exit and recovering stale or incomplete metadata. Stop older workers before upgrading a shared workspace. / 工作流改用固定文件上的操作系统锁，进程退出时自动释放并恢复过期或不完整的诊断记录；升级共享工作区前应先停止旧版 worker。
- Distinguish temporary lock/I/O failures from conflicting supplier operations; unsubmitted work remains retryable without creating another paid task. / 区分临时锁与 I/O 故障和真实重复任务，尚未提交的操作可继续重试。
- Count provider occupancy once per scan instead of once per pending operation. / 每轮扫描统一统计供应商占用，消除待处理任务的平方级遍历。
- Add process-death, concurrent recovery and liveness regressions, including macOS/Windows executor CI jobs. / 增加进程异常退出、并发恢复与存活检测回归，以及 macOS／Windows 执行器 CI。

## 0.15.1 — 2026-11-02

First public release of Grey2Art. / Grey2Art 首次公开发行。

- Turn an existing gameplay greybox into one or more playable art styles, or start from a gameplay brief or reference. / 从已有玩法灰盒制作单个或多个美术版本，也可从玩法需求或参考开始。
- Develop concepts, spatial recipes, asset boards and 3D assets into editable native samples in Godot or Unity; use Blender for spatial authoring and checks. / 从概念、空间配方、资产图板和 3D 资产推进到 Godot／Unity 可编辑样段，支持 Blender 空间创作与验证。
- Inspect assets, resume original tasks and export local usage feedback. / 支持资产体检、原任务接续和本地使用反馈导出。
- Install the complete Skill in Codex, Claude Code or WorkBuddy; verified ZIP and checksums are provided with the release. / 支持 Codex、Claude Code、WorkBuddy，随发行提供校验过的完整安装包与校验值。

- Preserve Unicode paths and text in offline installation and CLI/MCP output across supported operating systems. / 跨平台安装及 CLI／MCP 输出支持中文等 Unicode 路径与文本。

- Use Pillow 13 for image processing in a Python 3.11+ runtime; offline commands retain Python 3.10 support. / 图像处理使用 Python 3.11+ 与 Pillow 13，离线命令保留 Python 3.10 支持。

Demo games and media retain their source rights. See [third-party notices](THIRD_PARTY_NOTICES.md). / 演示游戏与媒体保留来源权利，见[第三方声明](THIRD_PARTY_NOTICES.md)。
