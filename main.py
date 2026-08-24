"""
easy-ai 主入口：连接所有功能模块。

用法：
  python main.py chat              # AI 闲聊（CLI）
  python main.py chat --ui        # AI 闲聊（GUI 窗口）
  python main.py chat --ai-mode   # AI 知识模式（增强配置）
  python main.py story            # 叙事引擎（互动故事 CLI）
  python main.py story --ui       # 叙事引擎（GUI 窗口）
  python main.py paotuan          # 迷失之镜 TRPG 跑团
  python main.py trpg dice 3d6   # TRPG 工具：掷骰
  python main.py trpg npc            # TRPG 工具：随机 NPC
  python main.py trpg quest          # TRPG 工具：随机任务
  python main.py trpg loot          # TRPG 工具：随机战利品
  python main.py train             # AI 训练模式（跑团 → 知识）
  python main.py ai-knowledge      # AI 知识问答模式
  python main.py neural-train      # 训练神经网络意图分类器
  python main.py markov-demo       # 马尔科夫链演示
  python main.py demo             # 运行所有演示（兼容旧行为）

修复历史：
  v3.0.0 (2026-06-28): 从 demo 脚本重构为子命令主入口，连接所有模块。
  v3.1.0 (2026-07-04): 新增 AI 知识模式、神经网络训练、马尔科夫链演示。
  v2.4.0: 添加命令行参数、日志配置、异步接口演示。
"""

import argparse
import logging
import os
import sys
from pathlib import Path

# ── 动态路径检测 ─────────────────────────────────────────────
def _detect_project_root() -> Path:
    current = Path(__file__).parent.absolute()
    for p in [current] + list(current.parents):
        if (p / "ai").exists() or (p / "engine").exists():
            return p
    return current

PROJECT_ROOT = _detect_project_root()
sys.path.insert(0, str(PROJECT_ROOT))

from ai.logger import setup_logging, get_logger


# ═══════════════════════════════════════════════════════════
# 通用工具
# ═══════════════════════════════════════════════════════════

def _create_ai(config_path=None):
    """创建 AICore 实例。"""
    from ai.core import create
    if config_path is None:
        p = PROJECT_ROOT / "config" / "default.json"
        config_path = str(p) if p.exists() else None
    return create(config_path)


def _create_engine(data_path=None):
    """创建 NarrativeEngine 实例。"""
    from engine.core import NarrativeEngine
    if data_path is None:
        data_path = str(PROJECT_ROOT / "data")
    cfg = str(PROJECT_ROOT / "config" / "default.json")
    return NarrativeEngine(data_path=data_path, config_file=os.path.basename(cfg))


# ═══════════════════════════════════════════════════════════
# 子命令实现
# ═══════════════════════════════════════════════════════════

def cmd_chat(args):
    """AI 闲聊（CLI 或 GUI）。"""
    # 支持 AI 知识模式：加载增强配置
    config_path = None
    if getattr(args, 'ai_mode', False):
        config_path = str(PROJECT_ROOT / "config" / "ai_knowledge.json")
        print("[info] 已加载 AI 知识增强配置")

    ai = _create_ai(config_path=config_path)
    ai.enable_sessions()
    session_id = args.session or "cli_user"

    if args.ui:
        # GUI 模式：启动 ChatUI
        from ui.chat_ui import ChatUI

        def on_option(index):
            pass  # 闲聊模式无选项

        def on_free_text(text):
            reply = ai.chat(session_id, text)
            ui.add_ai_message(reply)

        ui = ChatUI(title="easy-ai 闲聊", on_option=on_option, on_free_text=on_free_text)
        # 发送欢迎消息
        ui.after(100, lambda: ui.add_ai_message("你好！我是 AI 助手，有什么可以帮你的吗？"))
        ui.run()
    else:
        # CLI 模式
        print("=" * 60)
        print("easy-ai 闲聊模式（输入 'quit' / 'exit' / 'q' / '退出' 结束）")
        print("=" * 60)
        while True:
            try:
                user_input = input("你：").strip()
                if user_input.lower() in ["quit", "exit", "q", "退出"]:
                    print("再见！")
                    break
                if not user_input:
                    continue
                reply = ai.chat(session_id, user_input)
                print(f"AI：{reply}")
            except (KeyboardInterrupt, EOFError):
                print("\n再见！")
                break


