# Changelog

[English](README.md) · [简体中文](README.zh-CN.md)

## 0.15.3 — 2026-11-03

- Reading executor status and image job records now retries brief Windows sharing conflicts for up to one second, including CRT permission errors without a Win32 code. Invalid JSON is not retried. / 查询执行器状态和图像任务时，对 Windows 短暂文件占用最多重试一秒，兼容仅返回 EACCES 的情况；损坏的 JSON 不重试。
- Image read errors now distinguish file access failures from invalid documents without printing document contents. / 图像任务读取错误区分文件访问失败和文档格式错误，不输出文档内容。

## 0.15.2 — 2026-11-03

- Use one installation prompt for the current agent; offline and manual installation remain available. / 在当前 Agent 中用一句话安装，保留离线及手动安装方式。
- Fix Windows process checks and atomic state writes, recover locks after process exit, and reject hard-linked lock files. / 修复 Windows 进程检测与状态写入；进程退出后可恢复锁，并拒绝会损坏其他文件的硬链接锁。
- Preserve the original image task during polling and recovery. Distinguish temporary contention from duplicate supplier jobs. / 图像轮询和恢复保留原任务身份，供应商任务不再因临时锁争用被误判为重复提交。
- Rotate rate-limited work fairly and count provider occupancy once per scan. / 限流调度按任务轮转，每轮只统计一次供应商占用，避免队尾饥饿和重复扫描。
- Preserve UTF-8 prompts and scene paths, merge concurrent Unity package updates, and keep upgrades working after rollback to 0.15.1. / 保留中文提示词与场景路径，并发合并 Unity 包依赖，回滚到 0.15.1 后仍可再次升级。

## 0.15.1 — 2026-11-02

First public release of Grey2Art. / Grey2Art 首次公开发行。

- Turn an existing gameplay greybox into one or more playable art styles, or start from a gameplay brief or reference. / 从已有玩法灰盒制作单个或多个美术版本，也可从玩法需求或参考开始。
- Develop concepts, spatial recipes, asset boards and 3D assets into editable native samples in Godot or Unity; use Blender for spatial authoring and checks. / 从概念、空间配方、资产图板和 3D 资产推进到 Godot／Unity 可编辑样段，支持 Blender 空间创作与验证。
- Inspect assets, resume original tasks and export local usage feedback. / 支持资产体检、原任务接续和本地使用反馈导出。
- Install the complete Skill in Codex, Claude Code or WorkBuddy; verified ZIP and checksums are provided with the release. / 支持 Codex、Claude Code、WorkBuddy，随发行提供校验过的完整安装包与校验值。

- Preserve Unicode paths and text in offline installation and CLI/MCP output across supported operating systems. / 跨平台安装及 CLI／MCP 输出支持中文等 Unicode 路径与文本。

- Use Pillow 13 for image processing in a Python 3.11+ runtime; offline commands retain Python 3.10 support. / 图像处理使用 Python 3.11+ 与 Pillow 13，离线命令保留 Python 3.10 支持。

Demo games and media retain their source rights. See [third-party notices](THIRD_PARTY_NOTICES.md). / 演示游戏与媒体保留来源权利，见[第三方声明](THIRD_PARTY_NOTICES.md)。
