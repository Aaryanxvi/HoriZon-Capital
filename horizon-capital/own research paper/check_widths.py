"""Flag display math and table rows likely to overrun a two-column measure."""
import re
import sys

t = open(sys.argv[1], encoding="utf-8").read()

print("=== display math ===")
for m in re.finditer(r"\\begin\{(equation\*?|align\*?)\}(.*?)\\end\{\1\}", t, re.S):
    body = " ".join(m.group(2).split())
    line = t[: m.start()].count("\n") + 1
    # A single-line display wider than ~100 chars of source usually overruns a
    # 3.4in column; one already broken with aligned/split is fine.
    wide = len(body) > 100 and not re.search(r"aligned|split|gathered|\\\\", body)
    print(f"  {'WIDE' if wide else 'ok  '} line {line:4d}  len {len(body):3d}  {body[:80]}")

print("\n=== long table rows (single-column tables only) ===")
for m in re.finditer(r"\\begin\{table\}(.*?)\\end\{table\}", t, re.S):
    for row in m.group(1).split(r"\\"):
        row = " ".join(row.split())
        if "&" in row and len(row) > 95:
            line = t[: m.start()].count("\n") + 1
            print(f"  WIDE near line {line:4d}  len {len(row):3d}  {row[:80]}")

print("\n=== verbatim/texttt runs over 30 chars ===")
for m in re.finditer(r"\\text(tt|sc)\{([^}]{31,})\}", t):
    line = t[: m.start()].count("\n") + 1
    print(f"  line {line:4d}: {m.group(2)[:60]}")
print("done")
