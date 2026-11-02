# Security reporting / 安全报告

## Current reporting route / 当前报告渠道

Use [GitHub private vulnerability reporting](https://github.com/hbzheng0942/grey2art/security/advisories/new) for sensitive reports. If the form is unavailable, request a private contact in [Discord](https://discord.gg/BKAVwyEMQh) without including vulnerability details.

敏感报告使用 [GitHub 私密漏洞报告](https://github.com/hbzheng0942/grey2art/security/advisories/new)。表单不可用时，可在 [Discord](https://discord.gg/BKAVwyEMQh) 请求私下联系渠道，不附漏洞细节。

Do not send sensitive reports to a group chat or public issue. / 敏感报告不要发到群聊或公开 issue。

## What to include / 所需信息

Report credential exposure, unintended file access, unsafe provider routing or unintended uploads. Provide the version, affected entrypoint, minimal redacted reproduction and impact. Keep live keys, signed URLs, private files and original recovery records out of the report until an appropriate private channel is established. If a credential has been exposed, revoke or rotate it through its provider and retain only redacted evidence.

适用问题包括凭据泄露、非预期文件访问、不安全供应商路由或非预期上传。提供版本、受影响入口、最小脱敏复现和影响。合适私密渠道建立前，不发送真实 key、签名 URL、私人文件或原始恢复记录。凭据已暴露时，通过供应商撤销或轮换，并仅保留脱敏证据。

The maintained Skill source and shipped runtime are in scope. External providers, engines and linked demo repositories retain their own reporting channels. Fixes and affected versions are recorded in [release notes](CHANGELOG.md).

维护范围为 Skill 源码和随包 runtime；外部供应商、引擎和链接案例仓库使用各自反馈渠道。修复与受影响版本记录在[版本说明](CHANGELOG.md)。
