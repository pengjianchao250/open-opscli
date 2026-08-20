"""为独立历史迁移测试加入脚本包的本地导入路径。"""

from pathlib import Path
import sys


_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
