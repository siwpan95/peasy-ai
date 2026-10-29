# easy-ai — 通用 AI 对话框架

## 仓库角色定位（投资组合分级 ①）

> 本仓在 siwpan 投资组合（D:/projects/repos，共 133 仓）中定级为 **① 核心推进**，领域 **AI/大模型**，定位 **本地AI叙事**。
> **角色**：零硬编码配置驱动通用 AI 对话框架+叙事引擎，持续投入。
> **维护策略**：① 核心推进——持续投入、不允许冻结；随所属收敛点 / 流水线长期演进。
> 投资组合统一分级索引（多机可查）：[组合分级决策索引 · allin 事实源](https://gitee.com/siwpan/allin/blob/master/docs/事实源/组合分级决策索引.md)。

[![PyPI version](https://img.shields.io/pypi/v/peasy-ai)](https://pypi.org/project/peasy-ai/)
[![Python versions](https://img.shields.io/pypi/pyversions/peasy-ai)](https://pypi.org/project/peasy-ai/)
[![License](https://img.shields.io/pypi/l/peasy-ai)](https://pypi.org/project/peasy-ai/)

零硬编码、配置驱动、可嵌入任意项目的 AI 核心 + 叙事引擎 + TRPG 训练场。

> **发行名 vs 导入名**（PyPI 上 `easy-ai` / `easy_ai` / `easyai` 均已被他人占用，
> 且 `easya1` 会被 PyPI 判为与既有的 `easyai`「过于相似」而拒收，故发行名取 `peasy-ai`）：
>
> | 用途 | 名字 | 写法 |
> |---|---|---|
> | 安装 | **peasy-ai** | `pip install peasy-ai` |
> | 导入 | **easy_ai** | `import easy_ai` |
> | 命令行 | **peasy-ai** | `peasy-ai chat` |

仓库：<https://gitee.com/siwpan/peasy-ai> ｜ 许可：MIT（见 [LICENSE](LICENSE)）

> **仓库改名**：本仓库原为 `siwpan/easy-ai`，因 PyPI 发行名改为 `peasy-ai`
> （`easy-ai`/`easy_ai`/`easyai` 均被占用，`easya1` 被 PyPI 判为与 `easyai` 过于相似），
> 按既有做法**删仓重建**为 `siwpan/peasy-ai`，而非在旧仓上改名 —— 避免残留矛盾内容。
> 旧地址已失效且无重定向。

## 安装

```bash
pip install peasy-ai                 # 核心零依赖，纯标准库即可运行
pip install peasy-ai[all]             # 可选：numpy + jieba + scikit-learn
```

可选依赖按需安装：`[numpy]`（TextCNN / 神经网络匹配器）、`[jieba]`（中文分词增强）、
`[sklearn]`（TF-IDF 匹配器）。缺失时对应匹配器会优雅降级并给出警告，
**不会让 `create()` 起不来**。

## 命令行

```bash
peasy-ai --help                      # 查看所有子命令（等价于 python -m easy_ai --help）

peasy-ai chat                        # AI 闲聊（CLI）
peasy-ai chat --ui                   # AI 闲聊（tkinter GUI）
peasy-ai story                       # 叙事引擎（互动故事）
peasy-ai paotuan                     # 迷失之镜 TRPG 跑团
peasy-ai trpg dice 3d6+2             # TRPG 掷骰
peasy-ai trpg npc -n 3               # 随机 NPC
peasy-ai train                       # AI 训练模式（跑团事件 → 自动学习）
peasy-ai demo                        # 运行全部演示
```

## 核心用法

### 1. AICore — 零文件启动

```python
from easy_ai import AICore, create

ai = create()                       # 零参数，内置默认配置
ai.respond("你好")                   # → "你好呀！"

ai.learn("你最喜欢的颜色", "蓝色")     # 教 AI
ai.respond("你最喜欢的颜色")           # → "蓝色"

ai.set_safety(["密码", "密钥"])       # 安全过滤
ai.save("memory.json")               # 持久化
ai.load("memory.json")               # 恢复
```

> **属性 vs 方法**：`memory_count` / `cache_size` / `session_count` / `matchers_info`
> 是 `@property`，无括号访问（`ai.memory_count`）。
> 开关类方法（`enable_*` / `set_*` / `add_matcher` / `save` / `reload` / `load`）
> 均返回 `self`，支持链式：`ai.enable_sessions().set_safety(["密码"])`。

### 2. 配置文件驱动

```python
ai = AICore("path/to/config.json")  # 一切行为来自 JSON
ai.reload("path/to/my_chat.json")   # 热重载，不丢记忆
```

### 3. 会话式对话

```python
ai.enable_sessions()
ai.chat("user_123", "你好")
ai.chat("user_123", "我叫小明")
ai.chat("user_123", "我叫什么")       # AI 记住了上下文
```

### 4. 意图识别

```python
ai.enable_intent()
intent, confidence = ai.classify_intent("帮我查一下")   # → ("command", 0.8)
keywords = ai.extract_keywords("今天的天气真好")         # → [("天气", 0.5), ...]
```

### 5. 叙事引擎

```python
from easy_ai.engine.core import NarrativeEngine

engine = NarrativeEngine("data")     # 从 JSON 加载故事
scene = engine.get_current_scene()
options = engine.get_available_options()   # 条件过滤后的选项
engine.choose_option(0)               # 执行选项，跳转场景
engine.save("save.json")              # 存档
```

### 6. TRPG 训练 — AI 跟着跑团学知识

```python
from easy_ai import AICore
from easy_ai.trpg.trainer import AITrainer

ai = AICore()
trainer = AITrainer(ai)

trainer.on_scene_result("1.1_sound_source", "感知", 12, 10, False, "什么也没听到")
trainer.on_combat_event("巨鼠群", 15, "攻击", 5, "躯干", False)

ai.respond("感知检定是什么结果")       # → "失败：掷出12，目标10"
```

### 7. TRPG 工具

```python
from easy_ai.trpg.tools import roll, random_npc, random_quest

roll("3d6+2")                        # → (14, [6,3,3], "+2")
random_npc()                          # → {"name": "索菲亚·铁锤", ...}
```

## 目录结构

自 1.0.0 起为 **src 布局的命名空间包**：顶层不再出现 `ai/` `engine/` `ui/` 这类
通用名（避免污染 `site-packages`），全部收在 `easy_ai` 之下。

```
easy-ai/
├── src/easy_ai/             # 📦 发行内容（导入名 easy_ai）
│   ├── __init__.py          #   公共 API 重导出
│   ├── main.py              #   命令行主入口（peasy-ai / python -m easy_ai）
│   ├── ai/                  # 🧠 AI 大脑
│   │   ├── core.py          #     AICore — 主入口类
│   │   ├── config_loader.py #     JSON 配置加载与校验
│   │   ├── memory.py        #     可学习记忆库
│   │   ├── pipeline.py      #     响应管道（中间件链 + 置信度竞争）
│   │   ├── session.py       #     多轮对话会话管理
│   │   ├── intent.py        #     意图识别 + 关键词提取
│   │   ├── textcnn.py       #     手写 TextCNN（仅 numpy）
│   │   ├── eval/            #     评估框架：分词 / 语料 / perplexity 等指标
│   │   ├── matchers/        #     匹配器（Regex / Fuzzy / 马尔科夫 / 神经网络）
│   │   └── responders/      #     专用响应器（时间查询 / 数学计算）
│   ├── engine/              # 📖 叙事引擎（零硬编码分支剧情）
│   ├── trpg/                 # 🎲 TRPG 训练工具（骰子 / 随机表 / 训练器）
│   ├── ui/                   # 🖥 图形界面（tkinter 聊天窗口）
│   ├── paotuan/              # 🎭 内置「迷失之镜」TRPG 子应用（独立自举）
│   ├── config/               # 默认配置文件（随包分发）
│   └── data/                 # 示例数据（随包分发）
├── tests/                    # 127 项单元测试
├── tools/                    # 离线训练与基线评估脚本
└── docs/                     # 各阶段实测基线文档
```

## 设计原则

- **零硬编码**：所有规则、安全词、回复模板在 JSON 配置中定义
- **置信度竞争**：多匹配器并行，选最高置信度回复（非"首命中"）
- **管道可插拔**：安全→记忆→匹配→兜底，每阶段可独立启停
- **AI 训练场**：TRPG 不是独立系统，而是 AI 的训练数据生成器
- **零外部依赖**：核心功能纯 Python 标准库，可选依赖缺失时自动降级

## 实测基线

| 项 | 结果 |
|---|---|
| 语料规模 | 7,950 → 108,647 token（13.7×） |
| 扩语料前 CNN vs 马尔科夫 top-1 | 43.95% vs 34.81%（**+9.14pp**） |
| 扩语料后 CNN vs 马尔科夫 top-1 | 38.26% vs 19.00%（**+19.25pp**） |
| 重排序（1 正 + 9 负采样） | 随机 0% / Jaccard 60% / CNN 条件似然 40% |

复现方法见 `docs/BASELINE_P0.md` … `docs/E2E_NEURAL.md` 与 `tools/` 下的评估脚本。

## 开发

```bash
pip install -e .[dev]
python -m pytest tests -q          # 127 passed
```
