"""SEOForge command-line interface."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Coroutine
from pathlib import Path
from typing import Annotated, Any, TypeVar

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from seoforge import __version__
from seoforge.audit import AuditOptions, run_audit
from seoforge.config import EXAMPLE_CONFIG, Config, load_config
from seoforge.models import Severity
from seoforge.report.builder import Report
from seoforge.report.limitations import DISCLAIMER
from seoforge.report.render import write_reports

T = TypeVar("T")

app = typer.Typer(
    name="seoforge",
    help="Free, open-source SEO / AEO / GEO auditing and optimization CLI.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
console = Console()
err = Console(stderr=True)

ConfigOpt = Annotated[
    Path | None, typer.Option("--config", "-c", help="Path to seoforge.yaml.", exists=False)
]


def _load(config_path: Path | None) -> Config:
    try:
        return load_config(config_path)
    except FileNotFoundError as exc:
        err.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from exc


def _site(url: str | None, config: Config) -> str:
    site = url or config.site
    if not site:
        err.print(
            "[red]Give a URL (seoforge audit https://example.com) or set `site:` in seoforge.yaml.[/red]"
        )
        raise typer.Exit(2)
    if not site.startswith(("http://", "https://")):
        site = "https://" + site
    return site


def run(coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


@app.callback(invoke_without_command=True)
def main(
    version: Annotated[bool, typer.Option("--version", help="Show version and exit.")] = False,
) -> None:
    if version:
        console.print(f"seoforge {__version__}")
        raise typer.Exit()


@app.command()
def init(
    path: Annotated[Path, typer.Argument(help="Where to write the config.")] = Path(
        "seoforge.yaml"
    ),
    force: Annotated[bool, typer.Option("--force", help="Overwrite an existing file.")] = False,
) -> None:
    """Write an example seoforge.yaml."""
    if path.exists() and not force:
        err.print(f"[yellow]{path} exists; use --force to overwrite.[/yellow]")
        raise typer.Exit(1)
    path.write_text(EXAMPLE_CONFIG, encoding="utf-8")
    console.print(f"Wrote {path}")


@app.command()
def audit(
    url: Annotated[str | None, typer.Argument(help="Site URL to audit.")] = None,
    config_path: ConfigOpt = None,
    max_pages: Annotated[int | None, typer.Option("--max-pages", "-n")] = None,
    depth: Annotated[int | None, typer.Option("--depth")] = None,
    concurrency: Annotated[int | None, typer.Option("--concurrency")] = None,
    delay: Annotated[
        float | None, typer.Option("--delay", help="Seconds between requests per host.")
    ] = None,
    render: Annotated[
        bool, typer.Option("--render", help="Render JavaScript with Playwright.")
    ] = False,
    resume: Annotated[
        bool, typer.Option("--resume", help="Resume the last unfinished crawl.")
    ] = False,
    cached: Annotated[
        bool, typer.Option("--cached", help="Reuse cached responses (within cache TTL).")
    ] = False,
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Report output directory.")
    ] = None,
    fmt: Annotated[
        list[str] | None, typer.Option("--format", "-f", help="html, md, json (repeatable).")
    ] = None,
    pagespeed: Annotated[
        bool, typer.Option("--pagespeed/--no-pagespeed", help="Query PageSpeed Insights.")
    ] = True,
    lighthouse: Annotated[
        bool, typer.Option("--lighthouse", help="Also run the local Lighthouse CLI.")
    ] = False,
    check_external: Annotated[
        bool, typer.Option("--check-external", help="Check outbound links.")
    ] = False,
    competitor: Annotated[
        list[str] | None,
        typer.Option("--competitor", help="Competitor URL for content gap (repeatable)."),
    ] = None,
    suggest: Annotated[
        bool,
        typer.Option(
            "--suggest", help="Fetch Google Autosuggest ideas (opt-in, cached, rate-limited)."
        ),
    ] = False,
    fail_on: Annotated[
        str | None,
        typer.Option("--fail-on", help="Exit 1 if issues at/above: critical|high|medium|low."),
    ] = None,
) -> None:
    """Crawl a site and produce a prioritized SEO/AEO/GEO report."""
    config = _load(config_path)
    site = _site(url, config)
    c = config.crawl
    if max_pages is not None:
        c.max_pages = max_pages
    if depth is not None:
        c.max_depth = depth
    if concurrency is not None:
        c.concurrency = concurrency
    if delay is not None:
        c.delay_seconds = delay
    if render:
        c.render_js = True
    if check_external:
        c.check_external = True
    options = AuditOptions(
        resume=resume,
        cached=cached,
        pagespeed=pagespeed,
        lighthouse=lighthouse,
        suggest=suggest,
        competitors=list(competitor or []) + config.competitors,
    )
    console.print(f"[bold]SEOForge {__version__}[/bold] auditing {site}")
    with Progress(
        SpinnerColumn(), TextColumn("{task.description}"), console=console, transient=True
    ) as prog:
        task = prog.add_task("Starting", total=None)

        def on_progress(done: int, seen: int, current: str) -> None:
            prog.update(task, description=f"Crawled {done}/{seen}  {current[:80]}")

        def on_step(msg: str) -> None:
            prog.update(task, description=msg)

        report, _ctx = run(run_audit(site, config, options, progress=on_progress, step=on_step))

    out_dir = out or Path(config.report.output_dir)
    formats = fmt or list(config.report.formats)
    bad = [f for f in formats if f not in ("html", "md", "json")]
    if bad:
        err.print(f"[red]Unknown format(s): {', '.join(bad)}[/red]")
        raise typer.Exit(2)
    paths = write_reports(report, out_dir, formats)
    _print_summary(report)
    for p in paths:
        console.print(f"  wrote {p}")
    threshold = fail_on or config.report.fail_on
    if threshold and threshold != "never":
        limit = Severity(threshold).rank
        if any(i.severity.rank <= limit for i in report.issues):
            err.print(f"[red]Failing: issues at or above '{threshold}' found.[/red]")
            raise typer.Exit(1)


def _print_summary(report: Report) -> None:
    counts = report.severity_counts
    console.print(
        f"\nHealth score [bold]{report.score}/100[/bold] (heuristic estimate) · "
        f"{report.stats['html_pages']} HTML pages · "
        f"[red]{counts['critical']} critical[/red] · [dark_orange]{counts['high']} high[/dark_orange] · "
        f"[yellow]{counts['medium']} medium[/yellow] · [green]{counts['low']} low[/green]"
    )
    if report.stats.get("render_error"):
        console.print(f"[yellow]JS rendering skipped: {report.stats['render_error']}[/yellow]")
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("Severity")
    table.add_column("Issue")
    table.add_column("URLs", justify="right")
    colors = {
        "critical": "red",
        "high": "dark_orange",
        "medium": "yellow",
        "low": "green",
        "info": "dim",
    }
    for issue in report.issues[:15]:
        sev = issue.severity.value
        table.add_row(f"[{colors[sev]}]{sev}[/{colors[sev]}]", issue.title, str(len(issue.urls)))
    if report.issues:
        console.print(table)
    if len(report.issues) > 15:
        console.print(f"  ... {len(report.issues) - 15} more in the report")
    console.print(f"[dim]{DISCLAIMER}[/dim]")


def entrypoint() -> None:  # pragma: no cover
    sys.exit(app())
