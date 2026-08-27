# easy-ai — 通用 AI 对话框架

零硬编码、配置驱动、可嵌入任意项目的 AI 核心 + 叙事引擎 + TRPG 训练场。

## 目录结构

```
easy-ai/
├── main.py              # 主入口（子命令：chat/story/paotuan/trpg/train/demo）
├── ai_core.py            # 向后兼容包装（SimpleAICore → AICore）
│
├── ai/                   # 🧠 AI 大脑
│   ├── core.py           #   AICore — 主入口类
│   ├── config_loader.py  #   JSON 配置加载与校验
│   ├── memory.py         #   可学习记忆库
│   ├── pipeline.py       #   响应管道（中间件链 + 置信度竞争）
│   ├── session.py        #   多轮对话会话管理
│   ├── intent.py         #   意图识别 + 关键词提取
│   ├── matchers/         #   匹配器（Regex + TF-IDF/Fuzzy）
│   └── responders/       #   专用响应器（时间查询 / 数学计算）
│
├── engine/               # 📖 叙事引擎（零硬编码分支剧情）
│   ├── core.py           #   事件调度 + 状态机 + 结局检查
│   ├── conditions.py     #   递归条件求值器（and/or/not）
│   ├── data_loader.py    #   JSON 场景/角色/配置加载
│   └── models.py         #   数据模型（Scene/Option/GameState）
│
├── trpg/                 # 🎲 TRPG 训练工具
│   ├── trainer.py        #   AI 训练器 — 游戏事件自动喂给 AICore
│   ├── tools.py          #   骰子解析 / 随机表 / 程序化内容生成
│   ├── adapter.py        #   叙事引擎 ↔ AI Core 适配桥
│   └── paotuan_gui.py    #   迷失之镜 TRPG 引擎 → GUI 集成
│
├── ui/                   # 🖥 图形界面
│   ├── interface.py      #   抽象 UI 基类
│   └── chat_ui.py        #   tkinter 类微信聊天窗口
│
├── paotuan/              #   内置迷失之镜 TRPG 引擎（GURPS 4e）
├── data/                 #   示例故事数据（星舰迷途）
└── config/               #   配置文件
    └── default.json      #   默认 AI 配置
```

## 快速开始

```bash
cd G:\repos\easy-ai

# 查看所有可用命令
python main.py --help

# AI 闲聊（CLI）
python main.py chat

# AI 闲聊（GUI 窗口）
python main.py chat --ui

# 叙事引擎（互动故事）
python main.py story

# 迷失之镜 TRPG 跑团
python main.py paotuan

# TRPG 工具：掷骰 / 随机 NPC / 任务 / 战利品
python main.py trpg dice 3d6+2
python main.py trpg npc -n 3
python main.py trpg quest
python main.py trpg loot -q rare

# AI 训练模式（跑团事件 → 自动学习）
python main.py train

# 运行所有演示（兼容旧行为）
python main.py demo
```

## 核心用法

### 1. AICore — 零文件启动

```python
import sys; sys.path.insert(0, 'G:/repos/easy-ai')
from ai.core import AICore

ai = AICore()                              # 零参数，内置默认配置
ai.respond("你好")                           # → "你好呀！"

ai.learn("你最喜欢的颜色", "蓝色")            # 教 AI
ai.respond("你最喜欢的颜色")                  # → "蓝色"

ai.set_safety(["密码", "密钥"])              # 安全过滤
ai.save("memory.json")                      # 持久化
ai.load("memory.json")                      # 恢复
```

### 2. 配置文件驱动

```python
ai = AICore("config/default.json")          # 一切行为来自 JSON
ai.reload("config/my_chat.json")            # 热重载，不丢记忆
```

### 3. 会话式对话

```python
ai.enable_sessions()
ai.chat("user_123", "你好")
ai.chat("user_123", "我叫小明")
ai.chat("user_123", "我叫什么")              # AI 记住了上下文
```

### 4. 意图识别

```python
ai.enable_intent()
intent, confidence = ai.classify_intent("帮我查一下")  # → ("command", 0.8)
keywords = ai.extract_keywords("今天的天气真好")       # → [("天气", 0.5), ...]
```

### 5. 叙事引擎

```python
from engine.core import NarrativeEngine
engine = NarrativeEngine("data")            # 从 JSON 加载故事
scene = engine.get_current_scene()
options = engine.get_available_options()     # 条件过滤后的选项
engine.choose_option(0)                      # 执行选项，跳转场景
engine.save("save.json")                     # 存档
```

### 6. TRPG 训练 — AI 跟着跑团学知识

```python
from ai.core import AICore
from trpg.trainer import AITrainer

ai = AICore()
trainer = AITrainer(ai)

# 游戏事件自动转化为 AI 知识
trainer.on_scene_result("1.1_sound_source", "感知", 12, 10, False, "什么也没听到")
trainer.on_combat_event("巨鼠群", 15, "攻击", 5, "躯干", False)

ai.respond("感知检定是什么结果")             # → "失败：掷出12，目标10"
ai.respond("如何对付巨鼠群")                 # → "使用攻击战术，造成了5点伤害"
```

### 7. TRPG 工具

```python
from trpg.tools import roll, random_npc, random_quest

roll("3d6+2")                               # → (14, [6,3,3], "+2")
random_npc()                                 # → {"name": "索菲亚·铁锤", ...}
random_quest()                               # → {"title": "前往古老神殿寻找...", ...}
```

## 设计原则

- **零硬编码**：所有规则、安全词、回复模板在 JSON 配置中定义
- **置信度竞争**：多匹配器并行，选最高置信度回复（非"首命中"）
- **管道可插拔**：安全→记忆→匹配→兜底，每阶段可独立启停
- **AI 训练场**：TRPG 不是独立系统，而是 AI 的训练数据生成器
- **零外部依赖**：核心功能纯 Python 标准库

## 依赖

全部可选，零硬性要求：

```
pip install -r requirements.txt   # jieba, scikit-learn, numpy（TF-IDF 增强）
```

> tkinter 为 GUI 所需，Python 安装时通常自带。

## 运行模式

| 命令 | 说明 |
|------|------|
| `python main.py --help` | 查看所有子命令 |
| `python main.py chat` | AI 闲聊（CLI 交互） |
| `python main.py chat --ui` | AI 闲聊（tkinter GUI） |
| `python main.py story` | 叙事引擎（互动故事 CLI） |
| `python main.py story --ui` | 叙事引擎（GUI 窗口） |
| `python main.py paotuan` | 迷失之镜 TRPG 跑团 |
| `python main.py trpg dice 3d6` | TRPG 掷骰工具 |
| `python main.py trpg npc` | TRPG 随机 NPC 生成 |
| `python main.py train` | AI 训练模式 |
| `python main.py demo` | 运行全部演示（兼容旧行为） |
| `--log-level DEBUG` | 任意子命令均可附加调试日志 |

> 所有模块已从主入口 `main.py` 统一连接，无需单独运行各模块脚本。
