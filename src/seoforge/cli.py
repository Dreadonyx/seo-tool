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
from seoforge.robots import RobotsTxt
from seoforge.storage import Store

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


@app.command()
def fix(
    url: Annotated[
        str | None, typer.Argument(help="Site URL to crawl and generate fixes for.")
    ] = None,
    config_path: ConfigOpt = None,
    out: Annotated[Path, typer.Option("--out", "-o", help="Output directory.")] = Path(
        "seoforge-fixes"
    ),
    max_pages: Annotated[int | None, typer.Option("--max-pages", "-n")] = None,
    ai_policy: Annotated[
        str | None,
        typer.Option(
            "--ai-policy", help="AI crawler preset: allow-all | search-only | deny-all | custom."
        ),
    ] = None,
    redirect_map: Annotated[
        Path | None,
        typer.Option("--redirect-map", help="CSV of old,new[,status] redirects to include."),
    ] = None,
    apply_to: Annotated[
        Path | None,
        typer.Option(
            "--apply-to",
            help="Local site root (e.g. ./public). Shows a diff and asks before each write.",
        ),
    ] = None,
    yes: Annotated[
        bool, typer.Option("--yes", help="With --apply-to: accept all diffs without prompting.")
    ] = False,
    cached: Annotated[bool, typer.Option("--cached", help="Reuse cached responses.")] = False,
    delay: Annotated[float | None, typer.Option("--delay")] = None,
) -> None:
    """Generate robots.txt, sitemap.xml, llms.txt, JSON-LD, meta tags and redirects.

    Files are written to --out. Nothing on your site changes unless you pass --apply-to with a
    LOCAL directory, review each diff and confirm it. SEOForge never modifies remote sites.
    """
    from rich.syntax import Syntax

    from seoforge.fix.bundle import apply_bundle, build_bundle
    from seoforge.geo.extras import add_geo_files

    config = _load(config_path)
    site = _site(url, config)
    if max_pages is not None:
        config.crawl.max_pages = max_pages
    if delay is not None:
        config.crawl.delay_seconds = delay
    if ai_policy and ai_policy not in ("allow-all", "search-only", "deny-all", "custom"):
        err.print(f"[red]Unknown --ai-policy {ai_policy}[/red]")
        raise typer.Exit(2)
    if redirect_map and not redirect_map.is_file():
        err.print(f"[red]Redirect map not found: {redirect_map}[/red]")
        raise typer.Exit(2)
    with console.status(f"Crawling {site}"):
        _report, ctx = run(run_audit(site, config, AuditOptions(cached=cached, pagespeed=False)))
    bundle = build_bundle(ctx, preset=ai_policy, redirect_map=redirect_map, extra=add_geo_files)
    written = bundle.write(out)
    console.print(f"Wrote {len(written)} file(s) to [bold]{out}[/bold] (see {out / 'INDEX.md'})")
    for f in bundle.files[:40]:
        console.print(f"  {f.path:<52} {f.description}")
    if apply_to is None:
        console.print(
            "[dim]Nothing on your site was changed. Use --apply-to <local dir> to apply with a diff preview.[/dim]"
        )
        return
    if not apply_to.is_dir():
        err.print(f"[red]--apply-to must be an existing local directory: {apply_to}[/red]")
        raise typer.Exit(2)

    def confirm(path: str, diff: str) -> bool:
        console.rule(path)
        console.print(Syntax(diff, "diff", theme="ansi_dark", word_wrap=True))
        if yes:
            return True
        return typer.confirm(f"Write {path}?", default=False)

    changed = apply_bundle(bundle, apply_to, confirm)
    console.print(f"Applied {len(changed)} file(s) in {apply_to}.")


# ---- GEO -----------------------------------------------------------------------------------
geo_app = typer.Typer(help="Generative-engine optimization: AI crawlers, llms.txt, entity tools.")
app.add_typer(geo_app, name="geo")


@geo_app.command("bots")
def geo_bots(
    url: Annotated[str | None, typer.Argument(help="Site URL.")] = None,
    config_path: ConfigOpt = None,
) -> None:
    """Show which AI crawlers your live robots.txt allows, and what your policy would generate."""
    from seoforge.geo.ai_bots import current_access, resolve_policy
    from seoforge.http import PoliteClient

    config = _load(config_path)
    site = _site(url, config)

    async def go() -> RobotsTxt:
        async with PoliteClient(config.crawl) as client:
            return await client.robots(site)

    robots = run(go())
    desired = resolve_policy(config.geo.ai_bot_preset, config.geo.ai_bots)
    table = Table(
        "Bot", "Operator", "Purpose", "Live", "Explicit", f"Policy ({config.geo.ai_bot_preset})"
    )
    for b in current_access(robots, site):
        live = "[green]allowed[/green]" if b.allowed else "[red]blocked[/red]"
        table.add_row(
            b.token, b.operator, b.purpose, live, "yes" if b.explicit else "no", desired[b.token]
        )
    console.print(table)
    if robots.missing:
        console.print("[yellow]No robots.txt: every bot is allowed by default.[/yellow]")
    console.print(
        "[dim]robots.txt is advisory; enforce at your server/CDN for bots that ignore it.[/dim]"
    )


