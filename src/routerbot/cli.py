"""RouterBot CLI entrypoint."""

import click


@click.group()
@click.version_option(package_name="routerbot")
def main() -> None:
    """RouterBot — Open Source LLM Gateway."""


@main.command()
@click.option("--host", default="0.0.0.0", help="Bind address")  # noqa: S104
@click.option("--port", default=4000, help="Bind port")
@click.option("--reload", is_flag=True, help="Enable auto-reload")
def serve(host: str, port: int, reload: bool) -> None:
    """Start the RouterBot proxy server."""
    try:
        import uvicorn
    except ImportError as exc:
        raise click.ClickException("Proxy dependencies not installed. Run: pip install routerbot[proxy]") from exc

    uvicorn.run(
        "routerbot.proxy.main:app",
        host=host,
        port=port,
        reload=reload,
    )


if __name__ == "__main__":
    main()
