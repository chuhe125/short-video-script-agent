# 第四题：短视频脚本 Agent

为创作者生成有来源、可编辑、经过时长与品牌检查的分镜脚本。CLI 使用 Python 标准库实现，真实模式接入 **DeepSeek Flash**，无需安装 Agent 框架。

## 评审入口

- [真实时长修正分镜](examples/real-revised.script.md)：首稿38.43秒 → 模型依据估算重写 → 26.93秒 → 重新估时与检查通过。
- [完整真实Trace](examples/real-revised.output.json)：步骤、参数、观察、后续动作和简要依据。
- [真实工具失败Trace](examples/real-tool_failure.output.json)：估时失败后保留素材与脚本，模型重试并修正。
- [评估与验收映射](docs/03-evaluation.md)：实际结果、失败、限制及全部验收点。
- [测试结果](examples/test-results.txt)：29项单元与回归测试通过。
- [已保存证据校验](examples/evidence-checks.json)：检查来源、时长、版本哈希，以及Trace动作与模型原始函数参数的一致性。

当前已有6组实际调用DeepSeek的执行记录，另有1组真实入口缺参拦截（0次模型调用）。离线Mock记录单独标记mode=mock，不能代替真实模型能力证据。

## 环境与离线运行

Python 3.10+，实际验证为 Python 3.12.5。没有第三方依赖；从本README所在目录执行：

```powershell
python -m src.agent --input examples/revised.input.json --output examples/local.output.json --markdown-output examples/local.script.md
python -m unittest discover -s tests -v
python -m examples.generate
python -m examples.verify
python -m examples.check_submission
```

`examples.generate`只重建本地Mock用例，不覆盖real-*或history。`examples.verify`只读取已保存真实记录，离线核对并重建可读分镜，不调用模型。后者验证已保存证据的一致性，不证明所有未来请求都正确。`examples.check_submission`检查规定文件与密钥误入情况，并明确列出尚未完成的人工提交项。

## DeepSeek真实模式

复制`.env.example`为`.env`并在本地填写密钥，或设置shell环境变量。**不要在.env.example里填写真实密钥。** .env已被.gitignore忽略。

```dotenv
MODEL_API_KEY=<只在本地填写>
MODEL_NAME=deepseek-flash
MODEL_BASE_URL=https://api.deepseek.com
```

也支持DEEPSEEK_API_KEY；MODEL_API_KEY优先。真实模式自动读取`.env`，已有非空环境变量优先；`--env-file`可指定其他配置文件。离线模式不读取密钥文件。

```powershell
python -m src.agent --mode real --input examples/normal.input.json --output examples/real-normal.output.json
python -m src.agent --mode real --input examples/revised.input.json --output examples/real-revised.output.json --markdown-output examples/real-revised.script.md
python -m examples.run_real --cases normal revised tool_failure no_material missing impossible changed_materials
```

最后一条命令会实际调用接口并覆盖所选real-*记录，产生模型费用；执行前确认自己要复测的范围。无密钥或接口异常会明确失败，不自动降级Mock。单次请求超时45秒，每步重新调用模型；默认最多16步，CLI允许1～30步。

接入依据：[DeepSeek官方模型与地址](https://api-docs.deepseek.com/en/)、[函数调用指南](https://api-docs.deepseek.com/guides/tool_calls/)。使用Chat Completions原生函数调用，关闭thinking模式，不采集或保存reasoning_content。只保存业务动作参数、简短理由、响应ID及token用量。

## 输入、输出与事实边界

必填：theme、audience、platform、target_seconds、style。时长必须大于0且不超过600秒。示例产品、素材和规则均为合成数据，无真实产品效果承诺。

- 模型选择检索、写稿、估时、规则检查和结束。执行器验证工具参数、来源、当前稿版本和最终状态。
- 旁白只允许素材fact或该素材的人工审核表达approved_lines；不接受无依据数字或功效宣称。这里是有限表达组合，不是开放式语义事实验证。
- 受众影响语速；平台影响画幅；风格影响镜头建议、标题及停顿范围。这些是显式编辑规则，模型看见规则后选择具体分镜与调整动作。
- 每个分镜给出旁白、字幕、画面、起止秒数、素材ID、原文和日期。每次修改后必须重新估时与检查，旧检查失效。
- target_seconds是硬上限，约90%为编辑建议，不是额外硬门槛。资料少时会提示脚本偏短，不无限添加空镜凑时长。
- 默认按字符语速估算，包含标点；尚未真实配音，不能保证成片秒数。静默演示时长与旁白时间分开统计。

## 失败与执行上限

```powershell
# 一次估时故障，观察模型如何调整
python -m src.agent --input examples/tool_failure.input.json --fail-once estimate
# 持续故障：保留脚本和素材，明确未完成
python -m src.agent --input examples/persistent_failure.input.json --fail-always estimate
# 达到上限：即使保留候选稿，也不声称任务完成
python -m src.agent --input examples/step_limit.input.json --max-steps 4
```

退出码0仅代表completed，其他状态退出码2。输出含status、result、trace、execution；incomplete_step_limit、model_error和needs_input各有明确含义。候选分镜可能在失败结果中保留，必须查看任务状态和两个检查结果。

模型若在一次响应中提出多个函数调用，串行调度器只执行第一项，其余明确记录为unexecuted_calls；下一步再次请求模型依据真实观察决策，不预先执行依赖旧观察的动作。步数上限覆盖这些重新决策。

## 目录与提交

src/为模型与工具代码，tests/为可执行测试，examples/为实际输出和Trace，data/为合成资料，docs/为五份要求文档。无需依赖其他题目目录；不需要数据库、界面或线上部署。

项目仓库：[chuhe125/short-video-script-agent](https://github.com/chuhe125/short-video-script-agent)，当前为私有仓库。候选人仍需如实填写docs/04-ai-usage.md、docs/05-retrospective.md中的个人贡献与实际用时。提交题号4、仓库URL及最终commit SHA；SHA以`git rev-parse HEAD`和最终交付消息为准。私有仓库须确认指定评审账号可读。见[提交记录](SUBMISSION.md)。
