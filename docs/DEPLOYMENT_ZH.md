# 中文部署与验收指南（v0.1–v0.3）

> **新用户先读 [五分钟快速上手](QUICKSTART_ZH.md)**。本页是完整手工试点及高级功能验收手册，不需要第一次使用就完成所有步骤。

## 三类资料，绝对不要混放

1. **公开工具仓库 `ai-context-hub`**：这是作者发布的程序、文档、测试、虚构示例。普通使用者可以直接克隆工具，不需要为它另建一个公开仓库。
2. **你自己的私有上下文仓库 `my-ai-context`**：项目背景、经批准的决策、交接记录、任务包。必须 Private。
3. **按需创建的独立私有源码仓库**：每个真实应用项目各一个，承载代码、测试和必要设计资源；上传前先审查文件清单和 Git 历史。不要把源码放进公开工具仓库或当作上下文文档上传。

只有第一类是公开资料；真实业务记录和源码是否向其他人授权，由各仓库所有者单独管理。

工具基于 Python 标准库和 Git；云端默认 GitHub 的私有仓库，但也可迁移到 GitLab、Gitea 或自建 Git 服务器。**不用部署数据库、额外 Agent、MCP 服务器或模型 API。**

## 第一步：准备仓库

从公开仓库克隆 `ai-context-hub` 工具；只需另外创建**你自己的** `my-ai-context`（Private）。若要接入已有本地应用源码，再另外创建对应的 Private 代码仓库。当前工具不负责创建远端仓库，也不会改动账号下任何既有仓库。

开始前确认你自己的项目资料目的地为 Private。**不要**把本工具包、私人上下文和业务源码混在一个仓库；不需要下载或推送任何名为 private-seed 的特殊 ZIP。只在独立私有仓库中初始化和保存你自己的记录。

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

## 第五步：v0.2 任务包、素材交接与 UAT 闭环

上面四步跑的是 v0.1 的「上下文 + 交接日志」。v0.2 把「谁批准了什么、对应哪次代码、缺陷怎么回来」也变成可核对的文件。**下面所有命令都在私有仓库的本地克隆里执行。**

### 5.1 先证明权限，再承诺能审查

```bash
python /path/to/ai-context-hub/src/ach.py --root . onboard-check \
    --source-repo <你的应用代码仓库地址> --prove-push
```

- 结论必须是 `READY`，`CONTEXT_READ`（上下文仓库可读）、`SOURCE_READ`（代码仓库可读）、`CONTEXT_PUSH`（有推送权限）三项都得是 `PASS`。
- 只要有一项没验证通过，结论是 `BLOCKED`，就**不能**对外宣称「可以让另一个 AI 审查代码了」。这时应该去解决权限，而不是让对方再要一份 ZIP。
- `--prove-push` 会真实推一个临时探测引用、读回、再删掉，属于一次真实写入验证，而不是猜测。

### 5.2 任务包：先批准，才能发布

```bash
# 规划方起草（此时只在本地，远端还没有任何东西）
python .../ach.py --root . task-new --project <代号> --task pilot-1 \
    --title "<这件事>" --accountable workbuddy --revision v1 \
    --source-repo <代码仓库地址> --baseline-sha <当前代码 HEAD> \
    --scope "<本次做什么>" --out-of-scope "<不做什么>" --expected "<可观察的结果>"

# 登记已批准的图片素材（可选，但一旦登记就按哈希校验）
python .../ach.py --root . task-asset --project <代号> --task pilot-1 \
    --file ./已批准的示意图.png --origin "<这张图从哪来>" --approved-by <你的名字>

# 由「你本人」批准这次修订（每个任务只批准一次）
python .../ach.py --root . task-approve --project <代号> --task pilot-1 \
    --approved-by <你的名字> --statement "批准：这一版就是用来开工的版本。"

# 发布到远端
python .../ach.py --root . task-publish --project <代号> --task pilot-1

# 任何 Agent 读取时都先核对最新远端版本
python .../ach.py --root . task-read --project <代号> --task pilot-1 --sync
```

关键规则（都由程序强制，不靠自觉）：

