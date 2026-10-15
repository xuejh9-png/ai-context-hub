# 五分钟开始使用 AI Context Hub（中文）

AI Context Hub **不是一个需要部署的网站**。它是一套本地命令行工具，负责把已确认的项目背景、决策和 AI 工作交接保存到**你自己管理的私有 Git 仓库**，让获得授权的不同 AI 工具按需读取。

> **隐私边界**：本项目的代码仓库是公开的；下面创建的项目上下文仓库必须是 **Private**。不要把客户资料、密钥、完整聊天记录或私人项目源码上传到这个公开仓库。

## 0. 准备

- Python 3.10 或更新版本；Git；能访问 GitHub（或兼容 Git 的托管平台）。
- 一个用于保存自己项目资料的**独立私有仓库**，例如 `my-ai-context`。先在托管平台上新建为 Private，并初始化 README（这样已有默认分支）。
- 每位需要执行本地 Git 操作的 Agent 使用自己的授权；ChatGPT 等应用是否支持连接器读写，应分别实测。

以下命令使用 macOS/Linux shell。在 Windows 上建议使用 Git Bash；路径需要按实际环境调整。

## 1. 下载工具和自己的私有仓库

把 `TOOL_OWNER` 换成本工具公开仓库的所有者，把 `YOUR_USERNAME` 换成你自己的 GitHub 用户名。**这两份仓库不是同一个仓库。**

```bash
git clone https://github.com/TOOL_OWNER/ai-context-hub.git
git clone git@github.com:YOUR_USERNAME/my-ai-context.git
cd my-ai-context
```

如果没有配置 SSH，可以把第二条地址换成你具有访问权限的 HTTPS 克隆地址。不要在命令或对话里粘贴密码、访问令牌。

## 2. 建立一个不含敏感数据的演示项目

```bash
python ../ai-context-hub/src/ach.py --root . init --project demo --name "Demo Project"
python ../ai-context-hub/src/ach.py --root . validate --project demo
```

检查新增的 `projects/demo/` 文件，确认完全是你愿意保存在**私有仓库**里的内容。

```bash
git add projects/demo
git commit -m "Initialize demo project context"
git push
```

如果提示没有 Git 用户名或邮箱，先在**这个私有克隆中**配置你的提交身份。如果推送失败，先处理 Git 认证或分支权限；不要使用强制推送。

## 3. 让一个 AI 留下可追溯的交接

```bash
python ../ai-context-hub/src/ach.py --root . read --project demo --sync
python ../ai-context-hub/src/ach.py --root . handoff --project demo \
  --agent implementer --task "Review project setup" \
  --result "Reviewed the demo context" \
  --evidence "Only inspected Markdown files; no runtime tests" \
  --status REPORTED_UNVERIFIED
python ../ai-context-hub/src/ach.py --root . sync-push --project demo
```

这份交接只是**演示记录**，不是代码已通过测试的声明。`sync-push` 只允许发布新交接记录；修改共享决策文件应另外审核并提交。

## 4. 验证另一个 AI 能实际接手

给另一个 AI 工具授权访问你自己的 `my-ai-context` 私有仓库，请它：

1. 读取最新的 `projects/demo/PROJECT_CONTEXT.md`、`DECISIONS.md`、`CURRENT_STATUS.md`。
2. 读取刚才的 `handoffs/` 文件，并说出它记录的任务和**尚未验证**的内容。
3. 回报它实际读到的仓库提交 SHA；如果权限不足，就报告无法验证，不要假装完成。

**通过标准**：第二个工具无需你重新复制整段对话，就能准确读到同一份记录。此阶段不必让它取得写权限。

## 下一步

- 想让 AI 共享**真实项目源码**，还需要把源码上传到**另一个独立的私有代码仓库**。先看 [现有项目安全接入](SOURCE_ONBOARDING.md)：`source-inspect → source-plan → 审查清单 → source-publish → source-verify`。不要把源码放进本工具的公开仓库。
- 要发送已批准的开发任务、交接素材及 UAT 缺陷，阅读 [任务包与 UAT](TASK_PACKET.md)。
- 要完整执行跨 Agent 试点，阅读 [试点操作手册](PILOT_RUNBOOK.md)。
- 要了解凭据、图片和历史记录的安全约束，阅读 [安全说明](SECURITY.md)。

## 常见问题

**Q：GitHub 里能看到文件，为什么 AI 还说找不到？**  
A：每个工具的仓库权限是独立的。先核查仓库可见性、连接器授权、实际读取的分支和提交 SHA。不要把“我这台机器能读”当作“所有 AI 都能读”。

**Q：文件更新之后 AI 会自动知道吗？**  
A：不会。此工具是按需同步；修改者需要提交和推送，读取者需要重新获取新版本。

**Q：失败时可以强制推送覆盖远端吗？**  
A：不可以。先检查本地改动、远端分支以及是否存在同名交接，保留证据并处理冲突。

**Q：这里会自动执行 GitHub、Codex、ChatGPT 的任务吗？**  
A：不会。它存储交接记录和已批准决策，不是后台 Agent 调度服务。
