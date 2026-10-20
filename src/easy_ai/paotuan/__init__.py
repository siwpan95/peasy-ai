"""paotuan —— 内置「迷失之镜」TRPG 子应用（GURPS 4e）。

这是一个**自带 core/ services/ view/ 的独立子应用**，不是 easy_ai 的库代码：

- 它不 import easy_ai 的 ai/engine（只有 trpg/paotuan_gui.py 反向调用它）；
- 它按「自身目录在 sys.path 首位」的方式自举，因此内部用 `from core.xxx import`
  这样的顶层绝对导入，与 easy_ai.ai / easy_ai.engine 互不干扰；
- `easy_ai.main` 的 `paotuan` 子命令通过 importlib 以文件方式加载
  `mirror_launcher.py`，并在加载前把本目录插入 sys.path[0]。

放在 easy_ai 包内只是为了随发行版一起分发，保持 `main.py paotuan` 开箱可用。
"""
