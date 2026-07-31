"""Cross-reference audit for the paper: citations, labels, refs, empty cells."""
import re
import sys

t = open(sys.argv[1], encoding="utf-8").read()

cited = set()
for m in re.findall(r"\\cite\{([^}]*)\}", t):
    cited.update(k.strip() for k in m.split(","))
defined = set(re.findall(r"\\bibitem\{([^}]*)\}", t))
labels = set(re.findall(r"\\label\{([^}]*)\}", t))
refs = set()
for m in re.findall(r"\\(?:ref|autoref)\{([^}]*)\}", t):
    refs.add(m.strip())

print("=== CITATIONS ===")
print(f"  cited keys:   {len(cited)}")
print(f"  bibitems:     {len(defined)}")
missing = sorted(cited - defined)
unused = sorted(defined - cited)
print(f"  cited but NOT in bibliography (breaks build): {missing or 'none'}")
print(f"  in bibliography but never cited (dead weight): {unused or 'none'}")

print("\n=== REFS / LABELS ===")
print(f"  \\ref targets: {len(refs)}   \\label defined: {len(labels)}")
bad = sorted(refs - labels)
unref = sorted(labels - refs)
print(f"  \\ref with no \\label (renders as '??'): {bad or 'none'}")
print(f"  \\label never referenced (harmless): {unref or 'none'}")

print("\n=== EMPTY / SUSPICIOUS CONTENT ===")
empties = []
for i, line in enumerate(t.splitlines(), 1):
    s = line.strip()
    if re.search(r"&\s*&", s) or s.endswith("& \\\\") or re.search(r"&\s*\\\\\s*$", s):
        empties.append((i, s[:70]))
print(f"  table rows with an empty cell: {len(empties)}")
for i, s in empties[:8]:
    print(f"    line {i}: {s}")

todo = [(i, ln.strip()[:70]) for i, ln in enumerate(t.splitlines(), 1)
        if re.search(r"TODO|TBD|FIXME|XXX|\[to be|pending\]", ln, re.I)]
print(f"  TODO/TBD/pending markers: {len(todo)}")
for i, s in todo[:8]:
    print(f"    line {i}: {s}")

# Bibitems whose body is suspiciously short = probably a stub entry.
stubs = []
for key, body in re.findall(r"\\bibitem\{([^}]*)\}(.*?)(?=\\bibitem|\\end\{thebibliography\})",
                            t, re.S):
    if len(body.strip()) < 40:
        stubs.append((key, body.strip()[:50]))
print(f"  stub/near-empty bibitems: {len(stubs)}")
for k, b in stubs:
    print(f"    {k}: {b!r}")

print("\n=== VERDICT ===")
ok = not missing and not bad and not stubs and not todo
print("  " + ("ALL CLEAN" if ok else "ISSUES ABOVE NEED FIXING"))
