"""Application entry point."""

import sys


def main() -> None:
    """Launch the Systemommy application."""
    from systemommy.app import run_application

    sys.exit(run_application())


if __name__ == "__main__":
    main()
