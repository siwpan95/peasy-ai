# Mirror of the Lost（镜中之失）

> 基于 GURPS 4e 的三层 MVVM 架构 TRPG 终端引擎 — 让 GM 专注于叙事，让引擎处理裁决。

---

## 项目概述

Mirror of the Lost 是一个 **终端驱动** 的 TRPG（桌上角色扮演游戏）中间件引擎。它不替代 GM——它替代骰子、规则查询和状态追踪，让 GM 从机械劳动中解放出来，专注于讲故事。

### 设计哲学

| 层 | 来源 | 职责 | 红线 |
|---|------|------|------|
| **Model（物理层）** | GURPS 4e | 属性/技能/伤害/环境物理。确定性状态管理。 | 不可输出叙事文本 |
| **ViewModel（叙事层）** | Fate Core | 裁决包→叙事转换。锚点查表。玩家宣告。 | 不可修改物理值 |
| **View（节奏层）** | Savage Worlds | 终端渲染。先攻抽牌。流程控制。 | 不直接读 Model |

核心接口是两个结构体：
- `ResolutionPacket`（物理层产出）→ 骰子/伤害/部位/穿透
- `ViewModelResult`（叙事层产出）→ 叙事文本/标签/专注点动作/事件队列

### 特色机制

- **数据驱动场景引擎** — module.json 的 `nodes[]` 数组驱动所有游戏逻辑，支持 5 种场景类型（perception/investigation/feat/combat/explore）
- **锚点查表** — 27 条扩展锚点短语（9 部位×3 伤害等级×3 伤害类型），实现"裁决包→叙事"的自动化转换
- **双币制** — 专注点（改情境/加标签/触发特征）vs 幸运点（重掷骰子），互不交叉
- **环境即第一 NPC** — EnvironmentSystem 持续产出标签，玩家可花专注点改变环境
- **附庸阈值系统** — ≥6 伤害立即移除，2-5 丧失行动力，<2 轻微干扰——切掉 GURPS 打群架的数学爆炸
- **休克系统** — HP/3 阈值，HT 检定失败则震慑 1 回合（-4 惩罚）
- **部位伤害** — 3d6 掷部位表，头/臂/腿/躯干各有不同效应标签
- **XP 成长** — 属性购买价格 ST/HT=10, DX/IQ=20

---

## 目录结构