@geo_app.command("entity")
def geo_entity(
    url: Annotated[str | None, typer.Argument(help="Site URL.")] = None,
    config_path: ConfigOpt = None,
    max_pages: Annotated[int, typer.Option("--max-pages", "-n")] = 50,
    wikidata: Annotated[
        bool, typer.Option("--wikidata/--no-wikidata", help="Search Wikidata for your entity.")
    ] = True,
) -> None:
    """sameAs graph, brand consistency, Wikidata search and draft."""
    from seoforge.geo import entity
    from seoforge.http import PoliteClient

    config = _load(config_path)
    site = _site(url, config)
    config.crawl.max_pages = max_pages
    with console.status("Crawling"):
        _r, ctx = run(run_audit(site, config, AuditOptions(pagespeed=False)))
    report = entity.analyze(ctx.crawl, config.entity)
    console.print(f"[bold]Entity:[/bold] {report.name or '(unknown - set entity.name)'}")
    table = Table("Platform", "Profile")
    for platform, link in report.platforms.items():
        table.add_row(platform, link or "[dim]-[/dim]")
    console.print(table)
    if report.name_variants:
        console.print(f"Name variants: {report.name_variants}")
    if report.missing_facts:
        console.print(f"[yellow]Missing facts:[/yellow] {', '.join(report.missing_facts)}")
    if wikidata and report.name:

        async def search() -> list[dict[str, str]]:
            async with PoliteClient(config.crawl) as client:
                return await entity.wikidata_search(client.http, report.name or "")

        try:
            candidates = run(search())
        except Exception as exc:
            err.print(f"[yellow]Wikidata search failed: {exc}[/yellow]")
            candidates = []
        if candidates:
            console.print(
                "[bold]Existing Wikidata items with this name[/bold] (check before creating one):"
            )
            for c in candidates:
                console.print(f"  {c['id']}  {c['label']} - {c['description']}  {c['url']}")
        else:
            console.print("No Wikidata item found with this name.")
    qs, _guide = entity.wikidata_draft(config.entity, ctx.crawl.site, report.same_as, report.name)
    console.print("[bold]Wikidata QuickStatements draft[/bold] (full guide via `seoforge fix`):")
    console.print(qs)


@geo_app.command("llms")
def geo_llms(
    url: Annotated[str | None, typer.Argument(help="Site URL.")] = None,
    config_path: ConfigOpt = None,
    out: Annotated[Path, typer.Option("--out", "-o")] = Path("seoforge-fixes"),
    max_pages: Annotated[int | None, typer.Option("--max-pages", "-n")] = None,
    md_links: Annotated[
        bool, typer.Option("--md-links", help="Link to .md mirrors in llms.txt.")
    ] = False,
) -> None:
    """Generate llms.txt, llms-full.txt and Markdown mirrors only."""
    from seoforge.generators import llms

    config = _load(config_path)
    site = _site(url, config)
    if max_pages:
        config.crawl.max_pages = max_pages
    with console.status("Crawling"):
        _r, ctx = run(run_audit(site, config, AuditOptions(pagespeed=False)))
    files = llms.generate(ctx.crawl, config, md_links=md_links)
    out.mkdir(parents=True, exist_ok=True)
    (out / "llms.txt").write_text(files.llms_txt, encoding="utf-8")
    (out / "llms-full.txt").write_text(files.llms_full_txt, encoding="utf-8")
    for path, md in files.mirrors.items():
        target = out / "markdown" / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(md, encoding="utf-8")
    console.print(
        f"Wrote llms.txt, llms-full.txt and {len(files.mirrors)} Markdown mirror(s) to {out}"
    )
    console.print(
        "[dim]llms.txt is a proposal (llmstxt.org); AI providers have not confirmed using it.[/dim]"
    )


# ---- AI visibility tracker -----------------------------------------------------------------
vis_app = typer.Typer(help="Track whether AI assistants mention or cite you (manual or scripted).")
app.add_typer(vis_app, name="visibility")


def _store(config: Config) -> Store:
    return Store(config.db_path)


@vis_app.command("init")
def vis_init(config_path: ConfigOpt = None) -> None:
    """Create the default prompt set from the entity section of seoforge.yaml."""
    from seoforge.geo.visibility import add_prompts, default_prompts

    config = _load(config_path)
    prompts = default_prompts(config.entity, config.seed_keywords)
    if not prompts:
        err.print(
            "[yellow]Set entity.name / entity.category (and seed_keywords) in seoforge.yaml first.[/yellow]"
        )
        raise typer.Exit(1)
    added = add_prompts(_store(config), prompts)
    console.print(f"Added {added} prompt(s). List them with `seoforge visibility prompts`.")


