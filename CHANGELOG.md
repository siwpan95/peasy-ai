# Changelog

本项目所有值得注意的变更都会记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

> 说明：v1.0.0 之后、v2.2.0 之前的改动（去本地化、README 整理、.gitignore 补齐等）当时未记入本文件，此处据提交历史补记。

## [2.2.0] - 2026-10-15

学习型组件深化批次（P0 → P1 → P2 → 端到端 → 重排序 → 扩语料重评）。
主线思路：先把「尺子」立起来，再谈模型改进 —— 每一步都给出可复现的实测数字。

### Added

- **评估框架 `ai/eval/`**
  - `tokenize.py`：全项目唯一分词器（train/test 必须同源，否则 perplexity 不可比）
  - `corpus.py`：多源语料加载 + 按文档留出集划分（确定性、无泄漏）
  - `metrics.py`：perplexity / top-k / 均匀基线 / 相对增益 / 覆盖率 / OOV
- **马尔科夫链重写**（`ai/matchers/markov_chain.py`）
  - 平滑：add-k 与插值式 Kneser-Ney（延续概率替代原始频次）
  - UNK 折叠（`unk_cutoff`）与真·置信度（相对均匀基线的归一化增益）
  - 用户语料 / AI 语料分离建模，回复从 AI 侧链生成
  - 新增 `log_prob` / `top_k` / `perplexity` / `save` / `load`
- **真 TextCNN**（`ai/textcnn.py`，Kim 2014）：Embedding → 多尺度 Conv1D(2/3/4)
  → ReLU → Max-over-time pooling → Dropout → Dense+Softmax，手写前向与反向（仅 numpy）
  - 与马尔科夫链实现**同一套评估协议**，可在同一留出集上直接对照
  - 支持条件训练 `fit(conditions=...)`（P(回答|问题)），用于候选重排序
- **神经网络匹配器**（`ai/matchers/neural_matcher.py`）：离线训权重 + 运行期加载；
  支持 `mode=generate|rerank`，打分器可选 `cnn|jaccard|hybrid`
- **共用检索索引**（`ai/matchers/retrieval.py`）：字符 bigram 倒排索引
- **工具链**
  - `tools/fetch_corpus.py`：联网语料抓取（零三方依赖、限速、中文占比门槛）
  - `tools/eval_baseline.py` / `eval_corpus_ab.py` / `eval_textcnn.py` / `eval_rerank.py`
  - `tools/train_textcnn.py`：离线训练 + 权重导出（支持 `--full` / `--conditional`）
- **文档**：`docs/DEEPEN_P0.md`、`BASELINE_P0/P1/P2/P3.md`、`BASELINE_RERANK.md`、`E2E_NEURAL.md`

### Changed

- 语料从 4,249 → **108,647 token**（并入 `paotuan/` TRPG 模组 + 联网抓取）
- 马尔科夫匹配器默认改用项目内真实问答对（`corpus: "auto"`），不再只用规则库

### Fixed

- 伪置信度：`Jaccard(输入,生成文本)` → 相对均匀基线的归一化信息增益
- 语义错位：以用户输入续写冒充回复 → 用户/AI 语料分离后从 AI 侧链生成
- 死代码与性能炸弹：`_build_keyword_index` 空实现、O(状态×语料) 双重循环 → 倒排索引
- `fuzzy_matcher`：本机 jieba 缺 `lcut`，改为探测属性后降级（修好 4 个既有 failing test）
- TextCNN 训练过程中留出 perplexity 恒为 `exp(20)≈4.85e8`（`_trained` 置位过晚）
- 重排序用无条件模型打分导致失效（top-1 仅 5%）→ 改条件训练后升至 40%
- `top_k` 重复归一化 context 导致 O(n²·V)，扩语料后评估卡死 → 拆出 `_prob_norm` 内核

### 实测数据（详见各 BASELINE 文档）

| 项 | 结果 |
|---|---|
| 语料规模 | 7,950 → 108,647 token（13.7×） |
| 扩语料前 CNN vs 马尔科夫 top-1 | 43.95% vs 34.81%（**+9.14pp**） |
| 扩语料后 CNN vs 马尔科夫 top-1 | 38.26% vs 19.00%（**+19.25pp**） |
| 重排序（负采样判别 1 正 + 9 负） | 随机 0% / Jaccard 60% / CNN 条件似然 40% |
| 梯度检查 | 有限差分 vs 解析梯度，最大相对误差 ~1e-10 |
| 测试 | 127 passed |

### 已知限制（如实列出）

1. **自由生成仍由马尔科夫主导**：TextCNN 生成质量在小语料下不如「回放真实语料」，
   置信度口径（似然增益）天然偏爱记忆型模型；`neural` 默认 `enabled: false`。
2. **重排序上 CNN 不如朴素 Jaccard**（40% vs 60%），样本仅 20 条留出对，差异不足以定论。
3. **联网语料不入仓**（`.cache/` 已 gitignore），需 `python tools/fetch_corpus.py` 重建。
4. 本轮 TextCNN 仅训 3 epoch 做扩语料重评，+19.25pp 为**保守下界**。

## [2.1.0] - 未单独记入（补记）

- 文档去本地化：示例与说明中的绝对路径改为 `<PATH>` 占位符 / 按包自身位置推导
- README 首屏补仓库链接与许可声明

## [1.0.0] - 2026-08-27

### Added

- 首个发行版：便携源码 zip（剔除 .venv/构建产物/输出物，依赖见 README）。
- 发布面：gitee [siwpan/easy-ai](https://gitee.com/siwpan/easy-ai) release `v1.0.0`（通用 AI 对话框架 v1.0.0）。