```
pt/
├── README.md                    ← 本文件
├── requirements.txt             ← 依赖清单（纯标准库，仅记录 Python 版本）
├── mirror_launcher.py           ← 启动入口（游戏主循环）
├── mirror_mvp.py                ← 核心引擎（MVVM 集成中心）
│
├── config/                      ← 项目配置
│   └── system.json              │  系统配置（规则引擎、内容库、架构描述）
│
├── core/                        ← Model + ViewModel 层
│   ├── character.py             │  GURPS 角色数据模型（四属性/衍生/技能/特征/装备）
│   ├── enemy.py                 │  敌人模型（mook/elite/wildcard/boss）
│   ├── scene_engine.py          │  数据驱动场景引擎（module.json → 节点执行）
│   ├── combat_engine.py         │  战斗引擎（先攻/攻击/防御/休克/部位）
│   ├── viewmodel.py             │  ResolutionPacket → ViewModelResult 转换管线
│   └── environment_system.py    │  环境标签系统（加载/进化/玩家交互）
│
├── services/                    ← 辅助服务层
│   ├── item_system.py           │  物品运行时（装备/消耗品/效果查询）
│   ├── xp_system.py             │  XP 计算/成长/升级选项
│   ├── save_manager.py          │  存档管理（角色快照 + 进度 JSON）
│   ├── scene_resolver.py        │  场景结算（专注回复/印记消减/执念检查）
│   └── data_importer.py         │  统一数据导入器
│
├── view/                        ← View 层（终端渲染）
│   ├── terminal_renderer.py     │  所有终端输出收拢模块
│   └── character_sheet.py       │  角色卡渲染（完整/紧凑模式）
│
├── data/                        ← 游戏数据
│   ├── enemies.json             │  敌人库
│   └── items.json               │  物品库
│
├── characters/                  ← 玩家角色卡（JSON）
│   ├── 预置-调查记者.json
│   ├── 预置-退役军警.json
│   ├── 预置-神秘学学者.json
│   └── 预置-街头混混.json
│
├── modules/                     ← 模组（每个模组一个子目录）
│   └── mirror_house_alley/
│       └── module.json          │  镜屋巷模组（完整 3 幕）
│
├── templates/                   ← 内容创作模板
│   ├── characters/              │  角色卡 Excel 模板
│   │   ├── character.xlsx       │  │  空白角色卡
│   │   ├── 预置-调查记者.xlsx    │  │  IQ 13 调查记者
│   │   ├── 预置-退役军警.xlsx    │  │  ST 13 退役军警
│   │   ├── 预置-神秘学学者.xlsx  │  │  IQ 14 神秘学学者
│   │   └── 预置-街头混混.xlsx    │  │  DX 13 街头混混
│   ├── gm-data/                 │  GM 数据 Excel 模板
│   │   ├── enemy_builder.xlsx   │  │  敌人构建器
│   │   ├── item_builder.xlsx    │  │  物品构建器
│   │   ├── trap_builder.xlsx    │  │  陷阱构建器
│   │   ├── encounter_table.xlsx │  │  遭遇表
│   │   ├── loot_table.xlsx      │  │  战利品表
│   │   └── npc_reaction.xlsx    │  │  NPC 反应表
│   ├── gm-module/               │  GM 模组 Excel 模板
│   │   ├── scene_builder.xlsx   │  │  场景构建器
│   │   ├── module_meta.xlsx     │  │  模组元信息
│   │   └── map_grid.xlsx        │  │  网格地图
│   └── json-templates/          │  JSON 空白模板
│       ├── character_template.json
│       ├── enemy_template.json
│       ├── item_template.json
│       ├── module_template.json
│       └── scene_node_template.json
│
├── saves/                       ← 存档目录（自动创建）
│
├── tools/                       ← 工具脚本
│   ├── make_templates.py        │  一键生成 Excel 模板
│   └── char_importer.py         │  角色卡 Excel → JSON 导入器
│
├── tests/                       ← 测试套件
│   ├── test_comprehensive.py     │  535 项全覆盖测试
│   └── test_excel_roundtrip.py  │  Excel 生态回验证
```

---

## 快速开始

### 环境要求

- Python 3.10+
- 零外部依赖（纯标准库）

### 运行游戏

```bash
cd pt
python mirror_launcher.py
```

启动后将看到：
1. Splash 画面 → 2. 模组选择 → 3. 角色选择（4 预置 + 快速创建） → 4. 游戏主循环

### 快捷键

| 按键 | 功能 |
|------|------|
| `C` | 查看完整角色卡 |
| `S` | 保存进度 |
| `H` | 帮助菜单 |
| `Q` | 退出（主菜单） |

### 运行测试

```bash
cd pt
python tests/test_comprehensive.py
```

535 项测试覆盖所有 15 个模块，验证核心路径与边缘情况。

### Excel 生态验证

```bash
cd pt
python tests/test_excel_roundtrip.py
```

53 项回验证确保 Excel → JSON 转换完整性。

---

## 内容创作指南

### 创建角色

1. 复制 `templates/json-templates/character_template.json` 到 `characters/`
2. 填写属性（ST/DX/IQ/HT）、技能、特征、装备
3. 文件即角色——放在 `characters/` 目录下即被自动发现

**属性说明**：
- `ST`（力量）— 近战伤害、负重、HP
- `DX`（敏捷）— 命中、闪避、精细操作
- `IQ`（智力）— 技能、感知、意志
- `HT`（体质）— 生命值、抗性、疲劳

**特征格式**（触发-响应模式）：
```json
{
  "name": "特征名",
  "trigger_condition": "自然语言触发条件",
  "cost": 1,
  "effect": "效果描述",
  "per_scene_limit": 2
}
```

### 创建模组

1. 在 `modules/` 下新建子目录
2. 复制 `templates/json-templates/module_template.json` 为 `module.json`
3. 填写 meta 信息 → 定义 act_1/act_2/act_3 → 填充 nodes[]

**场景类型**：

| scene_type | 说明 | 核心配置 |
|------------|------|----------|
| `perception` | 感知检定 | `skill_check` + `modifier` |
| `investigation` | 调查节点 | `skill_checks[]`（嵌套检定） |
| `feat` | 壮举/挑战 | `skill_check` + `tool_bonus` |
| `combat` | 战斗 | `unit_stats` + `special_mechanic` |
| `explore` | 纯叙事 | `auto_success: true` |

