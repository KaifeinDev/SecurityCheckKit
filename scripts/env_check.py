"""Environment health check for the security-scan pipeline (Step 0), runnable
standalone without Claude Code.

Automates the mechanical parts of Step 0 from SKILL.md:
  - `foundry.toml` exists and `src` is not misconfigured as "."
  - `forge build` succeeds
  - OpenZeppelin upgradeable API version signature detection (v4 vs v5),
    flagging mixed/conflicting signatures for human review rather than
    guessing (see references/pitfalls.md #2)
  - toolchain + dependency version info, written as scan_env.json for
    build_report.py to consume

This script does NOT install missing dependencies or pick a version for you —
that decision needs human judgment when contracts mix incompatible API
signatures. It reports what it finds and exits non-zero when something needs
a human to look at it.

Usage:
    python3 env_check.py [--project-dir .] [--src-prefix src/] [--json out.json]
"""
import argparse
import json
import os
import re
import subprocess
import sys

# (marker regex, which OZ major version it indicates)
OZ_VERSION_SIGNATURES = [
    (re.compile(r"__UUPSUpgradeable_init\s*\("), "v4"),
    (re.compile(r"_beforeTokenTransfer\s*\("), "v4"),
    (re.compile(r"__Ownable_init\s*\(\s*\)"), "v4"),  # no-arg form
    (re.compile(r"__Ownable_init\s*\(\s*\w"), "v5"),  # takes initialOwner
    (re.compile(r"_update\s*\(\s*address\s+to\s*,\s*uint256\s+tokenId\s*,\s*address\s+auth\s*\)"), "v5"),
]


def run(cmd, cwd):
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=120)
        return proc.returncode == 0, (proc.stdout + proc.stderr).strip()
    except FileNotFoundError:
        return False, f"command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return False, f"timed out: {' '.join(cmd)}"


def check_foundry_toml(project_dir):
    path = os.path.join(project_dir, "foundry.toml")
    if not os.path.isfile(path):
        return {"ok": False, "detail": "foundry.toml not found — run `forge init` first"}
    with open(path, encoding="utf-8") as f:
        content = f.read()
    m = re.search(r'^\s*src\s*=\s*"(.*?)"', content, re.MULTILINE)
    src_val = m.group(1) if m else "src"  # foundry default
    if src_val == ".":
        return {
            "ok": False,
            "detail": (
                'src = "." in foundry.toml — this makes forge compile everything under '
                "lib/ as primary targets (see pitfalls.md #1). Must be a dedicated dir, e.g. \"src\"."
            ),
        }
    return {"ok": True, "detail": f'src = "{src_val}"'}


def check_forge_build(project_dir):
    ok, output = run(["forge", "build"], project_dir)
    return {"ok": ok, "detail": "forge build succeeded" if ok else output[-3000:]}


def find_sol_files(src_dir):
    out = []
    for root, _dirs, files in os.walk(src_dir):
        for name in files:
            if name.endswith(".sol"):
                out.append(os.path.join(root, name))
    return out


def detect_oz_version_signatures(project_dir, src_prefixes):
    findings = {}  # file -> set of versions detected
    for prefix in src_prefixes:
        src_dir = os.path.join(project_dir, prefix)
        if not os.path.isdir(src_dir):
            continue
        for path in find_sol_files(src_dir):
            with open(path, encoding="utf-8", errors="ignore") as f:
                text = f.read()
            versions = {ver for pattern, ver in OZ_VERSION_SIGNATURES if pattern.search(text)}
            if versions:
                rel = os.path.relpath(path, project_dir)
                findings[rel] = sorted(versions)

    conflicts = {f: v for f, v in findings.items() if len(v) > 1}
    return {"per_file": findings, "conflicts": conflicts}