@vis_app.command("add")
def vis_add(
    prompt: Annotated[str, typer.Argument(help="Prompt text.")],
    config_path: ConfigOpt = None,
) -> None:
    """Add a custom prompt."""
    from seoforge.geo.visibility import add_prompts

    added = add_prompts(_store(_load(config_path)), [(prompt, "custom")])
    console.print("Added." if added else "Already tracked.")


@vis_app.command("prompts")
def vis_prompts(config_path: ConfigOpt = None) -> None:
    """List tracked prompts."""
    from seoforge.geo.visibility import list_prompts

    table = Table("ID", "Kind", "Prompt")
    for p in list_prompts(_store(_load(config_path))):
        table.add_row(str(p["id"]), p["kind"], p["text"])
    console.print(table)


@vis_app.command("log")
def vis_log(
    prompt_id: Annotated[int, typer.Argument(help="Prompt ID (see `visibility prompts`).")],
    engine: Annotated[
        str, typer.Argument(help="chatgpt|claude|gemini|perplexity|copilot|brave-leo|other")
    ],
    mentioned: Annotated[
        bool, typer.Option("--mentioned/--not-mentioned", help="Was your brand mentioned?")
    ] = False,
    cited_url: Annotated[
        str | None, typer.Option("--cited-url", help="URL of yours that was cited/linked.")
    ] = None,
    position: Annotated[
        int | None, typer.Option("--position", help="Rank in a list answer, if any.")
    ] = None,
    notes: Annotated[str | None, typer.Option("--notes")] = None,
    config_path: ConfigOpt = None,
) -> None:
    """Record what an AI assistant answered (manual entry)."""
    from seoforge.geo.visibility import Observation, log

    try:
        log(
            _store(_load(config_path)),
            Observation(
                prompt_id,
                engine.lower(),
                mentioned or bool(cited_url),
                bool(cited_url),
                position,
                cited_url,
                "manual",
                notes,
            ),
        )
    except ValueError as exc:
        err.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from exc
    console.print("Logged.")


@vis_app.command("import")
def vis_import(
    csv_path: Annotated[
        Path, typer.Argument(help="CSV: prompt,engine,date,mentioned,cited_url,position,notes")
    ],
    config_path: ConfigOpt = None,
) -> None:
    """Import observations from a CSV file."""
    from seoforge.geo.visibility import import_csv

    n = import_csv(_store(_load(config_path)), csv_path)
    console.print(f"Imported {n} observation(s).")


@vis_app.command("run")
def vis_run(
    engine: Annotated[str, typer.Argument(help="Engine label to record results under.")],
    cmd: Annotated[
        str,
        typer.Option("--cmd", help="Command printing an answer; {prompt} is replaced. No shell."),
    ],
    url: Annotated[
        str | None, typer.Option("--site", help="Your site URL (to detect citations).")
    ] = None,
    config_path: ConfigOpt = None,
) -> None:
    """Run YOUR command once per prompt and log brand mentions/citations from its output.

    Use only APIs/tools whose terms allow it (e.g. a free API tier you signed up for).
    SEOForge does not automate consumer chat apps.
    """
    from seoforge.geo.visibility import run_command

    config = _load(config_path)
    try:
        results = run_command(
            _store(config), engine.lower(), cmd, config.entity, url or config.site
        )
    except ValueError as exc:
        err.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from exc
    hits = sum(r.mentioned for r in results)
    console.print(
        f"Ran {len(results)} prompt(s): mentioned in {hits}, cited in {sum(r.cited for r in results)}."
    )


@vis_app.command("report")
def vis_report(
    config_path: ConfigOpt = None,
    json_out: Annotated[
        Path | None, typer.Option("--json", help="Also write the summary as JSON.")
    ] = None,
) -> None:
    """Mention and citation rates per engine over time."""
    import json as _json

    from seoforge.geo.visibility import summary

    data = summary(_store(_load(config_path)))
    if not data["observations"]:
        console.print("No observations yet. Use `seoforge visibility log` or `visibility run`.")
        return
    table = Table("Engine", "Month", "Checks", "Mention rate", "Citation rate")
    for engine, rows in data["trend"].items():
        for r in rows:
            table.add_row(
                engine,
                r["month"],
                str(r["checks"]),
                f"{r['mention_rate']:.0%}",
                f"{r['citation_rate']:.0%}",
            )
    console.print(table)
    latest = Table("Prompt", "Engine", "Date", "Mentioned", "Cited URL")
    for r in data["latest"]:
        latest.add_row(
            r["prompt"],
            r["engine"],
            r["date"],
            "yes" if r["mentioned"] else "no",
            r["cited_url"] or "",
        )
    console.print(latest)
    if json_out:
        json_out.write_text(_json.dumps(data, indent=2), encoding="utf-8")
        console.print(f"Wrote {json_out}")
