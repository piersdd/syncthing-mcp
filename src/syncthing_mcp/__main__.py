"""Entry point for `python -m syncthing_mcp` and the `syncthing-mcp` console script."""

from syncthing_mcp.server import mcp


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
