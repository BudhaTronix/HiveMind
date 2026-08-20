"""Allow ``python -m hivemind`` to behave like the installed ``hivemind`` command."""

from hivemind.cli import app

if __name__ == "__main__":
    app()
