# -*- coding: utf-8 -*-
"""
迷失之镜 — 终端角色卡渲染器 (View 层 · 阶段 2)
游戏内按 C 查看角色卡
"""
try:
    from ..core.character import Character
except ImportError:  # 脚本自举模式（sys.path[0] = paotuan/ 目录）
    from core.character import Character


class CharacterSheet:
    """终端角色卡显示器"""

    @staticmethod
    def render(pc: Character) -> str:
        """渲染完整角色卡到字符串"""
        lines = []
        lines.append("")
        lines.append("╔════════════════════════════════════════╗")
        lines.append(f"║  角色卡：{pc.name:<20s}          ║")
        lines.append("╠════════════════════════════════════════╣")

        # 属性
        lines.append("║  ── 属性 ──                           ║")
        lines.append(f"║  ST {pc.st:>3d}  DX {pc.dx:>3d}  IQ {pc.iq:>3d}  HT {pc.ht:>3d}            ║")

        # 衍生值
        lines.append("║  ── 衍生值 ──                         ║")
        hp_status = "🔴" if pc.hp < pc.hp_max // 3 else ("🟡" if pc.hp < pc.hp_max // 2 else "🟢")
        lines.append(f"║  {hp_status} HP: {pc.hp}/{pc.hp_max}  |  FP: {pc.fp}/{pc.fp_max}               ║")
        lines.append(f"║  Will: {pc.will}  |  Per: {pc.per}  |  Dodge: {pc.dodge}              ║")

        # 资源
        lines.append("║  ── 资源 ──                           ║")
        lines.append(f"║  ○ 专注点: {pc.focus_points}/{pc.focus_max}  |  ♦ 幸运点: {pc.luck_points}/{pc.luck_max}      ║")
        marks_bar = "💀" + "●" * pc.psychic_marks + "○" * (5 - pc.psychic_marks)
        lines.append(f"║  {marks_bar}  精神印记: {pc.psychic_marks}                  ║")

        # 技能
        if pc.skills:
            lines.append("║  ── 技能 ──                           ║")
            for skill in pc.skills[:8]:  # 最多显示 8 个
                lines.append(f"║  {skill.name:<12s} {skill.level:>3d} ({skill.difficulty})                 ║")

        # 特征
        if pc.features:
            lines.append("║  ── 特征 ──                           ║")
            for feat in pc.features[:4]:
                status = "✅" if feat.used_this_scene < feat.per_scene_limit else "❌"
                lines.append(f"║  {status} {feat.name:<14s} (○{feat.cost})                ║")

        # 优劣势
        if pc.advantages or pc.disadvantages:
            lines.append("║  ── 优/劣势 ──                        ║")
            for adv in pc.advantages[:3]:
                lines.append(f"║  + {adv:<20s}          ║")
            for dis in pc.disadvantages[:3]:
                lines.append(f"║  - {dis:<20s}          ║")

        # 装备
        if pc.equipment:
            lines.append("║  ── 装备 ──                           ║")
            for eq in pc.equipment[:6]:
                mark = "☑" if eq.equipped else "☐"
                lines.append(f"║  {mark} {eq.name:<14s} ({eq.etype})               ║")

        # 永久标签
        if pc.permanent_tags:
            lines.append("║  ── 永久标签 ──                        ║")
            for tag in pc.permanent_tags[:3]:
                lines.append(f"║  ⚠ {tag:<22s}       ║")

        # XP
        if pc.total_xp > 0:
            lines.append(f"║  ── XP: {pc.total_xp} (v{pc.version}) ──               ║")

        lines.append("╚════════════════════════════════════════╝")
        return "\n".join(lines)

    @staticmethod
    def render_compact(pc: Character) -> str:
        """紧凑模式（用于状态栏）"""
        hp_color = "🔴" if pc.hp < pc.hp_max // 3 else ("🟡" if pc.hp < pc.hp_max // 2 else "🟢")
        return (f"{hp_color} HP:{pc.hp}/{pc.hp_max} | FP:{pc.fp}/{pc.fp_max} | "
                f"○:{pc.focus_points}/{pc.focus_max} ♦:{pc.luck_points}/{pc.luck_max} | 💀:{pc.psychic_marks}")
