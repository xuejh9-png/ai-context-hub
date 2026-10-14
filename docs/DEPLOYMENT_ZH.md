# 中文部署与验收指南（v0.1）

## 两个仓库，绝对不要混用

1. **公开仓库 `ai-context-hub`**：本代码包、说明、测试、虚构示例。以后作为你的 GitHub 独立作品展示。
2. **私有仓库 `my-ai-context`**：真实项目资料（真实业务或个人项目）、决策和 Agent 交接日志。不可公开。

工具基于 Python 标准库和 Git；云端默认 GitHub 的私有仓库，但也可迁移到 GitLab、Gitea 或自建 Git 服务器。**不用部署数据库、额外 Agent、MCP 服务器或模型 API。**

## 第一步：准备仓库

在 GitHub 用户名下分别创建 `ai-context-hub`（Public）和 `my-ai-context`（Private）。当前工具不负责创建远端仓库，也不会修改既有 `deepseek-whale-girl`。

上传前先确认所选仓库是否公开。把本包的文件只推送到公开仓库；把**另一个独立的 private-seed 包**只推送到私有仓库。不要将两个 ZIP 放入同一仓库，也不要连同任何业务项目代码、私人数据或备份一起上传。

`my-ai-context` 要初始化一个 main 分支，至少包含 `projects/<项目代号>/` 下的三个 Markdown 文件和 `handoffs/README.md`。若使用提供的私有 seed，先进行敏感性审查。

## 第二步：WorkBuddy 与 Codex

只要所在机器已被授权访问私有 Git 仓库，两个 Agent 即可分别克隆一份。它们不用共享同一电脑路径。

```bash
git clone https://github.com/<你的账号>/my-ai-context.git
cd my-ai-context
python /path/to/ai-context-hub/src/ach.py --root . read --project demo --sync
```

如果连接失败，不要默认是 OAuth 问题；先区分 DNS/网络、Git 认证、仓库授权、分支错误。

一次测试交接：

```bash
python /path/to/ai-context-hub/src/ach.py --root . handoff --project demo --agent workbuddy --task '共享连接测试' --result '读到了 D-007' --evidence 'git commit: <实际 SHA>' --status REPORTED_UNVERIFIED
python /path/to/ai-context-hub/src/ach.py --root . sync-push --project demo
```

Codex 用不同的 `--agent codex`，自己先 read --sync 再写。`sync-push` 只提交新的交接文件，拒绝偷偷修改状态/决策文件。

## 第三步：ChatGPT

为 ChatGPT GitHub 连接器授予 `my-ai-context` 的仓库访问权限后，指示它读取最新 `PROJECT_CONTEXT.md`、`DECISIONS.md`、`CURRENT_STATUS.md` 和两条日志。连接器的写入动作是否允许、具体授权范围，都必须实际验证。**不要把仅能读取自动当作能写入**。

## 第四步：验收

- [ ] WorkBuddy 完成远端读取 + 新增日志提交 + 远端读回，报告 commit SHA。
- [ ] Codex 从同一远端读取 WorkBuddy 的日志，再独立提交自己的日志，报告 SHA。
- [ ] ChatGPT 通过 GitHub 连接器重新读取两个日志、核对决策 已确认的项目决策。
- [ ] 三方理解一致，无法访问时明确报错，敏感数据未流向公开仓库。
- [ ] 核对完成后才宣布从旧共享云盘切换至 GitHub 单一事实来源。

## 发布验收

跑通 `python -m unittest discover -s tests -v`；确认公开仓库不包含 `projects/` 私人数据目录或其他私人文件。公开项目只有代码、说明和虚构示例。开源许可证需要仓库所有者单独选择；未作决定前不要自动添加 MIT/Apache 授权。
