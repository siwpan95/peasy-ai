"""
测试套件初始化文件。

使 tests/ 成为一个 Python 包，支持 unittest 发现。
"""

import sys
from pathlib import Path

# 将项目根目录添加到路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
