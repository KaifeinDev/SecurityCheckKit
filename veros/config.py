#!/usr/bin/env python3
"""Model settings for the AI triage step.

    veros config --show
    veros config --model claude-opus-5
    veros config --api-key sk-ant-...      # or just export ANTHROPIC_API_KEY

Resolution order for the key: --api-key on the command line, then
$ANTHROPIC_API_KEY, then the stored config. The env var wins over the file so a
CI job can inject its own key without rewriting anyone's config, and so the key
does not have to be written to disk at all.
"""
import argparse
import json
import os
import stat
import sys

CONFIG_DIR = os.path.join(
    os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "veros"
)
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

DEFAULT_MODEL = "claude-opus-5"
DEFAULT_EFFORT = "high"


def load() -> dict:
    if not os.path.isfile(CONFIG_PATH):
        return {}
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def save(data: dict) -> None:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    # The file may hold an API key; keep it off other accounts on the machine.
    os.chmod(CONFIG_PATH, stat.S_IRUSR | stat.S_IWUSR)


def resolve_model() -> str:
    return load().get("model") or DEFAULT_MODEL


def resolve_effort() -> str:
    return load().get("effort") or DEFAULT_EFFORT


def resolve_api_key(explicit: str = None) -> str:
    return explicit or os.environ.get("ANTHROPIC_API_KEY") or load().get("api_key") or ""


def require_api_key(explicit: str = None) -> str:
    key = resolve_api_key(explicit)
    if not key:
        sys.exit(
            "找不到 API key。擇一設定：\n"
            "  export ANTHROPIC_API_KEY=sk-ant-...\n"
            "  veros config --api-key sk-ant-...\n"
            f"（後者會寫進 {CONFIG_PATH}，權限 0600）"
        )
    return key


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--model", help=f"AI 判讀使用的模型，預設 {DEFAULT_MODEL}")
    parser.add_argument(
        "--effort", choices=["low", "medium", "high", "xhigh", "max"],
        help=f"思考深度，預設 {DEFAULT_EFFORT}。安全判讀建議不低於 high",
    )
    parser.add_argument("--api-key", help="寫入設定檔；也可以改用 $ANTHROPIC_API_KEY 不落地")
    parser.add_argument("--show", action="store_true", help="顯示目前設定")
    args = parser.parse_args()

    data = load()
    changed = False
    for field in ("model", "effort", "api_key"):
        value = getattr(args, field if field != "api_key" else "api_key")
        if value:
            data[field] = value
            changed = True
    if changed:
        save(data)
        print(f"已寫入 {CONFIG_PATH}")

    if args.show or not changed:
        key = resolve_api_key()
        source = (
            "環境變數 ANTHROPIC_API_KEY" if os.environ.get("ANTHROPIC_API_KEY")
            else ("設定檔" if load().get("api_key") else "未設定")
        )
        print(f"設定檔  : {CONFIG_PATH}")
        print(f"模型    : {resolve_model()}")
        print(f"思考深度: {resolve_effort()}")
        print(f"API key : {'已設定（' + source + '）' if key else '未設定'}")


if __name__ == "__main__":
    main()
