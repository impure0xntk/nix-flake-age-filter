# Ensure the project's src directory is on the import path for test discovery
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[0]
src_path = PROJECT_ROOT.parent / "src"
if src_path.is_dir():
    sys.path.insert(0, str(src_path))
