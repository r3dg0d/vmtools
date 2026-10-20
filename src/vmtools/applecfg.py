"""`config` subcommand shared by iosvm/macosvm (keys live in ~/.config/vmtools/config.json)."""

from __future__ import annotations

from .layout import config
from .ui import OUT


def add_config(sub, prefix: str):
    sp = sub.add_parser("config", help=f"show or set {prefix}_* settings", description="config [KEY [VALUE]]")
    sp.add_argument("key", nargs="?")
    sp.add_argument("value", nargs="?")

    def run(args) -> int:
        cfg = config()
        keys = sorted(k for k in cfg.defaults if k.startswith(prefix + "_"))
        if args.key and args.value is not None:
            cfg.set(args.key, args.value)
            OUT.ok(f"{args.key} = {cfg.get(args.key)}")
        elif args.key:
            print(cfg.get(args.key))
        elif OUT.json:
            OUT.emit_json({k: cfg.get(k) for k in keys})
        else:
            for k in keys:
                OUT.say(f"  {k:24} {cfg.get(k)}")
        return 0

    sp.set_defaults(handler=run)
    return sp
