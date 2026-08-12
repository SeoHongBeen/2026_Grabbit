"""
모든 스크립트의 import가 제대로 되는지 검사

파일을 옮기거나 import를 바꾼 뒤에 한 번 돌려보기

왜 필요한가:
  py_compile(구문 검사)로는 "모듈을 못 찾는" 문제가 안 잡힘

어떻게:
  각 파일의 맨 위부터 '마지막 top-level import 문'까지만 잘라서 실행
  sys.path 설정 같은 준비 코드가 그 사이에 있으므로 통째로 실행해야 하고,
  그 뒤(학습 루프 등)는 실행되지 않으므로 빠름

사용법:
    python tools/check_imports.py
"""
import ast
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 윈도우에서 출력을 파이프로 넘기면 stdout이 cp949가 되고, em-dash 같은 문자에서
# UnicodeEncodeError로 죽는다. 검사는 다 끝났는데 요약을 찍다가 죽으면 결과를 못 본다.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# 검사할 폴더. record/ 는 RPi에서 단독으로 돌아가야 하므로 함께 봄
FOLDERS = ["core", "data", "training", "export", "record", "tools"]

RUNNER = r'''
import ast, sys, os
path = sys.argv[1]

# 실제 실행(python 폴더/스크립트.py)과 같은 조건을 만든다
# 파이썬은 스크립트가 있는 폴더를 sys.path 맨 앞에 넣으므로,
# 같은 폴더의 모듈을 import 하는 코드도 동작해야 함
sys.path.insert(0, os.path.dirname(os.path.abspath(path)))

src = open(path, encoding="utf-8").read()
tree = ast.parse(src)

last = -1
for i, node in enumerate(tree.body):
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        last = i

if last < 0:
    print("NOIMPORT")
    sys.exit(0)

head = ast.Module(body=tree.body[:last + 1], type_ignores=[])
ns = {"__file__": os.path.abspath(path), "__name__": "importcheck"}
exec(compile(head, path, "exec"), ns)
print("OK")
'''


def collect():
    out = []
    for folder in FOLDERS:
        d = os.path.join(ROOT, folder)
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if f.endswith(".py"):
                out.append("%s/%s" % (folder, f))
    return out


def main():
    scripts = collect()
    if not scripts:
        print("검사할 파일이 없습니다")
        return 1

    env = dict(os.environ, PYTHONIOENCODING="utf-8", TF_CPP_MIN_LOG_LEVEL="3")
    fails = []

    print("%d개 파일 검사\n" % len(scripts))
    for s in scripts:
        r = subprocess.run(
            [sys.executable, "-c", RUNNER, s],
            cwd=ROOT, capture_output=True, text=True,
            encoding="utf-8", errors="replace", env=env)

        lines = (r.stdout or "").strip().splitlines()
        ok = r.returncode == 0 and lines and lines[-1] in ("OK", "NOIMPORT")

        print("  %-34s %s" % (s, "OK" if ok else "FAIL"))
        if not ok:
            tail = [l for l in (r.stderr or "").strip().splitlines() if l.strip()]
            fails.append((s, tail[-1] if tail else "(메시지 없음)"))

    print()
    if fails:
        print("실패 %d개" % len(fails))
        for s, msg in fails:
            print("  %-32s %s" % (s, msg[:100]))
        return 1

    print("전부 통과 — 모든 스크립트가 필요한 모듈을 찾습니다")
    return 0


if __name__ == "__main__":
    sys.exit(main())