def cmd_story(args):
    """叙事引擎（互动故事）。"""
    engine = _create_engine()
    ai = _create_ai() if args.ai else None

    if args.ui:
        # GUI 模式
        from ui.chat_ui import ChatUI

        def render_current():
            scene = engine.get_current_scene()
            if not scene:
                ui.show_ending("故事已结束。")
                return
            opts = engine.get_available_options()
            ui.show_attributes(engine.attributes)
            ui.show_scene(
                speaker_name=scene.speaker or "旁白",
                speaker_avatar=None,
                text=scene.text,
                options=[{"text": o.text, "index": i} for i, o in enumerate(opts)]
            )

        def on_option(index):
            opts = engine.get_available_options()
            if 0 <= index < len(opts):
                engine.choose_option(opts[index].id)
                render_current()

        def on_free_text(text):
            if ai:
                reply = ai.respond(text)
                ui.add_ai_message(reply)
            else:
                ui.add_ai_message("（AI 未启用，无法闲聊。用 --ai 启动可启用 AI 伴聊。）")

        ui = ChatUI(title=engine.title or "easy-ai 互动故事", on_option=on_option, on_free_text=on_free_text)
        render_current()
        ui.run()
    else:
        # CLI 模式
        print("=" * 60)
        print(f"故事：{engine.title}")
        print(f"当前场景：{engine.current_scene_id}")
        print("=" * 60)

        while True:
            scene = engine.get_current_scene()
            if not scene:
                print("\n【故事结束】")
                break

            print(f"\n── {scene.id} ──")
            print(f"  {scene.speaker or '旁白'}：{scene.text}")

            opts = engine.get_available_options()
            if not opts:
                print("\n（没有可用选项，故事结束。）")
                break

            print("\n选项：")
            for i, o in enumerate(opts):
                print(f"  {i}. {o.text}")
            print("  q. 退出")

            choice = input("\n请选择：").strip().lower()
            if choice == "q":
                print("再见！")
                break
            try:
                idx = int(choice)
                if 0 <= idx < len(opts):
                    engine.choose_option(opts[idx].id)
                else:
                    print("  无效编号。")
            except ValueError:
                print("  请输入数字或 'q'。")


