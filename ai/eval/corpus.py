"""
语料加载与留出集划分。

设计口径对齐 `weiqi_lab/tools/eval_model.mjs`：
- **按文档（局面/局）划分**，而不是按 token 随机划分 —— 随机划分会把同一句的
  上下文泄漏进训练集，让 perplexity 虚低。
- 前 80% 训练 / 后 20% 留出，划分结果**确定性可复现**。

项目内的真实事件流来源（按可信度排序）：
1. `data/training_log.json` — TRPG 跑团事件流（question/answer 真实配对）
2. `data/ai_training.json` — AI 记忆库（问题 → 答案）
3. `data/scenes/*.json`    — 叙事场景（旁白 + 玩家选项）
4. `paotuan/**`            — 迷失之镜 TRPG 模组（P1 新增，最大的未利用语料）
5. `config/default.json`   — 规则库（旧语料，仅作对照基线）

**P1 的关键来源**是第 4 项：TRPG 模组里 `node.trigger`（玩家动作，如"调查滴水声"）
与 `layer_narrative.anchor_phrases`（GM 叙述，如"你轻敲砖块，一道金属嗡鸣回传"）
天然构成**真实发生过的对话轮次** —— 比规则库的模板串烧高一个量级。
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .tokenize import tokenize


# 递归抽取时要跳过的键：这些是标识符/元数据，不是叙述文本
_SKIP_KEYS = frozenset({
    "id", "ids", "key", "keys", "node_id", "scene_id", "module_id", "next_nodes",
    "prerequisite_nodes", "version", "author", "license", "path", "file",
    "source", "based_on", "compatible_core", "release_date", "tags",
})

_CJK_RE = re.compile(r'[\u4e00-\u9fff]')


def _has_cjk(s: str) -> bool:
    return bool(_CJK_RE.search(s))


def _read_json(fp: Path) -> Any:
    try:
        return json.loads(fp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


@dataclass
class QAPair:
    """一条问答对：用户说了什么，AI 答了什么。"""
    question: str
    answer: str
    source: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Corpus:
    """语料容器。

    - `texts`：纯文本文档，用于语言建模（perplexity / top-k）。
    - `pairs`：问答对，用于对话建模（用户语料与 AI 语料必须分开训）。
    """
    name: str = "corpus"
    texts: List[str] = field(default_factory=list)
    pairs: List[QAPair] = field(default_factory=list)

    # ---------- 构造 ----------
    @classmethod
    def from_easy_ai(cls, root: Optional[str] = None,
                     include_rules: bool = True,
                     include_paotuan: bool = True,
                     include_web: bool = True) -> "Corpus":
        """从 easy-ai 项目自身的真实事件流构建语料。

        Args:
            root: 项目根目录，默认按本文件位置推导（ai/eval/ → 上两级）。
            include_rules: 是否并入规则库作为对照源。
            include_paotuan: 是否并入 paotuan/ TRPG 模组（P1 新增的主力语料）。
            include_web: 是否并入联网抓取的语料（`.cache/corpus_web.jsonl`，
                由 `tools/fetch_corpus.py` 生成；**不入仓**，缺失时静默跳过）。
        """
        if root is None:
            root = str(Path(__file__).resolve().parents[2])
        root_p = Path(root)

        texts: List[str] = []
        pairs: List[QAPair] = []

        # ① TRPG 跑团事件流（最可信：真实发生过的问答）
        pairs += cls._load_training_log(root_p / "data" / "training_log.json")

        # ② AI 记忆库
        pairs += cls._load_memories(root_p / "data" / "ai_training.json")

        # ③ 叙事场景：旁白作纯文本；「玩家选项 → 下一场景旁白」作问答对
        scene_dir = root_p / "data" / "scenes"
        if scene_dir.is_dir():
            scene_by_id: Dict[str, str] = {}
            raw_scenes: List[dict] = []
            for fp in sorted(scene_dir.glob("*.json")):
                try:
                    d = json.loads(fp.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                raw_scenes.append(d)
                if d.get("text"):
                    texts.append(d["text"])
                    scene_by_id[d.get("id", "")] = d["text"]
            # 选项 → 目标场景旁白，构成一轮真实交互
            for d in raw_scenes:
                for opt in d.get("options", []):
                    otext = opt.get("text", "")
                    if otext:
                        texts.append(otext)
                    nxt = scene_by_id.get(opt.get("next", ""), "")
                    if otext and nxt:
                        pairs.append(QAPair(otext, nxt, source="scene",
                                            meta={"from": d.get("id", "")}))

        # ④ TRPG 模组（P1 新增：最大的未利用真实语料）
        if include_paotuan:
            p_texts, p_pairs = cls._load_paotuan(root_p / "paotuan")
            texts += p_texts
            pairs += p_pairs

        # ⑤ 联网语料（P3：把语料规模从 7950 提到 10 万 token）
        if include_web:
            texts += cls._load_web(root_p / ".cache" / "corpus_web.jsonl")

        # ⑥ 规则库（旧语料，仅作对照）
        if include_rules:
            pairs += cls._load_rules(root_p / "config" / "default.json")

        return cls(name="easy-ai", texts=texts, pairs=pairs)

    @staticmethod
    def _load_web(fp: Path) -> List[str]:
        """加载联网抓取的语料（JSONL，每行 {source,title,text}）。

        纯文本文档，无问答结构，故只进 `texts` 不进 `pairs`。
        文件缺失时静默返回空 —— 这是**可再生产物**，不该让启动失败。
        """
        out: List[str] = []
        if not fp.exists():
            return out
        try:
            for line in fp.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                t = rec.get("text", "") if isinstance(rec, dict) else ""
                if t and len(t) >= 20:
                    out.append(t)
        except (OSError, json.JSONDecodeError):
            return out
        return out

    # ---------- paotuan TRPG 模组 ----------
    @classmethod
    def _load_paotuan(cls, paotuan_dir: Path) -> Tuple[List[str], List[QAPair]]:
        """从 paotuan/ 抽取 TRPG 真实叙事语料。

        两类产出：
        - 纯文本：模组描述、环境氛围、规则手册、角色卡中的叙述性文字；
        - 问答对：`node.trigger`（玩家动作）→ `layer_narrative.anchor_phrases`
          （GM 对该动作的叙述结果）—— 这是项目里质量最高的真实对话轮次。
        """
        texts: List[str] = []
        pairs: List[QAPair] = []
        if not paotuan_dir.is_dir():
            return texts, pairs

        # ① 模组：act_*/nodes
        for fp in sorted((paotuan_dir / "modules").glob("*/module.json")):
            try:
                d = json.loads(fp.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            for key in d:
                if not key.startswith("act_"):
                    continue
                act = d[key]
                if not isinstance(act, dict):
                    continue
                if act.get("description"):
                    texts.append(act["description"])
                env = act.get("environment") or act.get("environment_update") or {}
                if isinstance(env, dict) and env.get("mood"):
                    texts.append(env["mood"])
                for node in act.get("nodes", []):
                    t_p, t_q = cls._extract_node(node, fp.stem)
                    texts += t_p
                    pairs += t_q

        # ② 规则手册 / 内容库：收集叙述性中文文本
        for fp in [paotuan_dir / "config" / "system.json",
                   paotuan_dir / "data" / "enemies.json",
                   paotuan_dir / "data" / "items.json"]:
            if fp.exists():
                texts += cls._collect_narrative_strings(_read_json(fp))

        # ③ 角色卡
        for fp in sorted((paotuan_dir / "characters").glob("*.json")):
            texts += cls._collect_narrative_strings(_read_json(fp))

        return texts, pairs

    @staticmethod
    def _extract_node(node: dict, module: str) -> Tuple[List[str], List[QAPair]]:
        """从单个 TRPG 节点抽取：纯文本 + (玩家动作 → GM 叙述) 问答对。"""
        texts: List[str] = []
        pairs: List[QAPair] = []
        if not isinstance(node, dict):
            return texts, pairs

        trigger = node.get("trigger", "")
        if trigger:
            texts.append(trigger)

        # GM 叙述：layer_narrative.anchor_phrases 的 success/failure/crit_*
        narr = node.get("layer_narrative") or {}
        anchors = narr.get("anchor_phrases") or {}
        answers: List[str] = []
        if isinstance(anchors, dict):
            for k, v in anchors.items():
                if isinstance(v, str) and len(v) >= 4:
                    answers.append(v)
                    texts.append(v)

        # 物理层的检定结果描述
        phys = node.get("layer_physics") or {}
        for key in ("skill_check", "result"):
            v = phys.get(key)
            if isinstance(v, str) and len(v) >= 4:
                texts.append(v)
        for sc in phys.get("skill_checks", []) or []:
            if isinstance(sc, dict):
                for k in ("skill", "result"):
                    v = sc.get(k)
                    if isinstance(v, str) and len(v) >= 4:
                        texts.append(v)
                        if k == "result":
                            answers.append(v)
        for eff in (phys.get("critical_effects") or {}).values():
            if isinstance(eff, str) and len(eff) >= 4:
                texts.append(eff)
                answers.append(eff)

        # 玩家动作 → GM 叙述：真实发生过的对话轮次
        if trigger and answers:
            for a in answers:
                pairs.append(QAPair(trigger, a, source="paotuan",
                                    meta={"module": module,
                                          "node": node.get("node_id", "")}))
        return texts, pairs

    @staticmethod
    def _collect_narrative_strings(obj: Any, min_len: int = 8,
                                   depth: int = 0) -> List[str]:
        """递归收集「像句子」的中文字符串（过滤 id/字段名单词）。"""
        out: List[str] = []
        if depth > 8:
            return out
        if isinstance(obj, dict):
            for k, v in obj.items():
                if str(k).lower() in _SKIP_KEYS:
                    continue
                out += Corpus._collect_narrative_strings(v, min_len, depth + 1)
        elif isinstance(obj, list):
            for v in obj:
                out += Corpus._collect_narrative_strings(v, min_len, depth + 1)
        elif isinstance(obj, str):
            s = obj.strip()
            if len(s) >= min_len and _has_cjk(s):
                out.append(s)
        return out

    @staticmethod
    def _load_training_log(fp: Path) -> List[QAPair]:
        if not fp.exists():
            return []
        try:
            d = json.loads(fp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        out = []
        for rec in d.get("records", []):
            q, a = rec.get("question", ""), rec.get("answer", "")
            if q and a:
                out.append(QAPair(q, a, source="training_log",
                                  meta={"context": rec.get("context", {})}))
        return out

    @staticmethod
    def _load_memories(fp: Path) -> List[QAPair]:
        if not fp.exists():
            return []
        try:
            d = json.loads(fp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        out = []
        for q, answers in (d.get("memories") or {}).items():
            if isinstance(answers, list):
                answers = answers[0] if answers else ""
            if isinstance(answers, str) and q and answers:
                out.append(QAPair(q, answers, source="memory"))
        return out

    @staticmethod
    def _load_rules(fp: Path) -> List[QAPair]:
        """规则库：把正则 pattern 洗成可读文本，与 responses 配成对。"""
        if not fp.exists():
            return []
        try:
            d = json.loads(fp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        out = []
        for rule in d.get("rules", []):
            pattern = rule.get("pattern", "")
            if not pattern or pattern == ".*":
                continue
            q = _clean_pattern(pattern)
            for resp in rule.get("responses", []):
                if q and resp:
                    out.append(QAPair(q, resp, source="rule"))
        return out

    # ---------- 划分 ----------
    def split(self, ratio: float = 0.8) -> Tuple["Corpus", "Corpus"]:
        """按文档顺序划分训练集 / 留出集（确定性，无随机）。

        文本与问答对**分别**按同一比例切，保持两者来源一致。
        """
        if not 0.0 < ratio < 1.0:
            raise ValueError(f"ratio 必须在 (0,1)，当前值：{ratio}")

        n_t = int(len(self.texts) * ratio)
        n_p = int(len(self.pairs) * ratio)
        train = Corpus(f"{self.name}:train",
                       list(self.texts[:n_t]), list(self.pairs[:n_p]))
        hold = Corpus(f"{self.name}:holdout",
                      list(self.texts[n_t:]), list(self.pairs[n_p:]))
        return train, hold

    # ---------- 视图 ----------
    @property
    def user_texts(self) -> List[str]:
        """用户侧语料（问）。"""
        return [p.question for p in self.pairs]

    @property
    def ai_texts(self) -> List[str]:
        """AI 侧语料（答）。"""
        return [p.answer for p in self.pairs]

    @property
    def all_texts(self) -> List[str]:
        return list(self.texts) + self.user_texts + self.ai_texts

    def stats(self) -> Dict[str, Any]:
        """语料规模统计（评估前必看：语料太小则任何结论都不可靠）。"""
        tok = sum(len(tokenize(t)) for t in self.all_texts)
        return {
            "name": self.name,
            "docs": len(self.texts),
            "pairs": len(self.pairs),
            "chars": sum(len(t) for t in self.all_texts),
            "tokens": tok,
            "sources": _count_by_source(self.pairs),
        }

    def __len__(self) -> int:
        return len(self.texts) + len(self.pairs)

    def __repr__(self) -> str:
        s = self.stats()
        return (f"<Corpus {s['name']} docs={s['docs']} pairs={s['pairs']} "
                f"tokens={s['tokens']}>")


def _clean_pattern(pattern: str) -> str:
    """把正则 pattern 洗成可读文本（去掉正则元字符）。"""
    import re as _re
    return _re.sub(r'[.*+?^$(){}|\[\]\\]', '', pattern).strip()


def _count_by_source(pairs: List[QAPair]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for p in pairs:
        out[p.source] = out.get(p.source, 0) + 1
    return dict(sorted(out.items()))
