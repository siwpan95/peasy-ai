# Changelog

本项目所有值得注意的变更都会记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

> 说明：v1.0.0 之后、v2.2.0 之前的改动（去本地化、README 整理、.gitignore 补齐等）当时未记入本文件，此处据提交历史补记。
>
> 版本号的另一次说明见下：PyPI 首发（peasy-ai 1.0.0）**不继承**仓库内部版本号，
> 仓库此前同时存在 3.2.0（`__init__.py` / `ai/core.py` / `engine/core.py`）与
> 2.2.0（`config_loader.py` / `config/default.json` / CHANGELOG / tag v2.2.0）两套值，
> 首发时统一重置为 1.0.0，以 PyPI 发布序列为准。

## [1.0.1] - 2026-10-21

《四境》纪录片项目压测反哺：`tests/smoke_easy_ai.py` 66/81 → 81/81，
仓库自带 unittest 127/127 保持全绿。

### Fixed

- **`paotuan` 子包 pip 安装后整体不可用（P0，打包级）**：`core/` `services/` `view/`
  及 `mirror_mvp.py` / `mirror_launcher.py` 共 12 个文件原使用顶层绝对导入
  （`from core.xxx import` / `from view import`），源码自举可跑但
  `import easy_ai.paotuan.core.scene_engine` 必然 `ModuleNotFoundError`。
  改为**双模导入**：优先相对导入（`from .core.xxx` / `from ..core.xxx`），
  `ImportError` 时回退顶层绝对导入——包内导入与 `main.py paotuan`
  的文件式自举加载（`spec_from_file_location`，无父包）两种模式同时可用
- **`AICore` 开关类方法不支持链式调用**：`set_safety` / `add_matcher` /
  `set_selection_strategy` / `enable_sessions` / `enable_intent` /
  `enable_stage` / `disable_stage` / `save` / `reload` / `load`
  原隐式返回 `None`，现统一返回 `self`
- **`AICore.import_memory()` 只收 JSON 字符串**：与 `export_memory()` 不对称，
  内存 roundtrip 备份不可用；现同时接受 dict 与 JSON 字符串
  （`import_state()` 同步支持）
- **`AICore.add_matcher()` 无法注册自定义匹配器**：原签名 `add_matcher(matcher)`
  不支持指定名称；现为 `add_matcher(name, matcher=None, **config)`，支持
  实例 / 类 / 工厂函数三种注册方式，鸭子类型对象（仅实现 `match()`）
  会自动补齐 `name` / `priority` / `min_confidence` / `can_process` 协议默认值
- **`AICore.remove_matcher()` 调用了不存在的方法**：`ResponsePipeline`
  没有 `remove_matcher`，调用即 `AttributeError`；已补齐实现
- **`AICore.get_pipeline_info()` 必然 AttributeError**：`ResponsePipeline`
  没有 `get_info()`（`AICore` 上有 `get_info` 而管道对象上没有，命名不统一）；
  已为管道补齐 `get_info()`，返回阶段开关 / 匹配器清单 / 选择策略 / 安全配置
- **`enable_intent()` 签名不统一**：原无参数，现为 `enable_intent(enabled=True)`，
  与 `enable_sessions()` / `enable_stage()` 一致，`False` 可关闭意图识别
- **`set_safety()` 传布尔触发裸 TypeError**：`len(True)` 炸出
  `object of type 'bool' has no len()`；现支持布尔快捷开关
  （保留现有关键词），非法类型给出明确 TypeError

### Changed

- `ResponsePipeline.add_matcher()` 排序键对缺失 `priority` 的匹配器
  回退默认值 50（直接调用管道 API 时更稳）

### Docs

- README「核心用法」补充属性/方法说明：`memory_count` / `cache_size` /
  `session_count` / `matchers_info` 为 `@property`（无括号访问），
  开关类方法返回 `self` 支持链式

## [1.0.0] - 2026-10-20（PyPI 首发：peasy-ai）

首次打包发布。仓库此前**没有任何打包文件**（无 `pyproject.toml` / `setup.py`），
本条目记录的是补上的"打包底座"。

### Added

- **`pyproject.toml`**：setuptools + **src 布局**，发行名 `peasy-ai`、导入名 `easy_ai`
  - 控制台入口 `peasy-ai`（等价 `python -m easy_ai`）
  - 包数据随包分发：`config/*.json`、`data/**/*.json`、`paotuan/` 子应用及其模组
  - 可选依赖分组：`[numpy]` `[jieba]` `[sklearn]` `[all]` `[dev]`；**核心零硬性依赖**
- **`src/easy_ai/__main__.py`**、**`src/easy_ai/paotuan/__init__.py`**（paotuan 为独立自举子应用，补 `__init__.py` 以便随包分发）

### Changed