def cmd_paotuan(args):
    """迷失之镜 TRPG 跑团。"""
    launcher_path = PROJECT_ROOT / "paotuan" / "mirror_launcher.py"
    if not launcher_path.exists():
        print(f"错误：找不到迷失之镜启动器（{launcher_path}）")
        sys.exit(1)

    # 将 paotuan 目录加入 sys.path 并启动
    paotuan_dir = str(PROJECT_ROOT / "paotuan")
    if paotuan_dir not in sys.path:
        sys.path.insert(0, paotuan_dir)

    import importlib.util
    spec = importlib.util.spec_from_file_location("mirror_launcher", launcher_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.MirrorLauncher().run()


def cmd_trpg(args):
    """TRPG 工具箱。"""
    from trpg.tools import DiceRoller, RandomTables, ProceduralGen, roll, random_npc, random_quest, random_loot

    sub = args.trpg_cmd

    if sub == "dice":
        notation = args.notation or "3d6"
        total, results, desc = DiceRoller.roll(notation)
        print(f"[掷骰] {notation} = {total}")
        print(f"   掷骰结果：{results}")
        print(f"   修饰：{desc}")

    elif sub == "npc":
        count = args.count or 1
        for _ in range(count):
            npc = random_npc()
            print(f"\n[NPC] {npc['name']}")
            print(f"   特质：{npc['trait']}")
            print(f"   职业：{npc['occupation']}")
            print(f"   心情：{npc['mood']}")
            print(f"   秘密：{npc['secret']}")

    elif sub == "quest":
        count = args.count or 1
        for _ in range(count):
            q = random_quest()
            print(f"\n[任务] {q['title']}")
            print(f"   类型：{q['type']}  地点：{q['location']}")
            print(f"   奖励：{q['reward']}")

    elif sub == "loot":
        quality = args.quality or "common"
        count = args.count or 1
        for _ in range(count):
            item = random_loot(quality)
            print(f"[战利品] {item}")

    elif sub == "place":
        count = args.count or 1
        for _ in range(count):
            from trpg.tools import ProceduralGen
            print(f"[地点] {ProceduralGen.place_name()}")

    elif sub == "enemy":
        count = args.count or 1
        for _ in range(count):
            e = ProceduralGen.enemy()
            print(f"\n[敌人] {e['name']}")
            print(f"   CR：{e['cr']}  战术：{e['tactic']}")

    else:
        print("用法：python main.py trpg {dice|npc|quest|loot|place|enemy} [选项]")
        print("  dice [表达式]     掷骰（默认 3d6）")
        print("  npc [-n 数量]      生成随机 NPC")
        print("  quest [-n 数量]    生成随机任务")
        print("  loot [-q 品质]     生成随机战利品")
        print("  place [-n 数量]    生成随机地名")
        print("  enemy [-n 数量]    生成随机敌人")


def cmd_train(args):
    """AI 训练模式：跑团事件 → AICore 知识。"""
    import random
    from ai.core import AICore
    from trpg.trainer import AITrainer
    from trpg.tools import DiceRoller, RandomTables

    ai = AICore()
    trainer = AITrainer(ai)

    print("=" * 60)
    print("AI 训练模式（模拟跑团事件 → 自动学习）")
    print("=" * 60)

    # 模拟几轮跑团事件
    print("\n--- 模拟场景检定 ---")
    scenes = [
        ("1.1", "感知", "听到墙后传来微弱的抓挠声……"),
        ("1.2", "潜行", "你悄无声息地潜入了营地。"),
        ("2.1", "近战", "刀锋相交，火花四溅！"),
    ]
    for node_id, skill, narrative in scenes:
        roll_val, dice, _ = DiceRoller.roll("3d6")
        target = 12
        success = roll_val <= target
        print(f"  场景 {node_id}：{skill}检定 掷出{roll_val} vs 目标{target} → {'成功' if success else '失败'}")
        trainer.on_scene_result(node_id, skill, roll_val, target, success, narrative)

    print("\n--- 模拟战斗事件 ---")
    enemies = ["巨鼠", "哥布林哨兵", "亡灵守卫"]
    for enemy in enemies:
        hp = random.randint(10, 30)  # noqa: F821
        action = "劈砍"
        dmg = random.randint(3, 12)  # noqa: F821
        print(f"  与 {enemy}（HP{hp}）战斗：使用{action}造成{dmg}点伤害")
        trainer.on_combat_event(enemy, hp, action, dmg, "躯干", killed=(dmg > hp))

    print("\n--- 模拟角色加载 ---")
    char = {
        "name": "全哥",
        "st": 12, "dx": 13, "iq": 14, "ht": 11,
        "skills": [
            {"name": "调查", "level": 14, "difficulty": "Average"},
            {"name": "潜行", "level": 13, "difficulty": "Average"},
        ],
        "equipment": ["短剑", "皮甲", "火把"],
    }
    trainer.on_character_load(char)

    print("\n--- 训练完成，测试 AI ---")
    test_q = ["感知检定是什么结果", "如何对付巨鼠", "全哥的属性是什么"]
    for q in test_q:
        print(f"  Q: {q}")
        print(f"  A: {ai.respond(q)}")

    # 导出训练日志
    log_path = str(PROJECT_ROOT / "data" / "training_log.json")
    trainer.export_training_log(log_path)
    print(f"\n训练日志已导出：{log_path}")
    print(f"摘要：{trainer.summary}")


def cmd_ai_knowledge(args):
    """AI 知识问答模式：加载 AI 知识库进行专业问答。"""
    from ai.core import AICore
    import json

    config_path = str(PROJECT_ROOT / "config" / "ai_knowledge.json")
    training_path = str(PROJECT_ROOT / "data" / "ai_training.json")

    print("=" * 60)
    print("easy-ai AI 知识问答模式")
    print("=" * 60)

    # 创建 AI 并加载知识
    ai = AICore(config_path)
    print(f"  AI 版本：{ai.version}")

    # 加载预训练记忆
    if os.path.exists(training_path):
        ai.load(training_path)
        print(f"  已加载 {ai.memory_count} 条 AI 知识记忆")

    ai.enable_sessions()
    session_id = "knowledge_user"

    print("\n我已准备就绪！可以问我关于以下主题的问题：")
    print("  - 人工智能 / 机器学习 / 深度学习")
    print("  - 神经网络 / CNN / RNN / Transformer")
    print("  - NLP / CV / GAN / 强化学习")
    print("  - 大语言模型 / Prompt 工程 / RAG")
    print("  - 监督学习 / 无监督学习 / 过拟合")
    print("  - 以及更多 AI 相关话题...")
    print("\n输入 'quit' 或 'exit' 退出，输入 'learn 问:xxx 答:yyy' 教我新知识")
    print("=" * 60)

    while True:
        try:
            user_input = input("\n你：").strip()
            if user_input.lower() in ["quit", "exit", "q", "退出"]:
                print("再见！期待下次继续探讨 AI~")
                break
            if not user_input:
                continue

            # 手动教学模式
            if user_input.startswith("learn "):
                content = user_input[6:].strip()
                parts = content.split("答:", 1)
                if len(parts) == 2:
                    q = parts[0].replace("问:", "").replace("问：", "").strip()
                    a = parts[1].strip()
                    if q and a and ai.learn(q, a):
                        print(f"[学习] 已记住：「{q[:30]}」→「{a[:50]}」")
                    else:
                        print("[学习] 这条我已经知道了~")
                else:
                    print("[格式] learn 问:问题 答:答案")
                continue

            # 查看记忆统计
            if user_input == "/stats":
                info = ai.get_info()
                print(f"[统计] 记忆数={info['memory_count']} 会话数={info['session_count']}")
                print(f"[统计] 匹配器={[m['name'] for m in info['matchers']]}")
                continue

            # 搜索记忆
            if user_input.startswith("/search "):
                keyword = user_input[8:].strip()
                results = ai.search_memory(keyword)
                if results:
                    print(f"[搜索] 与「{keyword}」相关的问题（{len(results)} 条）：")
                    for i, r in enumerate(results[:10]):
                        print(f"  {i+1}. {r}")
                else:
                    print(f"[搜索] 未找到与「{keyword}」相关的问题")
                continue

            reply = ai.chat(session_id, user_input)
            print(f"AI：{reply}")

        except (KeyboardInterrupt, EOFError):
            print("\n再见！")
            break


def cmd_markov_demo(args):
    """马尔科夫链文本生成演示。"""
    from ai.matchers.markov_chain import MarkovChain, MarkovMatcher

    print("=" * 60)
    print("马尔科夫链文本生成演示")
    print("=" * 60)

    # 用 AI 知识语料训练马尔科夫链
    corpus = [
        "人工智能是计算机科学的重要分支，致力于让机器模拟人类智能。",
        "机器学习是人工智能的核心，通过数据训练让模型自动学习规律。",
        "深度学习使用多层神经网络，可以自动提取数据的高层特征。",
        "卷积神经网络在图像识别领域取得了突破性进展。",
        "Transformer架构通过自注意力机制实现了并行化处理。",
        "大语言模型如GPT和DeepSeek可以理解和生成自然语言。",
        "强化学习通过与环境交互，学习最优的决策策略。",
        "自然语言处理让计算机能够理解人类语言的语义和情感。",
        "计算机视觉技术让机器能够识别图像中的物体和场景。",
        "生成对抗网络由生成器和判别器组成，可以生成逼真的图像。",
        "监督学习需要标注数据来训练模型进行分类或回归。",
        "无监督学习从无标签数据中发现隐藏的模式和结构。",
        "过拟合是机器学习中常见的问题，可以通过正则化来解决。",
        "梯度下降算法是神经网络训练的核心优化方法。",
        "激活函数为神经网络引入了非线性变换能力。",
        "交叉熵损失函数常用于分类任务的训练。",
        "RAG技术结合了信息检索和文本生成，可以减少幻觉。",
        "嵌入向量将文本映射到高维空间，捕捉语义相似性。",
        "循环神经网络的LSTM变体解决了长序列依赖问题。",
        "Dropout是一种常用的正则化技术，防止神经网络过拟合。",
    ]

    # 不同 n-gram 级别的演示
    for n in [2, 3, 4]:
        print(f"\n── N={n} 马尔科夫链 ──")
        mc = MarkovChain(n=n)
        mc.train(corpus)
        print(f"  词汇量：{mc.vocab_size}  状态数：{mc.total_states}")

        for temp in [0.5, 0.8, 1.2]:
            print(f"\n  [温度={temp}]")
            for i in range(3):
                generated = mc.sample(start="人工智能", max_length=60, temperature=temp)
                print(f"    {i+1}. {generated}")

    # 演示 MarkovMatcher 集成
    print("\n── MarkovMatcher 集成演示 ──")
    matcher = MarkovMatcher({"n_gram": 3, "temperature": 0.8})
    matcher._model.train(corpus)
    print(f"  模型：{matcher}")

    test_inputs = ["什么是深度学习", "神经网络如何训练", "NLP的应用"]
    for t in test_inputs:
        result = matcher.match(t, [])
        if result:
            print(f"  输入：「{t}」-> 生成：「{result.reply[:60]}...」(置信度={result.confidence:.2f})")
        else:
            print(f"  输入：「{t}」-> 无匹配")

    print("\n演示完成。")


def cmd_neural_train(args):
    """训练神经网络意图分类器。"""
    from ai.neural import NeuralIntentClassifier, check_numpy

    if not check_numpy():
        print("错误：NumPy 未安装。请运行 pip install numpy 后重试。")
        return

    print("=" * 60)
    print("神经网络意图分类器训练")
    print("=" * 60)

    # 准备训练数据
    training_data = {
        "greeting": [
            "你好", "嗨", "hello", "你好呀", "在吗", "哈喽",
            "早上好", "晚上好", "大家好", "好久不见",
        ],
        "farewell": [
            "再见", "拜拜", "bye", "下次见", "晚安", "回见",
            "走了", "先下了", "回头聊", "改天见",
        ],
        "question": [
            "什么是人工智能", "机器学习怎么学", "CNN的原理是什么",
            "如何入门AI", "Transformer怎么工作的", "什么是深度学习",
            "NLP是什么", "怎么训练模型", "梯度下降是什么",
            "为什么用Python做AI",
        ],
        "command": [
            "帮我算一下", "查一下天气", "打开文件", "保存数据",
            "生成报告", "运行代码", "解释一下", "翻译这段话",
        ],
        "statement": [
            "今天的天气不错", "我觉得AI会改变世界", "Python很好用",
            "这个项目很有趣", "深度学习的进展很快", "NLP越来越重要了",
        ],
        "emotion": [
            "太棒了", "好难过", "真开心", "气死我了", "好紧张",
            "太感动了", "烦死了", "好期待", "真厉害", "加油",
        ],
        "help": [
            "帮帮我", "救命", "怎么用", "我不懂", "出错了",
            "卡住了", "不会弄", "求助", "救命啊", "这是什么情况",
        ],
    }

    texts = []
    labels = []
    for intent, examples in training_data.items():
        for text in examples:
            texts.append(text)
            labels.append(intent)

    print(f"训练数据：{len(texts)} 条，{len(training_data)} 个类别")
    print(f"类别：{list(training_data.keys())}")

    # 训练分类器
    clf = NeuralIntentClassifier(intents=list(training_data.keys()))
    history = clf.train(texts, labels, epochs=200, lr=0.05, verbose=True)

    # 测试
    print("\n── 测试分类器 ──")
    test_cases = [
        ("你好呀，好久不见", "greeting"),
        ("什么是卷积神经网络", "question"),
        ("帮我翻译一下这段话", "command"),
        ("今天真的好开心啊", "emotion"),
        ("我不懂这个怎么用", "help"),
        ("拜拜，明天见", "farewell"),
        ("我觉得深度学习很有趣", "statement"),
    ]

    correct = 0
    for text, expected in test_cases:
        intent, conf = clf.classify(text)
        ok = "✓" if intent == expected else f"✗ (期望:{expected})"
        print(f"  {ok} 「{text}」-> {intent} (置信度={conf:.2f})")
        if intent == expected:
            correct += 1

    print(f"\n准确率：{correct}/{len(test_cases)} = {correct/len(test_cases)*100:.1f}%")

    # 演示 Top-K 分类
    print("\n── Top-3 分类演示 ──")
    for text in ["什么是Transformer架构", "救命我搞不定了"]:
        top3 = clf.classify_top_k(text, k=3)
        print(f"  「{text}」:")
        for intent, conf in top3:
            print(f"    {intent}: {conf:.2f}")

    # 保存模型
    model_path = str(PROJECT_ROOT / "data" / "intent_classifier.json")
    clf.save(model_path)

    print("\n训练完成。模型已保存到 data/intent_classifier.json")


def cmd_demo(args):
    """运行所有演示（兼容 v2.x 行为）。"""
    print("=" * 60)
    print("easy-ai 全功能演示")
    print("=" * 60)

    # AICore 演示
    print("\n── AICore 演示 ──")
    ai = _create_ai()
    print(f"  AI 名称：{ai.name}")
    print(f"  记忆数：{ai.memory_count}")
    for msg in ["你好", "你叫什么名字"]:
        print(f"  用户：{msg}")
        print(f"  AI：{ai.respond(msg)}")

    # 叙事引擎演示
    print("\n── NarrativeEngine 演示 ──")
    try:
        engine = _create_engine()
        print(f"  故事标题：{engine.title}")
        scene = engine.get_current_scene()
        if scene:
            print(f"  当前场景：{scene.id}")
            print(f"  文本：{scene.text[:60]}...")
    except Exception as e:
        print(f"  （叙事引擎演示跳过：{e}）")

    # TRPG 工具演示
    print("\n── TRPG 工具演示 ──")
    from trpg.tools import DiceRoller, RandomTables, ProceduralGen
    print(f"  掷骰 3d6：{DiceRoller.roll('3d6')[0]}")
    print(f"  随机 NPC：{RandomTables.npc_name()}")
    print(f"  随机地名：{ProceduralGen.place_name()}")

    # 马尔科夫链演示
    print("\n── 马尔科夫链演示 ──")
    from ai.matchers.markov_chain import MarkovChain
    mc = MarkovChain(n=3)
    mc.train([
        "人工智能是计算机科学的分支，致力于创造智能系统。",
        "机器学习让计算机从数据中学习，无需显式编程。",
        "深度学习是机器学习的一种方法，使用多层神经网络。",
        "自然语言处理让机器理解人类语言。",
    ])
    print(f"  N=3 词汇量={mc.vocab_size} 状态数={mc.total_states}")
    gen = mc.sample(start="人工智能", max_length=40, temperature=0.8)
    print(f"  生成：「{gen}」")

    # 神经网络演示
    print("\n── 神经网络演示 ──")
    from ai.neural import check_numpy
    if check_numpy():
        print("  NumPy 已安装，神经网络模块可用。")
        print("  运行 'python main.py neural-train' 训练意图分类器。")
    else:
        print("  NumPy 未安装，神经网络模块不可用。")
        print("  安装：pip install numpy")

    print("\n" + "=" * 60)
    print("演示完成。")
    print("提示：使用子命令可获得完整功能，如：")
    print("  python main.py chat --ai-mode  # AI 知识增强问答")
    print("  python main.py ai-knowledge     # AI 知识问答模式")
    print("  python main.py markov-demo      # 马尔科夫链演示")
    print("  python main.py neural-train     # 神经网络训练")
    print("  python main.py story            # 互动故事")
    print("  python main.py paotuan          # 迷失之镜 TRPG")
    print("=" * 60)


# ═══════════════════════════════════════════════════════════
# 命令行参数解析
# ═══════════════════════════════════════════════════════════

def build_parser():
    parser = argparse.ArgumentParser(
        prog="easy-ai",
        description="easy-ai 主入口：AI 对话 · 叙事引擎 · TRPG 跑团 · 训练场",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # ── chat ────────────────────────────────────────────────
    p_chat = subparsers.add_parser("chat", help="AI 闲聊（CLI 或 GUI）")
    p_chat.add_argument("--session", default="cli_user", help="会话 ID（默认：cli_user）")
    p_chat.add_argument("--ui", action="store_true", help="启动 GUI 窗口")
    p_chat.add_argument("--ai-mode", action="store_true", help="加载 AI 增强知识配置")

    # ── story ───────────────────────────────────────────────
    p_story = subparsers.add_parser("story", help="叙事引擎（互动故事）")
    p_story.add_argument("--ui", action="store_true", help="启动 GUI 窗口")
    p_story.add_argument("--ai", action="store_true", help="启用 AI 伴聊（场景外自由对话）")
    p_story.add_argument("--data", default=None, help="故事数据目录路径")

    # ── paotuan ─────────────────────────────────────────────
    p_paotuan = subparsers.add_parser("paotuan", help="迷失之镜 TRPG 跑团")

    # ── trpg ────────────────────────────────────────────────
    p_trpg = subparsers.add_parser("trpg", help="TRPG 工具箱（掷骰/随机生成）")
    trpg_sub = p_trpg.add_subparsers(dest="trpg_cmd", help="工具子命令")

    p_dice = trpg_sub.add_parser("dice", help="掷骰")
    p_dice.add_argument("notation", nargs="?", default="3d6", help="骰子表达式（如 3d6+2）")

    p_npc = trpg_sub.add_parser("npc", help="生成随机 NPC")
    p_npc.add_argument("-n", "--count", type=int, default=1, help="生成数量")

    p_quest = trpg_sub.add_parser("quest", help="生成随机任务")
    p_quest.add_argument("-n", "--count", type=int, default=1, help="生成数量")

    p_loot = trpg_sub.add_parser("loot", help="生成随机战利品")
    p_loot.add_argument("-q", "--quality", default="common", help="品质（poor/common/uncommon/rare/legendary）")
    p_loot.add_argument("-n", "--count", type=int, default=1, help="生成数量")

    p_place = trpg_sub.add_parser("place", help="生成随机地名")
    p_place.add_argument("-n", "--count", type=int, default=1, help="生成数量")

    p_enemy = trpg_sub.add_parser("enemy", help="生成随机敌人")
    p_enemy.add_argument("-n", "--count", type=int, default=1, help="生成数量")

    # ── train ───────────────────────────────────────────────
    p_train = subparsers.add_parser("train", help="AI 训练模式（跑团 → 知识）")

    # ── ai-knowledge ────────────────────────────────────────
    p_ai_knowledge = subparsers.add_parser("ai-knowledge", help="AI 知识问答模式")

    # ── markov-demo ─────────────────────────────────────────
    p_markov = subparsers.add_parser("markov-demo", help="马尔科夫链文本生成演示")

    # ── neural-train ────────────────────────────────────────
    p_neural = subparsers.add_parser("neural-train", help="训练神经网络意图分类器")

    # ── demo ────────────────────────────────────────────────
    p_demo = subparsers.add_parser("demo", help="运行所有演示（兼容旧行为）")

    # ── 全局选项 ────────────────────────────────────────────
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                       default="INFO", help="日志级别（默认：INFO）")
    parser.add_argument("--log-file", type=str, default=None, help="日志文件路径")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    # 初始化日志
    log_level = getattr(logging, args.log_level)
    setup_logging(level=log_level, log_file=args.log_file, verbose=(args.log_level == "DEBUG"))
    logger = get_logger("main")
    logger.info("easy-ai 启动，命令=%s", args.command)

    # 无命令时显示帮助
    if not args.command:
        parser.print_help()
        sys.exit(0)

    # 调度子命令
    handlers = {
        "chat": cmd_chat,
        "story": cmd_story,
        "paotuan": cmd_paotuan,
        "trpg": cmd_trpg,
        "train": cmd_train,
        "ai-knowledge": cmd_ai_knowledge,
        "markov-demo": cmd_markov_demo,
        "neural-train": cmd_neural_train,
        "demo": cmd_demo,
    }

    try:
        handlers[args.command](args)
    except Exception as e:
        logger.error("执行失败：%s", e, exc_info=True)
        print(f"\n错误：{e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
