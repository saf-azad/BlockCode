"""Command line interface: `blockcode serve|new|import-csv|validate|run|export`."""

from __future__ import annotations

from pathlib import Path

import typer

app = typer.Typer(help="BlockCode: blocks that compile to SQL, Python and R.", no_args_is_help=True)


@app.command()
def serve(
    host: str = "127.0.0.1",
    port: int = 8000,
    projects_dir: Path = typer.Option(Path("projects"), help="Where projects are stored."),
) -> None:
    """Start the local web editor."""
    import uvicorn

    from blockcode.server import create_app

    uvicorn.run(create_app(projects_dir), host=host, port=port)


@app.command()
def version() -> None:
    """Print the BlockCode version."""
    from blockcode import __version__

    typer.echo(__version__)
