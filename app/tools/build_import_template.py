"""生成《合同导入模板样例.xlsx》（与 /api/import/template.xlsx 同一规格）。

用法：python app/tools/build_import_template.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.routers.imports import build_template_bytes  # 复用服务端模板（避免双份漂移）

OUT = ROOT / "import_template" / "合同导入模板样例.xlsx"


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(build_template_bytes())
    print("saved:", OUT)


if __name__ == "__main__":
    main()