- **命名空间重构**（沿用 zhuangtaiji 先例）：`ai/` `engine/` `trpg/` `ui/` `paotuan/`
  `config/` `data/` `__init__.py` `main.py` 全部移入 `src/easy_ai/`
  - 原因：顶层 `ai` `engine` `ui` `config` `data` `tools` 都是通用名，
    原样发布会污染 `site-packages`，且 PyPI 上 `easy-ai` / `easy_ai` / `easyai` 均已被他人占用
  - 改写 **61 处**绝对导入（`from ai.` → `from easy_ai.ai.` 等）
  - 删除包内 3 处 `sys.path` 自举（`main.py` / `trpg/adapter.py` / `trpg/trainer.py`），
    改由包机制保证；`trpg/paotuan_gui.py` 保留 paotuan 自身的自举（它不依赖 easy_ai）
  - `PROJECT_ROOT` 改为按 `__file__` 推导包目录，安装后即 `site-packages/easy_ai`
- **版本统一为 1.0.0**：`__init__.py` / `ai/core.py` / `engine/core.py` /
  `ai/config_loader.py` / `config/default.json` 五处
- **发行名定为 `peasy-ai`**（三次改名，每次都是被 PyPI 规则逼的）：
  - `easy-ai` / `easy_ai`：被 Khoa1468 的占位包（summary 就叫 "My Project Dont Touch"）占用；
    `easyai` 是 Zulko 的 EasyAI 博弈库 —— 三个都不可用
  - `easya1`：TestPyPI 干跑通过，但**正式 PyPI 拒收** ——
    `400 The name 'easya1' is too similar to an existing project`
  - 根因是 Warehouse 的 `ultranormalize_name` 比对规则：**`o/O→0`、`l/L` 与 `i/I→1`、
    去掉所有 `-_.`** 后再比。于是 `easya1` 与既有的 `easyai` 都折叠成 `easya1` ⇒ 撞名。
    ⇒ **TestPyPI 干跑不能替代正式校验**：两边的项目库不同，`easyai` 不在 TestPyPI 上，所以干跑放行了。
- README：改为 `pip install peasy-ai` + `import easy_ai`，挂 PyPI 徽章，
  目录结构更新为 src 布局，去掉已不存在的 `ai_core.py` 与 `<PATH>` 占位符
- `.gitignore`：补 `build/` `dist/` `*.egg-info/`

### Fixed

- **无 numpy 时 `create()` 直接崩溃**（既有缺陷，`_init_matchers` 对配置未列出的匹配器
  默认 `enabled=True`，构造 `NeuralMatcher` 抛 `ImportError` 并一路冒泡）
  → 匹配器构造缺可选依赖时改为**告警并跳过**，核心能力零依赖可用
- `tests/test_engine.py`、`tests/test_neural_matcher.py`、`tools/train_textcnn.py`、
  `tools/eval_rerank.py` 中指向根 `data/`、`config/` 的相对路径随目录迁移一并修正

### 验证

- `python -m pytest tests -q` → **127 passed**（与重构前 v2.2.0 基线完全一致）
- `python -m build` → sdist + wheel，`twine check` 双双 PASSED
- wheel 顶层**仅 `easy_ai`**（无通用名污染），97 个条目，中文文件名正常
- 干净 venv `pip install peasy-ai==1.0.0`（`pip list` 只有 peasy-ai，**零依赖**）后于中立目录复验：
  `__file__` 指向 site-packages、`create()` / `learn` / `respond` / 叙事引擎 / 掷骰 全通

### 发布记录

| 项 | 值 |
|---|---|
| PyPI | <https://pypi.org/project/peasy-ai/1.0.0/> |
| 产物 | `peasy_ai-1.0.0-py3-none-any.whl` + `peasy_ai-1.0.0.tar.gz` |
| 发行名 / 导入名 | `peasy-ai` / `easy_ai` |
| 控制台入口 | `peasy-ai`（等价 `python -m easy_ai`） |
| 上传时刻 | 2026-10-20 12:36 (+0800)，正式索引实装复核通过 |
| tag | `peasy-ai-v1.0.0` |

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

## [1.0.0] - 2026-08-27（仓库内部版本，与上方 PyPI 首发的 1.0.0 不是同一个）

> 本条是仓库**内部版本序列**的 1.0.0（2026-08-27）。PyPI 首发不继承该序列、另起 1.0.0，
> 见本文件顶部的 `[1.0.0] - 2026-10-20（PyPI 首发：peasy-ai）`。两者同名但含义不同，
> 不合并、不改写，保留原样以免伪造历史。

### Added

- 首个发行版：便携源码 zip（剔除 .venv/构建产物/输出物，依赖见 README）。
- 发布面：gitee [siwpan/easy-ai](https://gitee.com/siwpan/easy-ai) release `v1.0.0`（通用 AI 对话框架 v1.0.0）。
  ⚠️ 该仓库已于 2026-10-20 **删仓重建为 `siwpan/peasy-ai`**（按 bloodmusic 先例，不在旧仓上改名），
  此链接为改名前的历史地址，不再维护。