- 没有 `APPROVAL.md` 或简报仍是 `PENDING`，`task-publish` 直接拒绝，**不会推送任何东西**。
- 批准记录里存了 `BRIEF.md`、`ACCEPTANCE.md` 和 `ASSETS.md` 的 SHA-256。素材必须先登记再批准；批准后修改范围、验收标准或素材清单，发布都会拒绝。
- `--approved-by` 和 UAT 的人员字段只是写入 Git 的声明，CLI 不验证现实身份。谁能批准、发布和改历史，仍由仓库权限、受保护分支和人工复核控制。
- 已经发布过的任务包**永远不会被覆盖**。要改就得新开一个 task 编号或新版本号。
- `sync-push` 只接受新的交接日志，**不能**用来夹带任务包或 UAT 记录；这是故意的，避免绕过上面的门槛。
- 素材限制：只允许 png/jpeg/gif/webp、单个不超过 5 MB、文件名必须是小写安全名、按文件头校验真实类型、禁止软链接和路径穿越。哈希对不上就拒绝发布。

### 5.3 实现完成：交证据，不是交结论

在**另一个**应用代码仓库里开发（建分支、开 PR，不要直接推 main），然后回到上下文仓库写完成记录：

```bash
python .../ach.py --root . handoff --project <代号> --agent workbuddy \
    --task "Implement pilot-1" --result "<实际改了什么>" --evidence "commit <sha>" \
    --source-repo <代码仓库地址> --branch <分支名> --code-sha <完整 sha> \
    --pr <PR 链接> --build "<构建/运行命令>" --tests "<真实的测试输出>" \
    --acceptance PENDING --status VERIFIED
python .../ach.py --root . sync-push --project <代号>
```

- `--source-repo`、`--branch`、`--code-sha` 是必填，`--code-sha` 必须是真实的 7–40 位十六进制提交号，占位符会被拒。
- **「AI 做完了」不等于「人验收通过」。** 默认写 `--acceptance PENDING`；只有引用了状态为 `re-tested` 的 UAT 记录，才允许写 `PASSED`，否则程序拒绝。

### 5.4 UAT：人测得怎么样，直接回到代码

```bash
# 你测完，报一个缺陷（可以带截图）
python .../ach.py --root . uat-new --project <代号> --task pilot-1 --reporter <你的名字> \
    --source-repo <代码仓库地址> --tested-commit <你实际测的那个 sha> \
    --environment "<系统 / 版本 / 构建号>" --steps "1. ... 2. ..." \
    --expected "<应该发生什么>" --observed "<实际发生了什么>" --severity high \
    --screenshot ./缺陷截图.png
python .../ach.py --root . uat-publish --project <代号> --feedback <记录 id>

# 后续状态是「追加」，不改写历史
python .../ach.py --root . uat-status --project <代号> --feedback <记录 id> \
    --status fixed --by codex --related-pr <修复 PR> --note "补了回归测试"
python .../ach.py --root . uat-publish --project <代号> --feedback <记录 id>
```

- 记录刚建立时状态是 `reported`，**当前状态取状态历史的最后一行**，旧行永不修改。
- 已发布的记录**只能追加**：可以加状态、加新截图；改写或删除已发布内容会被拒绝，这样审查方永远看得到最初的原始报告。
- 状态取值：`reported` → `reproduced` → `fixed` → `re-tested`。
- 如果没有代码仓库读取权限，正确做法是**解决权限**，而不是让用户再发一份整个项目的 ZIP。
- 二进制截图无法通过某些聊天连接器上传时，必须如实说明限制并改用本地 CLI，**不能谎报上传成功**。

## 第六步：验收

v0.1 交接闭环：

- [ ] WorkBuddy 完成远端读取 + 新增日志提交 + 远端读回，报告 commit SHA。
- [ ] Codex 从同一远端读取 WorkBuddy 的日志，再独立提交自己的日志，报告 SHA。
- [ ] ChatGPT 通过 GitHub 连接器重新读取两个日志，核对已确认的项目决策。
- [ ] 三方理解一致，无法访问时明确报错，敏感数据未流向公开仓库。
- [ ] 核对完成后才宣布从旧共享云盘切换至 GitHub 单一事实来源。

v0.2 任务包与 UAT 闭环：

