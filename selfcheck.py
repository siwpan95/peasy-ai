#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""peasy-ai 无头自检：TRPG 骰子 + 叙事引擎状态推进 + AI 记忆往返（不 import tkinter）。

本仓是 src 布局（导入名 ``easy_ai`` 在 ``src/easy_ai``），``.venv`` 里只装了可选依赖
numpy/jieba、并没有 pip install 本包，因此把项目自身的 ``src`` 加入 sys.path 即可。

不 import ``easy_ai.ui.*`` / ``paotuan.view.*``（tkinter 窗口）。验证点：
1. ``easy_ai.trpg.tools.DiceRoller``：XdY±M 的骰值范围与总和、4d6k3 保留最高 3 颗、
   非法表达式返回 (0, [], 说明)；
2. ``easy_ai.engine.core.NarrativeEngine``：从包内 data/config.json 加载场景，
   选择选项后场景跳转、回合数推进、属性发生变化；
3. ``easy_ai.create()``：learn() 写入后 respond() 能取回同一事实（记忆往返）。
"""
from __future__ import annotations

import logging
import random
import sys
from pathlib import Path

sys.dont_write_bytecode = True          # 不在项目里留 .pyc
try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

# easy_ai 的 logger 默认 INFO，会往 stdout 打初始化日志；自检只关心结果。
logging.disable(logging.CRITICAL)


class CheckError(RuntimeError):
    pass


def check(condition, message):
    if not condition:
        raise CheckError(message)


def check_dice(DiceRoller):
    random.seed(2026)
    total, rolls, _desc = DiceRoller.roll("3d6+2")
    check(len(rolls) == 3 and all(1 <= value <= 6 for value in rolls),
          f"3d6 骰值越界：{rolls!r}")
    check(total == sum(rolls) + 2, f"3d6+2 总和错误：{total} != {sum(rolls) + 2}")

    total, rolls, desc = DiceRoller.roll("4d6k3")
    check(len(rolls) == 3, f"4d6k3 应保留 3 颗骰子，实际 {len(rolls)}")
    check(rolls == sorted(rolls, reverse=True), f"4d6k3 未按高低排序：{rolls!r}")
    check(total == sum(rolls), f"4d6k3 总和错误：{total} != {sum(rolls)}")
    check("drop" in desc, f"4d6k3 缺少丢弃说明：{desc!r}")

    total, rolls, _desc = DiceRoller.roll("1d20-3")
    check(len(rolls) == 1 and 1 <= rolls[0] <= 20, f"1d20 骰值越界：{rolls!r}")
    check(total == rolls[0] - 3, f"1d20-3 总和错误：{total}")

    total, rolls, message = DiceRoller.roll("not-a-die")
    check(total == 0 and rolls == [] and "无效" in message,
          f"非法骰子表达式未被拒绝：{(total, rolls, message)!r}")


def check_narrative(NarrativeEngine):
    data_dir = ROOT / "src" / "easy_ai" / "data"
    check((data_dir / "config.json").is_file(), f"缺少叙事数据：{data_dir / 'config.json'}")
    engine = NarrativeEngine(data_path=str(data_dir))
    check(engine.current_scene_id == "prologue",
          f"初始场景不是 prologue：{engine.current_scene_id!r}")
    options = engine.get_available_options()
    check(len(options) >= 2, f"初始场景可用选项过少：{len(options)}")
    before_scene = engine.current_scene_id
    before_attrs = dict(engine.attributes)
    check(engine.choose_option(0) is True, "choose_option(0) 返回失败")
    check(engine.current_scene_id != before_scene,
          f"选择选项后场景未推进：仍为 {engine.current_scene_id!r}")
    check(engine.turn_count == 1, f"回合数未推进：{engine.turn_count}")
    check(engine.attributes != before_attrs,
          f"选择选项后属性未变化：{engine.attributes!r}")


def check_memory(create):
    ai = create()
    ai.learn("自检键", "自检值")
    reply = ai.respond("自检键")
    check("自检值" in reply, f"记忆往返失败：{reply!r}")


def main():
    from easy_ai.trpg.tools import DiceRoller
    from easy_ai.engine.core import NarrativeEngine
    from easy_ai import create

    check_dice(DiceRoller)
    check_narrative(NarrativeEngine)
    check_memory(create)
    print(
        "selfcheck ok: TRPG dice (3d6+2/4d6k3/1d20-3/invalid) + narrative engine "
        "(prologue -> option 0, turn+1, attrs change) + AICore learn/respond memory roundtrip"
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - 自检入口需要把任何失败转成 FAIL + 退出码 1
        print(f"FAIL: {type(exc).__name__}: {exc}")
        raise SystemExit(1)
