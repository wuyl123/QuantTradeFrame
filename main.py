"""Entry point for stock data, charts, and the configured buy-and-hold backtest."""

import argparse
from importlib import import_module


COMMANDS = {
    "backtest": ("src.backtest.engine", "Run the strategy YAML; CLI options override it"),
    "download-a-share": ("src.data.a_share", "Download A-share data from BaoStock"),
    "download-us": ("src.data.us_stock", "Download US stock data from Alpaca"),
    "validate": ("src.data.loader", "Validate and normalize a stock CSV"),
    "plot": ("src.evaluation.visualize", "Plot price and trading volume"),
}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog="No command runs config/strategy.yaml. Use COMMAND --help for its options.",
    )
    commands = parser.add_subparsers(dest="command")
    for name, (_, description) in COMMANDS.items():
        commands.add_parser(name, help=description, add_help=False)
    args, remaining = parser.parse_known_args(argv)
    module_name, _ = COMMANDS[args.command or "backtest"]
    # Load only the requested tool; imports never download or run a backtest.
    import_module(module_name).main(remaining)


if __name__ == "__main__":
    main()