- [ ] `onboard-check` 对每个参与方都返回 `READY`，并且结果写进了带证据的交接记录。
- [ ] 没有批准记录时 `task-publish` 被拒绝；批准后修改简报也被拒绝。
- [ ] 从一个全新克隆里能读到 `BRIEF.md`、`ACCEPTANCE.md`、`ASSETS.md`、`APPROVAL.md` 和已批准图片，且清单哈希与文件一致。
- [ ] 重复发布是空操作；远端已有不同内容的任务包被拒绝覆盖，而不是被改写。
- [ ] 素材缺失、权限不足、超大/非法文件、路径穿越、fetch/push 失败、本地已有未提交改动，全部安全失败且本地文件不丢。
- [ ] 完成记录里带真实 SHA、PR、构建命令、真实测试输出，且明确写着 `Human acceptance: PENDING`。
- [ ] 在没有 `re-tested` 记录时，`--acceptance PASSED` 被拒绝。
- [ ] 两个 Agent 同时发布交接日志与任务包都能保留；旧的失败恢复测试仍然全绿。
- [ ] 已发布的 UAT 记录只能追加：加状态、加截图成功，改写或删除被拒绝。
- [ ] 公开仓库测试夹具里没有真实项目、聊天记录或私人图片。

## 发布验收

跑通 `python -m unittest discover -s tests -v`；确认公开仓库不包含 `projects/` 私人数据目录或其他私人文件。公开项目只有代码、说明和虚构示例。开源许可证需要仓库所有者单独选择；未作决定前不要自动添加 MIT/Apache 授权。

手工三方试点（规划方批准 → 实现方交付证据 → 审查方独立核对 → 你本人做 UAT）的完整步骤见 [PILOT_RUNBOOK.md](PILOT_RUNBOOK.md)；任务包与 UAT 的字段定义见 [TASK_PACKET.md](TASK_PACKET.md)。

## v0.3：把你本地已有的项目安全接入私有代码仓库

这一步解决的是「以后不用再发 ZIP」：让代码进入一个**独立的私有代码仓库**，另一个 AI 用它的连接器就能读到确切版本。

**三层必须分开**：公开工具仓库（本项目）／私有上下文仓库（记录）／**每个应用一个私有代码仓库**（代码）。本功能只把本地项目送进第三层，**不会**把业务代码写进上下文仓库。

### 3 步走（先看、再批准、最后上传）

```bash
# 1) 只读体检：不会写入、不会暂存、不会删除任何东西
python .../ach.py source-inspect --path "$HOME/Desktop/某个项目"

# 2) 先在网页上建好「私有」空仓库，然后生成上传计划
mkdir -p ~/source-onboarding/某个项目
python .../ach.py source-plan \
    --path "$HOME/Desktop/某个项目" --project some-project \
    --dest git@github.com:<你>/some-project.git \
    --workdir ~/source-onboarding/某个项目 \
    --authorize "<你的名字>" --statement "批准：这是要上传的文件清单"
# 它会打印一份哈希值（清单指纹）和 SOURCE_MANIFEST.txt

# 3) 你看过清单后，用那个指纹批准上传
python .../ach.py source-publish --workdir ~/source-onboarding/某个项目 \
    --approve-manifest <上一步打印的指纹>

# 4) 用全新克隆独立验证（证明远端真的有了）
python .../ach.py source-verify --workdir ~/source-onboarding/某个项目

# 5) 记录「别的工具」能不能读——不要靠猜，也不要拿本机读取成功当三方成功
python .../ach.py source-access --workdir ~/source-onboarding/某个项目 \
    --tool chatgpt --status pending --evidence "连接器还没指向这个仓库"
```

### 会被直接拒绝的情况（不是提醒，是拒绝）

- 选中了 `.env`、密钥、证书库、数据库文件，或文件内容里有凭据特征；
- 这些文件**曾经进过项目的 Git 历史**——因为推历史等于把它们一起公开，本工具**不会**改写历史；
- 目标仓库**匿名可读**（那就是公开的，拒绝）；
- 目标仓库不存在或本机没权限——会明确告诉你「需要先建私有仓库并授权」，而不是假装成功；
- 项目已经有指向别处的 `origin`（拒绝改指向）；
- 远端已有本地没有的提交（**拒绝强推**，也不会自动合并）；
- 要上传的提交内容与已批准清单**不完全一致**（多一个少一个都不行）。

### 压缩包 / 备份 / 超大文件

默认**排除**并列出，需要你用 `--allow-review` 明确提升才会进清单。备份和导出最容易误传。

### 诚实的边界

- **建仓库这一步不在范围内**：需要你账号的授权，工具会报「需要先做这一步」。
- `source-verify` 只能证明**本机**能推、能读回；**别的工具能不能读必须单独记录**。在没有第二个工具记录成功之前，汇总结论只会显示 `NOT VERIFIED`。
- 聊天连接器目前**不支持**上传二进制（截图），走本机 CLI。
- 全部动作都由你触发，没有后台同步。
- 凭据检测是模式匹配，不是完整扫描；上传前请自己看一遍清单。

