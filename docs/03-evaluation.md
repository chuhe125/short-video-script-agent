# 测试预期、实际结果、失败和限制

实际环境Python 3.12.5；真实模型请求名deepseek-flash，DeepSeek官方Chat Completions原生函数调用、thinking disabled、max_tokens=4096、单次超时45秒，默认16步。服务返回模型名、响应ID、token用量和函数参数保存在各JSON的execution.model_calls。不采集模型内部思维。

本次是有限案例验证，不报告泛化准确率、稳定成功率或真实成片效果。模型别名对应版本可能变化，复测结果应以实际记录为准。

## 核心验收映射

所有输入都在examples/下。real-*为真实入口记录；除缺信息用例在调用前拦截外，其余六组实际调用了DeepSeek。普通*.output.json为Mock，不能作为真实模型效果证明。

| 验收 | 输入 | 真实输出及实际结果 |
| --- | --- | --- |
| 正常生成 | normal.input.json | real-normal.output.json：completed；45.43秒，60秒上限内；时长与规则通过；6次模型调用 |
| 缺关键信息 | missing.input.json | real-missing.output.json：缺受众，needs_input；0次模型调用，没有虚构脚本 |
| 无素材 | no_material.input.json + no_material.data.json | real-no_material.output.json：空资料库，incomplete；检索/补查后停止，5次模型调用 |
| 工具失败 | tool_failure.input.json，fail_once=estimate | real-tool_failure.output.json：估时失败一次，模型保留素材/脚本并重试；39.43秒超时后修正到27.43秒并通过；10次模型调用 |
| 超时长修正 | revised.input.json | real-revised.output.json：首稿38.43秒，模型重写为26.93秒，再次estimate和check通过；8次模型调用 |
| 无法满足时长 | impossible.input.json | real-impossible.output.json：目标0.1秒，已尝试稿1.24秒，incomplete；5次模型调用 |
| 改变检索结果 | changed_materials.input.json + changed_materials.data.json | real-changed_materials.output.json：仅P01，completed，14.57秒；提示素材不足造成偏短；13次模型调用 |

两条清晰的真实动态路径：

- real-normal：资料齐全后生成、检查、结束；不用超时修正。
- real-revised：estimate返回38.43>30，模型选择write修改，26.93<=30，再check、finish。
- 额外real-tool_failure：estimate失败时模型选择重试，之后再根据超时结果改稿。不是执行器自动重试或预设成功日志。

JSON内Trace记录step/action/args/reason/observation，下一条动作体现上一观察后的选择。reason为简短可观察依据，不是内部思维。可读分镜为real-revised.script.md等文件；原始JSON是验收依据。

## 离线测试与证据检查

`python -m unittest discover -s tests -v`：29项通过，完整输出在examples/test-results.txt。新增回归覆盖受众语速/平台画幅/风格变化、修正后24～30秒、来源与版本、时间轴求和、过长空镜阻断、未知来源、品牌禁词、配置语速、持续故障保留、模型异常、上限、修改后检查失效、跳过检查拒绝及接口协议。

`python -m examples.verify`：七组入口记录全部通过一致性核验，见examples/evidence-checks.json。对实际调用路径逐步比较模型原始函数名称/参数/reason与Trace；对完成稿核对来源表达、时长求和和当前稿哈希；验证超时后修正、一次故障记录。它证明已保存证据内部一致，不证明未来运行必然通过。

离线场景另有persistent_failure.output.json、step_limit.output.json、profile_change.output.json、query_rewrite.output.json。对应输入同名。分别证明持续失败不成功、到上限未完成、编辑参数确实改变结果、关键词改写后检索。

## 优化前后与真实失败

- history/before-optimization.output.json：保留原先Mock首稿40秒→4秒的实际记录，作为节奏薄弱问题的证据。
- revised.output.json：优化后Mock首稿39.43秒→27秒；演示停顿保留，来源事实不变。真实模型独立修正结果为26.93秒，不把Mock的27秒当作模型结果。
- history/real-normal.network-failure.output.json、history/real-revised.network-failure.output.json：最初沙箱网络错误，model_error，未伪装成成功。
- history/real-normal.protocol-failure.output.json：早期JSON协议中reason错位、后续JSON解析失败，部分稿保留。
- history/real-revised.protocol-failure.output.json：文本JSON附带尾标，严格解析失败。
- history/real-revised.multiple-actions-failure.output.json：返回多个JSON对象，未擅自选一个冒充完整结果。
- history/real-revised.wrapper-failure.output.json：通用动作包装缺action字段，未执行。
- history/real-revised.parallel-calls-failure.output.json：早期执行器直接拒绝并行调用；最终采用“只执行第一项，其余明确未执行、下一步重新决策”的串行调度，并补回归。

历史记录对应当时实现，可能缺少后加的execution.protocol等元数据，不是最终协议样例。保留失败有助说明修改依据，不要删掉后只报告成功率。

## 限制与剩余交付

时长是字符数估算，不是TTS实测；approved_lines是预审有限表达，不是任意文案事实推断；受众/平台/风格规则为原型启发式；素材少时可能显著偏短。模型曾出现冗余查询、重复估算，虽有限步保护，仍会增加费用与时延。尚未做多随机种子稳定性、线上部署、任意提示注入或真实媒体效果评测。

个人贡献、实际总用时和个人回顾须由候选人补充。仓库URL见SUBMISSION.md，最终SHA以实际提交为准，私有评审权限仍需确认。线上费用由用户模型账户产生，当前未估算货币金额。
