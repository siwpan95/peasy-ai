# P0 — 评估地基：把「尺子」先立起来

> 目标：在动任何模型之前，先让「改进是否有效」变成**可判定的**。
> 方法论直接搬自 `weiqi_lab/docs/TIER3_LEARNING.md` —— 那个项目靠「留出集 +
> 均匀基线 + 相对增益 + 合成可判定用例」抓出了「对称帧未归一」的语义缺陷，
> 修完 top-1 从 7.25% → 21.34%。本轮在 easy-ai 上复现了同一套纪律。

## 1. 改造前的实测缺陷（全部有 file:line 证据）

| # | 缺陷 | 证据 | 处置 |
|---|---|---|---|
| D1 | ~~未接入主链路~~ | **已更正**：`MATCHER_REGISTRY` 自动注册，链路上确有 `MarkovMatcher`（priority 30） | 真实问题是语料最差，见 D5 |
| D2 | 零测试覆盖 | `tests/` grep `neural\|markov` 无命中 | 新增 `test_markov.py` + `test_eval.py`（44 项） |
| D3 | 文档撒谎 + 死代码 | `neural.py:11` 声称含 `TextCNN`，实无该类；`Conv1DLayer` 从未实例化 | 留待 P2 处理（真 TextCNN） |
| D4 | 伪置信度 | `markov_chain.py:353` 旧实现 = `Jaccard(输入,生成文本)*0.5+0.25` | 改为**相对均匀基线的归一化增益** |
| D5 | 语料最差 | `build_from_rules()` 把 pattern 与 response 混训 | 改为项目内真实问答对（`corpus: auto`） |
| D6 | 无平滑 | 仅逐级回退，未见组合概率为 0 | 新增 add-k 与**插值式 Kneser-Ney** |
| D7 | 无评估 | 无留出集 / perplexity / top-k / 基线 | 新增 `ai/eval/` 全套 |
| D8 | 死代码 + 性能炸弹 | `_build_keyword_index` 空实现；`_build_corpus_keywords` O(状态×语料) | 改为字符 bigram 倒排索引 |
| D9 | 语义错位 | 以用户输入为 seed 续写 → 产出"用户句子的续写" | 用户/AI 语料分离，回复从 AI 侧链生成 |

## 2. 新增资产

| 路径 | 作用 |
|---|---|
| `ai/eval/tokenize.py` | 全项目唯一分词器（train/test 必须同源，否则 perplexity 不可比） |
| `ai/eval/corpus.py` | 多源语料加载 + 按文档留出集划分（前 80% / 后 20%，确定性） |
| `ai/eval/metrics.py` | perplexity / top-k / 均匀基线 / 相对增益 / 覆盖率 / OOV |
| `tools/eval_baseline.py` | 基线评估器，产出 `docs/BASELINE_P0.md` |
| `tests/test_markov.py` | 22 项（含合成可判定用例，钉死 D4/D6/D9） |
| `tests/test_eval.py` | 22 项（校验尺子本身可信） |

## 3. 过程中的三次自我修正（值得记住的三类陷阱）

### 3.1 指标被 OOV 劫持

首次跑出「无平滑 perplexity 104，Kneser-Ney 441」，看似反直觉。真因是
留出集 **OOV 28.35%**，未见 token 被 clamp 到 `log=-20`，perplexity 反映的
几乎全是「有多少词没见过」，而非建模质量。

→ 补 **UNK 折叠**（`unk_cutoff`，低频词与未见词统一映射 `<unk>`）后，
perplexity 418 → 66，平滑方式之间才变得可比。

### 3.2 评估口径自身有缺陷（与 weiqi_lab §2.6 同类）

UNK 折叠后 top-1 反而从 20.90% 掉到 16.58% —— 因为真值 token 没走同样的
UNK 归一，「模型正确预测出生僻词（输出 `<unk>`）」被误判为不命中。

→ 修 `metrics` 让真值也归一后，top-1 回到 **42.70%**。
**教训：改模型的同时必须检查尺子，否则会把正确改动误判为退步。**

### 3.3 静默兜底掩盖真 bug

`_load_corpus` 为「不破坏零配置启动」写了 `except Exception: pass`，
结果 `QAPair` 无法解包成元组的真 bug 被吞得无声无息（表现为模型永远没训练）。

→ 改为 `except` 后**记录 warning**。教训：**降级可以，静默不行**。

## 4. 基线结论（详见 `BASELINE_P0.md`）

| 指标 | 最优 | 配置 |
|---|---|---|
| top-1 | **45.41%**（相对均匀 160.3×） | n=5 / kneser_ney / cutoff=1 |
| perplexity | **13.26**（相对均匀 26.6×） | n=5 / none / cutoff=1 |
| 默认采用 | top-1 42.16%，perplexity 27.72 | n=3 / kneser_ney / cutoff=1 |

- **UNK 折叠是最大单项改进**（cutoff 0→1：perplexity 418→66）。
  cutoff 继续增大只会缩水词表、top-1 下滑 —— 属指标假象，故默认取 1。
- **小语料下平滑会稀释已见的确定性转移**：每个 context 平均计数≈1，
  add-k/KN 的 perplexity 反而差于 MLE+回退；但 top-1 三者持平且平滑消除了零概率，
  而生成采样需要非零分布 → 默认仍取 Kneser-Ney。

## 5. P0 没能解决的问题（交给 P1/P2）

1. **语料仅 4249 token、留出集 OOV 43%** —— 这是当前第一瓶颈。
   weiqi_lab 的实测：同一模型换语料，相对增益 1.34× → 50.1×，
   远大于换模型架构的收益（21.3% → 25.8%）。→ **P1 主攻**。
2. `neural.py` 的 `Conv1DLayer` 仍是死代码，无真 TextCNN。→ **P2 主攻**。
3. 端到端回复质量仍受语料限制（如「什么是深度学习」→「学习是型战斗中的敌人」），
   这是 4249 token 语料的必然结果，不是模型选型的锅。
