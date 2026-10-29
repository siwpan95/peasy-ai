"""paotuan —— 内置「迷失之镜」TRPG 子应用（GURPS 4e）。

这是一个**自带 core/ services/ view/ 的独立子应用**，不是 easy_ai 的库代码：

- 它不 import easy_ai 的 ai/engine（只有 trpg/paotuan_gui.py 反向调用它）；
- 内部导入采用**双模写法**：优先相对导入（`from .core.xxx import` /
  `from ..core.xxx import`），ImportError 时回退顶层绝对导入
  （`from core.xxx import`）。前者支持 pip 安装后以
  `easy_ai.paotuan.core.scene_engine` 形式导入，后者兼容历史上的
  脚本自举方式；
- `easy_ai.main` 的 `paotuan` 子命令通过 importlib 以文件方式加载
  `mirror_launcher.py`，并在加载前把本目录插入 sys.path[0]；
  此时模块无父包，相对导入失败，自动走回退分支。

放在 easy_ai 包内只是为了随发行版一起分发，保持 `main.py paotuan` 开箱可用。
"""
