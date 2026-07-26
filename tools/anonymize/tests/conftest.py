import sys
from pathlib import Path

# Делаем соседние модули пакета импортируемыми при запуске pytest из любой папки.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))