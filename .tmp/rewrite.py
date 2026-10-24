"""一次性重写 stock_report_service 的 build_batches（CR-018）。"""
import pathlib

svc = pathlib.Path('app/services/stock_report_service.py')
new = pathlib.Path('.tmp/new_build.py').read_text(encoding='utf-8')

t = svc.read_text(encoding='utf-8')
start = t.index('def build_batches(')
end = t.index('BATCH_COLUMNS:')
t = t[:start] + new + '\n\n' + t[end:]

# 列/键：增加「行类型」
t = t.replace('BATCH_COLUMNS: list[tuple[str, int]] = [\n    ("仓库", 14),',
              'BATCH_COLUMNS: list[tuple[str, int]] = [\n    ("行类型", 10), ("仓库", 14),')
t = t.replace('BATCH_KEYS = ["warehouse",',
              'BATCH_KEYS = ["row_kind", "warehouse",')

if 'ROW_KIND_LABELS' not in t:
    t = t.rstrip() + '''

ROW_KIND_LABELS: dict[str, str] = {
    "normal": "正常配对",
    "reversal": "红冲",
    "orphan": "无批次出库",
}
'''
svc.write_text(t, encoding='utf-8')
print('rewrite done; row_kind refs:', t.count('row_kind'),
      '| keys:', t.count('"row_kind"'))