def gather_dependency_versions(project_dir):
    lib_dir = os.path.join(project_dir, "lib")
    deps = []
    if not os.path.isdir(lib_dir):
        return deps
    for name in sorted(os.listdir(lib_dir)):
        path = os.path.join(lib_dir, name)
        if not os.path.isdir(path):
            continue
        version = None
        ok, out = run(["git", "-C", path, "describe", "--tags", "--always"], project_dir)
        if ok and out:
            version = out.strip().splitlines()[-1]
        else:
            pkg_json = os.path.join(path, "package.json")
            if os.path.isfile(pkg_json):
                try:
                    with open(pkg_json, encoding="utf-8") as f:
                        version = json.load(f).get("version")
                except (json.JSONDecodeError, OSError):
                    pass
        deps.append({"name": name, "version": version or "unknown"})
    return deps


def gather_scan_env(project_dir):
    _, solc_out = run(["solc", "--version"], project_dir)
    solc_version = None
    m = re.search(r"Version:\s*([0-9.]+)", solc_out)
    if m:
        solc_version = m.group(1)

    _, slither_out = run(["slither", "--version"], project_dir)
    slither_version = slither_out.strip().splitlines()[-1] if slither_out else "unknown"

    _, forge_out = run(["forge", "--version"], project_dir)
    forge_version = "unknown"
    m = re.search(r"^forge Version:\s*(\S+)", forge_out, re.MULTILINE)
    if m:
        forge_version = f"forge Version: {m.group(1)}"

    git_ok, git_out = run(["git", "rev-parse", "HEAD"], project_dir)
    git_commit = git_out.strip() if git_ok else None

    return {
        "scan_date": None,  # filled in by scan.py at actual scan time
        "project_path": os.path.abspath(project_dir),
        "git_commit": git_commit,
        "solc_version": solc_version or "unknown",
        "slither_version": slither_version,
        "forge_version": forge_version,
        "dependencies": gather_dependency_versions(project_dir),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project-dir", default=".")
    parser.add_argument("--src-prefix", action="append", default=[], help="Repeatable. Defaults to src/.")
    parser.add_argument("--json", help="Write machine-readable result to this path")
    args = parser.parse_args()

    src_prefixes = args.src_prefix or ["src/"]
    project_dir = args.project_dir

    result = {
        "foundry_toml": check_foundry_toml(project_dir),
        "forge_build": None,
        "oz_version_signatures": detect_oz_version_signatures(project_dir, src_prefixes),
        "env": gather_scan_env(project_dir),
    }

    needs_human = False

    print(f"[foundry.toml] {result['foundry_toml']['detail']}")
    if not result["foundry_toml"]["ok"]:
        needs_human = True

    if result["foundry_toml"]["ok"]:
        result["forge_build"] = check_forge_build(project_dir)
        status = "OK" if result["forge_build"]["ok"] else "FAILED"
        print(f"[forge build] {status}")
        if not result["forge_build"]["ok"]:
            print(result["forge_build"]["detail"])
            needs_human = True
    else:
        print("[forge build] skipped (fix foundry.toml first)")

    conflicts = result["oz_version_signatures"]["conflicts"]
    if conflicts:
        needs_human = True
        print("[oz-version] CONFLICTING API signatures found — pick a version manually, do not guess:")
        for f, versions in conflicts.items():
            print(f"  - {f}: signatures matching {versions}")
    else:
        per_file = result["oz_version_signatures"]["per_file"]
        if per_file:
            print("[oz-version] consistent signatures detected:")
            for f, versions in per_file.items():
                print(f"  - {f}: {versions}")
        else:
            print("[oz-version] no version-specific signatures detected")

    env = result["env"]
    print(f"[versions] solc={env['solc_version']} slither={env['slither_version']} forge={env['forge_version']}")
    if env["slither_version"] == "unknown":
        needs_human = True
        print("  slither not found on PATH — install it first (see SKILL.md Step 0.5)")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"wrote {args.json}")

    sys.exit(1 if needs_human else 0)


if __name__ == "__main__":
    main()