**节点门控**：
- `prerequisite_nodes` — 前置节点列表（必须全部完成）
- `next_nodes` — 解锁的后续节点
- ViewModel 自动产出 `queued_events` 驱动流程推进

### 创建敌人

添加到 `data/enemies.json` 的 `enemies[]` 数组。

| enemy_type | 说明 |
|------------|------|
| `mook` | 杂兵——附庸阈值系统，不追踪单个体 |
| `elite` | 精英——完整追踪 HP，有属性 |
| `wildcard` | 特殊——有复杂特殊机制 |
| `boss` | Boss——完整属性 + 多阶段 |

### 创建物品

添加到 `data/items.json` 对象中（以物品 ID 为键）。

| type | 说明 | 示例 |
|------|------|------|
| `weapon` | 武器 | `damage: "2d6 pi+"` |
| `armor` | 护甲 | `dr: 4, dr_location: "躯干"` |
| `tool` | 工具 | `tool_bonus: +2` |
| `consumable` | 消耗品 | `uses: 1, restore_hp: "1d6"` |
| `key_item` | 关键道具 | 剧情相关 |

---

## 规则速查

### 3d6 裁决

| 掷骰 | 结果 |
|------|------|
| 3-4 | 大成功（Crit Success） |
| 5 ~ 目标值 | 成功 |
| 目标值+1 ~ 16 | 失败 |
| 17-18 | 大失败（Fumble） |

### 部位表（3d6）

| 掷骰 | 部位 |
|------|------|
| 3-5 | 头 |
| 6-7 | 右臂/左臂 |
| 8-13 | 躯干 |
| 14-16 | 右腿/左腿 |
| 17-18 | 头 |

### 伤害类型

| 类型 | 穿透倍率 |
|------|----------|
| 切割（cut） | ×1.5 |
| 穿刺（imp/pi+）| ×2 |
| 钝击（cr） | ×1.0 |
| 燃烧（burn） | ×1.0 + 持续 |

### 双币制

| | 专注点 | 幸运点 |
|---|--------|--------|
| 作用 | 改情境（标签/特征） | 改骰子（重掷） |
| 默认值 | 3/3 | 2/2 |
| 回复 | 场景结算 / 安全节点 | 模组结束 |
| 消耗 | 1-2 点/次 | 1 点/次 |

### 附庸阈值

| 伤害 | 效果 |
|------|------|
| ≥6 | 立即移除 |
| 2-5 | 丧失行动力 / 溃逃 |
| <2 | 轻微干扰 |

---

## 开发指南

### 架构红线（不可违反）

1. Model 不输出叙事 — 只产出 ResolutionPacket
2. ViewModel 不修改物理值 — 只产出叙事标签
3. View 不绕过 VM 直接读 Model 原始数据
4. 战斗引擎攻击链路：`attack_resolve()` → `active_defense()` → `shock_check()` → `apply_damage()`，不可跳步

### 添加新子系统

1. 确定层级归属（core / services / view）
2. 创建模块文件
3. 在 `mirror_mvp.py` 的 `__init__` 中集成
4. 更新 `config/system.json` 的 `architecture.layers`
5. 写测试 → `tests/test_comprehensive.py`

### 添加新模组

1. 在 `modules/` 下新建目录
2. 复制 `templates/json-templates/module_template.json`
3. 确保 `module_id` 唯一，`system_name` = "Mirror of the Lost"
4. 遵循 scene_type 规范（perception/investigation/feat/combat/explore）
5. 定义完整的 prerequisite_nodes / next_nodes 门控图

---

## 许可证

概念框架：CC BY-NC-SA 4.0  
规则基础：GURPS 4e（Steve Jackson Games）

---

## 版本历史

| 版本 | 日期 | 里程碑 |
|------|------|--------|
| v1.0 | — | 基础架构，脚本驱动 |
| v2.0 | 2026-06-06 | MVVM 三层重构，数据驱动，15 模块，535 测试 |
| v3.1 | 2026-06-06 | 完整角色系统、战斗引擎、VM 管线、XP 成长 |

---

*"镜子从不撒谎——它只是展现一个方向。"*
