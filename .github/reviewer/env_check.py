"""Сверка среды с .github/environment.lock.json (§18′ п.18, D-143): ввод-вывод вокруг env_lib.

  env_check.py static
      reviewer-ci: рабочее дерево против lock-файла — runs-on, uses@SHA,
      CLAUDE_CODE_VERSION в agent.yml, файлы требований с хешами. Любое
      расхождение — код 1 (красный).
  env_check.py runtime --workflow NAME --out PATH [--cli PATH_TO_CLAUDE]
      в прогоне: ImageOS, ImageVersion, python3 (и версия CLI, если дан --cli)
      против lock-файла. Одна строка ENV_CHECK в журнал и JSON для артефакта
      прогона (механика в репозиторий не пишет). Код 1 — только расхождение
      того, что меняем мы (версия CLI); образ и python3 прогон не красят.
"""

import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import env_lib as el  # noqa: E402

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))


def read(path):
    try:
        with open(os.path.join(ROOT, path), encoding="utf-8") as fh:
            return fh.read()
    except FileNotFoundError:
        return None


def run_version(cmd):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return (out.stdout or out.stderr).strip() if out.returncode == 0 else None


def static():
    try:
        lock = el.parse_lock(read(el.LOCK_PATH))
    except el.LockError as exc:
        print(f"::error::environment lock: {exc.reason}")
        return 1
    wf_dir = os.path.join(ROOT, ".github", "workflows")
    workflows = {n: read(f".github/workflows/{n}") for n in sorted(os.listdir(wf_dir))}
    repo_files = {p: read(p) for p in lock["hashed_requirements"]}
    bad = el.static_violations(lock, workflows, repo_files)
    for v in bad:
        print(f"::error::environment lock: {v}")
    if not bad:
        print(f"environment lock: рабочее дерево совпадает с {el.LOCK_PATH} "
              f"(runs-on {lock['runner_label']}, {len(lock['uses'])} uses@SHA, CLI {lock['claude_code_version']}, "
              f"требования: {', '.join(lock['hashed_requirements'])})")
    return 1 if bad else 0


def actual_values(cli):
    actual = {"image_os": os.environ.get("ImageOS") or None,
              "image_version": os.environ.get("ImageVersion") or None,
              "python3": el.python3_version(run_version(["python3", "--version"]))}
    if cli:
        actual["claude_code_version"] = el.cli_version(run_version([cli, "--version"]))
    return actual


def runtime(workflow, out, cli=None, env=os.environ):
    fields = el.PLATFORM_FIELDS + (el.OWN_FIELDS if cli else ())
    try:
        lock = el.parse_lock(read(el.LOCK_PATH))
        result = el.compare_runtime(lock, actual_values(cli), fields)
    except el.LockError as exc:
        result = el.lock_error_result(exc.reason)
    result.update(schema=1, workflow=workflow, run_id=env.get("GITHUB_RUN_ID", ""), lock=el.LOCK_PATH,
                  section="§18′ п.18 (D-143)")
    line = el.runtime_line(result)
    print(("::warning::" if result["status"] in ("drift", "unknown", "lock_error") else
           "::error::" if result["status"] == "red" else "") + line)
    if out:
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=2)
    return 1 if result["status"] == "red" else 0


def main(argv):
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=["static", "runtime"])
    p.add_argument("--workflow", default="")
    p.add_argument("--out", default="")
    p.add_argument("--cli", default="")
    a = p.parse_args(argv[1:])
    if a.mode == "static":
        return static()
    return runtime(a.workflow, a.out, a.cli or None)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
