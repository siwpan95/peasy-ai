"""
聊天界面：tkinter 实现的类微信对话窗口。

特性：
- 顶部：属性条（彩色进度条）
- 中部：可滚动气泡对话（NPC 左灰，玩家右绿）
- 底部：选项按钮（游戏选项）+ 自由输入框（AI 闲聊）

零硬编码：颜色、字体大小、窗口标题全部从初始化参数配置。
"""

import tkinter as tk
from tkinter import ttk, scrolledtext
from typing import Dict, List, Any, Optional, Callable


class ChatUI:
    """tkinter 聊天界面。

    使用方式：
        ui = ChatUI(title="我的游戏", engine=engine, ai=ai_core)
        ui.run()
    """

    # 默认颜色方案（可在构造函数覆盖）
    DEFAULT_COLORS = {
        "bg": "#F5F5F5",
        "npc_bubble": "#FFFFFF",
        "npc_text": "#333333",
        "player_bubble": "#95EC69",
        "player_text": "#333333",
        "system_text": "#999999",
        "input_bg": "#FFFFFF",
        "button_bg": "#07C160",
        "button_fg": "#FFFFFF",
        "button_hover": "#06AD56",
        "attr_bar_bg": "#E0E0E0",
        "attr_bar_fill": "#07C160",
        "attr_label": "#666666",
    }

    def __init__(self, *,
                 title: str = "easy-ai 对话框",
                 width: int = 420,
                 height: int = 700,
                 colors: Optional[Dict[str, str]] = None,
                 font_family: str = "Microsoft YaHei",
                 font_size: int = 11,
                 on_option: Optional[Callable[[int], None]] = None,
                 on_free_text: Optional[Callable[[str], None]] = None,
                 on_close: Optional[Callable[[], None]] = None):
        """
        Args:
            title: 窗口标题。
            width/height: 窗口尺寸。
            colors: 颜色覆盖字典。
            font_family: 字体。
            font_size: 字号。
            on_option: 选项回调 (index) -> None
            on_free_text: 自由输入回调 (text) -> None
            on_close: 窗口关闭回调。
        """
        self.title = title
        self._width = width
        self._height = height
        self.font = (font_family, font_size)
        self.font_small = (font_family, font_size - 1)
        self.font_title = (font_family, font_size + 2, "bold")

        # 合并颜色
        self.colors = dict(self.DEFAULT_COLORS)
        if colors:
            self.colors.update(colors)

        # 回调
        self.on_option = on_option
        self.on_free_text = on_free_text
        self.on_close = on_close

        # 内部状态
        self._attr_widgets: Dict[str, Dict] = {}
        self._option_buttons: List[tk.Widget] = []

        # 构建窗口
        self._build()

    # ============================================================
    # 构建界面
    # ============================================================
    def _build(self):
        self.root = tk.Tk()
        self.root.title(self.title)
        self.root.geometry(f"{self._width}x{self._height}")
        self.root.configure(bg=self.colors["bg"])
        self.root.minsize(320, 500)

        # 绑定关闭事件
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # ---- 顶部：属性栏 ----
        self._attr_frame = tk.Frame(self.root, bg=self.colors["bg"], height=40)
        self._attr_frame.pack(fill="x", padx=10, pady=(10, 0))
        self._attr_frame.pack_propagate(False)

        # ---- 中部：对话滚动区 ----
        self._chat_canvas = tk.Canvas(
            self.root, bg=self.colors["bg"],
            highlightthickness=0, bd=0
        )
        self._chat_scrollbar = tk.Scrollbar(
            self.root, orient="vertical", command=self._chat_canvas.yview
        )
        self._chat_inner = tk.Frame(self._chat_canvas, bg=self.colors["bg"])

        self._chat_inner.bind("<Configure>", lambda e: self._chat_canvas.configure(
            scrollregion=self._chat_canvas.bbox("all")
        ))
        self._chat_window = self._chat_canvas.create_window(
            (0, 0), window=self._chat_inner, anchor="nw", tags="inner"
        )
        self._chat_canvas.configure(yscrollcommand=self._chat_scrollbar.set)

        # Canvas 宽度适配
        self._chat_canvas.bind("<Configure>", self._resize_chat_inner)

        self._chat_canvas.pack(side="left", fill="both", expand=True, padx=(10, 0))
        self._chat_scrollbar.pack(side="right", fill="y", padx=(0, 10))

        # 鼠标滚轮绑定
        self._chat_canvas.bind("<MouseWheel>", self._on_mousewheel)
        self._chat_inner.bind("<Enter>", lambda e: self._chat_canvas.bind_all("<MouseWheel>", self._on_mousewheel))
        self._chat_inner.bind("<Leave>", lambda e: self._chat_canvas.unbind_all("<MouseWheel>"))

        # ---- 底部：输入区 ----
        self._bottom_frame = tk.Frame(self.root, bg=self.colors["bg"])
        self._bottom_frame.pack(fill="x", padx=10, pady=10)

        # 选项按钮容器
        self._options_frame = tk.Frame(self._bottom_frame, bg=self.colors["bg"])
        self._options_frame.pack(fill="x", pady=(0, 5))

        # 自由输入行
        input_row = tk.Frame(self._bottom_frame, bg=self.colors["bg"])
        input_row.pack(fill="x")

        self._input_var = tk.StringVar()
        self._input_entry = tk.Entry(
            input_row, textvariable=self._input_var,
            font=self.font, bg=self.colors["input_bg"],
            relief="solid", bd=1,
        )
        self._input_entry.pack(side="left", fill="x", expand=True, ipady=6)

        self._send_btn = tk.Button(
            input_row, text="发送", font=self.font,
            bg=self.colors["button_bg"], fg=self.colors["button_fg"],
            relief="flat", padx=16, pady=4,
            activebackground=self.colors["button_hover"],
            command=self._on_send,
        )
        self._send_btn.pack(side="right", padx=(8, 0))

        # 回车发送
        self._input_entry.bind("<Return>", lambda e: self._on_send())

    def _resize_chat_inner(self, event):
        """Canvas 大小变化时调整内部 frame 宽度。"""
        self._chat_canvas.itemconfig(self._chat_window, width=event.width)

    def _on_mousewheel(self, event):
        self._chat_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # ============================================================
    # UIInterface 方法
    # ============================================================
    def show_attributes(self, attributes: Dict[str, int],
                        max_values: Optional[Dict[str, int]] = None):
        """渲染属性条。"""
        # 清空
        for w in self._attr_widgets.values():
            w["frame"].destroy()
        self._attr_widgets.clear()

        if not attributes:
            self._attr_frame.configure(height=0)
            return

        self._attr_frame.configure(height=40)
        max_vals = max_values or {k: 100 for k in attributes}

        # 平均分配宽度
        n = len(attributes)
        avail = self._width - 20

        for i, (name, value) in enumerate(attributes.items()):
            max_v = max_vals.get(name, 100)
            ratio = max(0.0, min(1.0, value / max_v)) if max_v > 0 else 0.5

            # 每个属性条容器
            frame = tk.Frame(self._attr_frame, bg=self.colors["bg"])
            frame.place(x=10 + i * (avail // n), y=2, width=avail // n - 10, height=36)

            # 标签
            lbl = tk.Label(frame, text=name, font=self.font_small,
                           fg=self.colors["attr_label"], bg=self.colors["bg"],
                           anchor="w")
            lbl.pack(fill="x")

            # 进度条
            bar_frame = tk.Frame(frame, bg=self.colors["attr_bar_bg"], height=10)
            bar_frame.pack(fill="x")
            bar_inner = tk.Frame(bar_frame, bg=self.colors["attr_bar_fill"])
            bar_inner.place(x=0, y=0, relwidth=ratio, height=10)

            # 数值标签
            val_lbl = tk.Label(frame, text=str(value), font=self.font_small,
                               fg=self.colors["attr_label"], bg=self.colors["bg"])
            val_lbl.pack(fill="x", anchor="e")

            self._attr_widgets[name] = {"frame": frame}

    def show_scene(self, speaker_name: str, speaker_avatar: Optional[str],
                   text: str, options: List[Dict[str, Any]]):
        """渲染场景对话和选项。"""
        # NPC 消息气泡
        self._add_bubble(speaker_name, text, is_npc=True)

        # 清除旧选项按钮
        self._clear_options()

        # 新选项按钮
        if options:
            for i, opt in enumerate(options):
                btn = tk.Button(
                    self._options_frame,
                    text=opt.get("text", f"选项 {i+1}"),
                    font=self.font,
                    bg=self.colors["button_bg"],
                    fg=self.colors["button_fg"],
                    relief="flat", padx=12, pady=6,
                    activebackground=self.colors["button_hover"],
                    command=lambda idx=i: self._on_option_click(idx),
                )
                btn.pack(side="left", padx=4, pady=2)
                self._option_buttons.append(btn)

    def show_ending(self, text: str):
        """显示结局。"""
        self._add_system_message(f"【结局】{text}")
        self._clear_options()

    def add_ai_message(self, text: str):
        """显示 AI 闲聊消息。"""
        self._add_bubble("AI", text, is_npc=True)
        self._clear_options()

    # ============================================================
    # 内部渲染
    # ============================================================
    def _add_bubble(self, sender: str, message: str, is_npc: bool = True):
        """添加一个对话气泡。"""
        bubble_frame = tk.Frame(self._chat_inner, bg=self.colors["bg"])
        bubble_frame.pack(fill="x", padx=8, pady=4)

        bg_color = self.colors["npc_bubble"] if is_npc else self.colors["player_bubble"]
        anchor = "w" if is_npc else "e"
        side = "left" if is_npc else "right"

        if is_npc:
            # 发送者名称
            name_lbl = tk.Label(
                bubble_frame, text=sender, font=self.font_small,
                fg=self.colors["system_text"], bg=self.colors["bg"],
                anchor="w"
            )
            name_lbl.pack(fill="x", padx=(4, 0))

        # 气泡框
        msg_frame = tk.Frame(bubble_frame, bg=bg_color, bd=0, highlightthickness=0)

        # 包装长文本
        wrap_len = max(40, self._width // 12)
        msg_lbl = tk.Label(
            msg_frame, text=message, font=self.font,
            fg=self.colors["npc_text" if is_npc else "player_text"],
            bg=bg_color, wraplength=self._width - 120,
            justify="left", padx=12, pady=8
        )
        msg_lbl.pack()

        msg_frame.pack(anchor=anchor, padx=8, pady=2)

        # 滚动到底部
        self._chat_inner.update_idletasks()
        self._chat_canvas.yview_moveto(1.0)

    def _add_system_message(self, text: str):
        """添加系统消息（结局等）。"""
        lbl = tk.Label(
            self._chat_inner, text=text, font=self.font_title,
            fg=self.colors["system_text"], bg=self.colors["bg"],
            wraplength=self._width - 60, pady=20
        )
        lbl.pack(fill="x")
        self._chat_canvas.yview_moveto(1.0)

    def _clear_options(self):
        """清除所有选项按钮。"""
        for btn in self._option_buttons:
            btn.destroy()
        self._option_buttons.clear()

    # ============================================================
    # 事件处理
    # ============================================================
    def _on_option_click(self, index: int):
        """选项按钮被点击。"""
        if self.on_option:
            self.on_option(index)

    def _on_send(self):
        """发送自由文本。"""
        text = self._input_var.get().strip()
        if not text:
            return

        self._input_var.set("")

        # 显示自己的消息
        self._add_bubble("我", text, is_npc=False)

        # 回调
        if self.on_free_text:
            self.on_free_text(text)

    def _on_close(self):
        """窗口关闭。"""
        if self.on_close:
            self.on_close()
        self.root.destroy()

    # ============================================================
    # 主循环
    # ============================================================
    def run(self):
        """启动 tkinter 主循环。"""
        self.root.mainloop()

    def quit(self):
        """退出主循环。"""
        self.root.quit()

    def after(self, ms: int, callback: Callable):
        """延迟调用。"""
        self.root.after(ms, callback)
