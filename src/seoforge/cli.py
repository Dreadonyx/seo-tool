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


@geo_app.command("commoncrawl")
def geo_commoncrawl(
    url: Annotated[str | None, typer.Argument(help="Site URL.")] = None,
    config_path: ConfigOpt = None,
) -> None:
    """How many of your URLs are in the latest Common Crawl index (free CDX API)."""
    from seoforge.geo.commoncrawl import presence
    from seoforge.http import PoliteClient

    config = _load(config_path)
    site = _site(url, config)

    async def go() -> Any:
        async with PoliteClient(config.crawl) as client:
            return await presence(client.http, site)

    with console.status("Querying Common Crawl index"):
        result = run(go())
    if result.error:
        err.print(f"[yellow]Common Crawl query failed: {result.error}[/yellow]")
        raise typer.Exit(1)
    console.print(
        f"{result.domain}: {result.captures} capture(s) in {result.crawl_id} (first 1,000 counted)"
    )
    for u in result.sample:
        console.print(f"  {u}")
    console.print(
        "[dim]Presence in Common Crawl is a rough signal of availability to LLM training "
        "pipelines, not proof any model used your content.[/dim]"
    )


# ---- Indexing --------------------------------------------------------------------------------
index_app = typer.Typer(help="Legitimate indexing: sitemaps, IndexNow, Search Console, Bing.")
app.add_typer(index_app, name="index")


def _confirm_send(what: str, yes: bool, dry_run: bool) -> bool:
    if dry_run:
        console.print(f"[yellow]Dry run:[/yellow] would {what}. Nothing sent.")
        return False
    return yes or typer.confirm(f"{what[0].upper()}{what[1:]}?", default=False)


def _urls_from(
    site: str, config: Config, urls_file: Path | None, changed_only: bool, max_pages: int | None
) -> tuple[list[str], dict[str, str]]:
    if urls_file:
        urls = [
            u.strip() for u in urls_file.read_text().splitlines() if u.strip().startswith("http")
        ]
        return urls, {}
    if max_pages:
        config.crawl.max_pages = max_pages
    with console.status("Crawling to collect indexable URLs"):
        _r, ctx = run(run_audit(site, config, AuditOptions(pagespeed=False)))
    hashes = {p.url: p.content_hash for p in ctx.pages if p.is_indexable}
    if changed_only:
        from seoforge.indexing.indexnow import changed_urls

        return changed_urls(_store(config), hashes), hashes
    return list(hashes), hashes


@index_app.command("engines")
def index_engines() -> None:
    """Which search engines accept submissions, and how."""
    from seoforge.indexing.engines import ENGINES, NOTE

    table = Table("Engine", "Index", "How to get indexed", "SEOForge")
    for e in ENGINES:
        table.add_row(e.name, e.index, e.how + (f"\n{e.url}" if e.url else ""), e.seoforge or "-")
    console.print(table)
    console.print(f"[dim]{NOTE}[/dim]")


@index_app.command("indexnow-key")
def indexnow_key(
    out: Annotated[
        Path, typer.Option("--out", "-o", help="Directory to write <key>.txt into.")
    ] = Path("."),
) -> None:
    """Generate an IndexNow key and its key file (upload it to your site root)."""
    from seoforge.indexing.indexnow import generate_key

    key = generate_key()
    path = out / f"{key}.txt"
    path.write_text(key, encoding="utf-8")
    console.print(
        f"Key: [bold]{key}[/bold]\nWrote {path}. Upload it so https://<your-site>/{key}.txt "
        "returns the key, then export INDEXNOW_KEY=<key>."
    )


@index_app.command("indexnow")
def indexnow_cmd(
    url: Annotated[str | None, typer.Argument(help="Site URL.")] = None,
    config_path: ConfigOpt = None,
    key: Annotated[
        str | None, typer.Option("--key", help="IndexNow key (default: $INDEXNOW_KEY).")
    ] = None,
    key_location: Annotated[
        str | None, typer.Option("--key-location", help="Key file URL if not at the root.")
    ] = None,
    urls_file: Annotated[
        Path | None, typer.Option("--urls", help="File with one URL per line (skips crawl).")
    ] = None,
    all_urls: Annotated[
        bool, typer.Option("--all", help="Submit every indexable URL, not only changed ones.")
    ] = False,
    max_pages: Annotated[int | None, typer.Option("--max-pages", "-n")] = None,
    yes: Annotated[bool, typer.Option("--yes", help="Skip the confirmation prompt.")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
) -> None:
    """Notify IndexNow engines (Bing, Yandex, Seznam, Naver, Yep) about changed URLs."""
    from seoforge.http import PoliteClient
    from seoforge.indexing import indexnow as ix

    config = _load(config_path)
    site = _site(url, config)
    key = key or config.api.env("indexnow_key_env")
    if not key or not ix.valid_key(key):
        err.print(
            "[red]Provide a valid key (--key or INDEXNOW_KEY). Create one: seoforge index indexnow-key[/red]"
        )
        raise typer.Exit(2)
    urls, hashes = _urls_from(
        site, config, urls_file, changed_only=not all_urls, max_pages=max_pages
    )
    urls, rejected = ix.filter_urls(urls, site)
    if rejected:
        console.print(f"[yellow]Skipping {len(rejected)} URL(s) from other hosts.[/yellow]")
    if not urls:
        console.print("No changed URLs to submit (use --all to force).")
        return

    async def check() -> Any:
        async with PoliteClient(config.crawl) as client:
            return await ix.verify_key_file(client.http, site, key, key_location)

    kc = run(check())
    if not kc.ok:
        err.print(f"[red]Key file check failed at {kc.url}: {kc.detail}[/red]")
        raise typer.Exit(1)
    for u in urls[:10]:
        console.print(f"  {u}")
    if len(urls) > 10:
        console.print(f"  ... and {len(urls) - 10} more")
    if not _confirm_send(f"submit {len(urls)} URL(s) to IndexNow", yes, dry_run):
        return

    async def send() -> Any:
        async with PoliteClient(config.crawl) as client:
            return await ix.submit(client.http, site, key, urls, key_location)

    results = run(send())
    for r in results:
        console.print(f"Batch {r.batch}: {r.count} URL(s) -> HTTP {r.status} ({r.meaning})")
    if all(r.status in (200, 202) for r in results) and hashes:
        ix.remember(_store(config), {u: hashes[u] for u in urls if u in hashes})


@index_app.command("gsc-sitemap")
def gsc_sitemap(
    url: Annotated[str | None, typer.Argument(help="Site URL.")] = None,
    config_path: ConfigOpt = None,
    sitemap_url: Annotated[
        str | None, typer.Option("--sitemap", help="Default: <site>/sitemap.xml")
    ] = None,
    domain_property: Annotated[
        bool, typer.Option("--domain-property", help="Use sc-domain: property.")
    ] = False,
    yes: Annotated[bool, typer.Option("--yes")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
) -> None:
    """Submit a sitemap to Google Search Console."""
    from seoforge.http import PoliteClient
    from seoforge.indexing.gsc import GSCAuthError, GSCClient, get_token, property_url

    config = _load(config_path)
    site = _site(url, config)
    prop = property_url(site, domain_property)
    target = sitemap_url or f"{site.rstrip('/')}/sitemap.xml"
    if not _confirm_send(f"submit {target} to Search Console property {prop}", yes, dry_run):
        return
    try:
        token = get_token(config.api.gsc_credentials_env)
    except GSCAuthError as exc:
        err.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from exc

    async def go() -> Any:
        async with PoliteClient(config.crawl) as client:
            gsc = GSCClient(client.http, token)
            await gsc.submit_sitemap(prop, target)
            return await gsc.list_sitemaps(prop)

    for sm in run(go()):
        console.print(
            f"  {sm.get('path')}  last submitted {sm.get('lastSubmitted')}  "
            f"errors {sm.get('errors', 0)}  warnings {sm.get('warnings', 0)}"
        )


@index_app.command("gsc-inspect")
def gsc_inspect(
    urls: Annotated[list[str], typer.Argument(help="URL(s) to inspect.")],
    config_path: ConfigOpt = None,
    site: Annotated[
        str | None, typer.Option("--site", help="Property URL (default: config site).")
    ] = None,
    domain_property: Annotated[bool, typer.Option("--domain-property")] = False,
    budget: Annotated[
        int, typer.Option("--budget", help="Max inspections per day (<= 2000).")
    ] = 2000,
) -> None:
    """URL Inspection (index status) - quota-aware: 2,000/day and 600/minute per property."""
    from seoforge.http import PoliteClient
    from seoforge.indexing.gsc import GSCAuthError, GSCClient, get_token, property_url

    config = _load(config_path)
    prop = property_url(_site(site, config), domain_property)
    try:
        token = get_token(config.api.gsc_credentials_env)
    except GSCAuthError as exc:
        err.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from exc
    store = _store(config)

    async def go() -> Any:
        async with PoliteClient(config.crawl) as client:
            gsc = GSCClient(client.http, token, store, budget)
            return [await gsc.inspect(prop, u) for u in urls], gsc.remaining(prop)

    results, remaining = run(go())
    table = Table("URL", "Verdict", "Coverage", "Robots", "Google canonical", "Last crawl")
    for r in results:
        table.add_row(
            r.url,
            r.error or r.verdict or "",
            r.coverage or "",
            r.robots or "",
            r.google_canonical or "",
            r.last_crawl or "",
        )
    console.print(table)
    console.print(f"[dim]Remaining inspection budget today: {remaining}[/dim]")


@index_app.command("bing")
def bing_cmd(
    url: Annotated[
        str | None, typer.Argument(help="Site URL (as verified in Bing Webmaster Tools).")
    ] = None,
    config_path: ConfigOpt = None,
    sitemap: Annotated[
        bool, typer.Option("--sitemap/--no-sitemap", help="Submit <site>/sitemap.xml.")
    ] = True,
    urls_file: Annotated[
        Path | None, typer.Option("--urls", help="Also submit these URLs (one per line).")
    ] = None,
    quota_only: Annotated[
        bool, typer.Option("--quota", help="Only show the URL submission quota.")
    ] = False,
    yes: Annotated[bool, typer.Option("--yes")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
) -> None:
    """Bing Webmaster Tools: submit sitemap and/or URLs (quota-aware)."""
    from seoforge.http import PoliteClient
    from seoforge.indexing.bing import BingClient, BingError

    config = _load(config_path)
    site = _site(url, config)
    key = config.api.env("bing_key_env")
    if not key:
        err.print(
            "[red]Set BING_WEBMASTER_API_KEY (Bing Webmaster Tools > Settings > API access).[/red]"
        )
        raise typer.Exit(2)
    urls = [u.strip() for u in urls_file.read_text().splitlines() if u.strip()] if urls_file else []

    async def go() -> None:
        async with PoliteClient(config.crawl) as client:
            bing = BingClient(client.http, key)
            q = await bing.quota(site)
            console.print(f"URL submission quota: {q.daily} today, {q.monthly} this month")
            if quota_only:
                return
            if sitemap and _confirm_send(
                f"submit {site.rstrip('/')}/sitemap.xml to Bing", yes, dry_run
            ):
                await bing.submit_sitemap(site, f"{site.rstrip('/')}/sitemap.xml")
                console.print("Sitemap submitted.")
            if urls and _confirm_send(
                f"submit {min(len(urls), q.daily)} URL(s) to Bing", yes, dry_run
            ):
                n = await bing.submit_urls(site, urls)
                console.print(f"Submitted {n} URL(s).")

    try:
        run(go())
    except BingError as exc:
        err.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc


@app.command()
def diagnose(
    url: Annotated[str, typer.Argument(help="The URL that isn't indexed.")],
    config_path: ConfigOpt = None,
    crawl_pages: Annotated[
        int, typer.Option("--crawl-pages", help="Crawl N pages to count internal links to it.")
    ] = 0,
    gsc: Annotated[
        bool, typer.Option("--gsc", help="Also run Search Console URL Inspection.")
    ] = False,
) -> None:
    """Why isn't this URL indexed? Checks robots, status, redirects, noindex, canonical, sitemap..."""
    from seoforge.http import PoliteClient
    from seoforge.indexing.diagnose import CLOSING_NOTE
    from seoforge.indexing.diagnose import diagnose as run_diagnose

    config = _load(config_path)
    store = _store(config)
    with console.status("Diagnosing"):
        result = run(run_diagnose(url, config, store, crawl_pages=crawl_pages))
    icons = {
        "pass": "[green]PASS[/green]",
        "warn": "[yellow]WARN[/yellow]",
        "fail": "[red]FAIL[/red]",
        "info": "[dim]INFO[/dim]",
    }
    table = Table("", "Check", "Detail", "Fix")
    for f in result.findings:
        table.add_row(icons[f.status], f.check, f.detail, f.fix)
    console.print(table)
    if gsc:
        from seoforge.indexing.gsc import GSCAuthError, GSCClient, get_token, property_url

        try:
            token = get_token(config.api.gsc_credentials_env)
        except GSCAuthError as exc:
            err.print(f"[yellow]GSC skipped: {exc}[/yellow]")
        else:

            async def inspect() -> Any:
                async with PoliteClient(config.crawl) as client:
                    from seoforge.http import origin

                    return await GSCClient(client.http, token, store).inspect(
                        property_url(origin(result.url)), result.url
                    )

            ins = run(inspect())
            console.print(
                f"Search Console: {ins.error or ins.verdict} - {ins.coverage or ''} "
                f"(Google canonical: {ins.google_canonical or 'n/a'})"
            )
    if result.blockers:
        console.print(
            f"[red]{len(result.blockers)} blocker(s) found.[/red] Fix them, then request "
            "indexing in Search Console once."
        )
    else:
        console.print(f"[green]No technical blockers found.[/green] {CLOSING_NOTE}")


# ---- Off-page --------------------------------------------------------------------------------
off_app = typer.Typer(
    help="Ethical off-page helpers: opportunities, broken links, unlinked mentions."
)
app.add_typer(off_app, name="offpage")


@off_app.command("checklist")
def off_checklist(
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Write Markdown to this file.")
    ] = None,
) -> None:
    """Backlink opportunity checklist, directory list and anti-spam policy."""
    from seoforge.offpage.checklist import checklist_markdown

    md = checklist_markdown()
    if out:
        out.write_text(md, encoding="utf-8")
        console.print(f"Wrote {out}")
    else:
        console.print(md)


@off_app.command("policy")
def off_policy() -> None:
    """Print SEOForge's anti-spam policy."""
    from seoforge.offpage.checklist import ANTI_SPAM_POLICY

    console.print(ANTI_SPAM_POLICY)


@off_app.command("broken-links")
def off_broken_links(
    pages: Annotated[list[str], typer.Argument(help="Resource pages in your niche to scan.")],
    config_path: ConfigOpt = None,
    wayback: Annotated[
        bool, typer.Option("--wayback/--no-wayback", help="Look up archived copies.")
    ] = True,
    json_out: Annotated[Path | None, typer.Option("--json")] = None,
) -> None:
    """Find dead outbound links on resource pages (robots-aware) for broken-link building."""
    import json as _json

    import httpx

    from seoforge.http import PoliteClient
    from seoforge.offpage.broken_links import find_broken_links

    config = _load(config_path)

    async def go() -> Any:
        async with PoliteClient(config.crawl) as client:
            api = client.http if wayback else None
            return await find_broken_links(client, pages, api=api)

    with console.status("Checking links"):
        try:
            report = run(go())
        except httpx.HTTPError as exc:
            err.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from exc
    for page, status in report.pages.items():
        if status != "ok":
            console.print(f"[yellow]{page}: {status}[/yellow]")
    table = Table("Resource page", "Dead link", "Anchor", "Status", "Archived copy")
    for d in report.dead:
        table.add_row(d.resource_page, d.url, d.anchor, str(d.status or "error"), d.archived or "-")
    console.print(table if report.dead else "No dead links found.")
    console.print(
        "[dim]Only suggest a replacement you'd genuinely recommend; one personal email per site.[/dim]"
    )
    if json_out:
        json_out.write_text(_json.dumps(report.to_dict(), indent=2), encoding="utf-8")


@off_app.command("mentions")
def off_mentions(
    url: Annotated[str | None, typer.Argument(help="Your site URL.")] = None,
    brand: Annotated[
        str | None, typer.Option("--brand", help="Brand name (default: entity.name).")
    ] = None,
    config_path: ConfigOpt = None,
    json_out: Annotated[Path | None, typer.Option("--json")] = None,
) -> None:
    """Find brand mentions (Hacker News, Wikipedia) and check whether they link to you."""
    import json as _json

    from seoforge.http import PoliteClient
    from seoforge.offpage.mentions import find_mentions

    config = _load(config_path)
    site = _site(url, config)
    name = brand or config.entity.name
    if not name:
        err.print("[red]Pass --brand or set entity.name in seoforge.yaml.[/red]")
        raise typer.Exit(2)

    async def go() -> Any:
        async with PoliteClient(config.crawl) as client:
            return await find_mentions(client, client.http, name, site)

    with console.status("Searching free sources"):
        report = run(go())
    table = Table("Source", "Title", "URL", "Links to you?", "Note")
    for m in report.mentions:
        linked = {True: "[green]yes[/green]", False: "[red]no[/red]", None: "?"}[m.linked]
        table.add_row(m.source, m.title, m.url, linked, m.note)
    console.print(table if report.mentions else "No mentions found in free sources.")
    for source, error in report.errors.items():
        console.print(f"[yellow]{source}: {error}[/yellow]")
    console.print("Search manually (SEOForge does not scrape search engines):")
    for s in report.manual_searches:
        console.print(f"  {s}")
    if json_out:
        json_out.write_text(_json.dumps(report.to_dict(), indent=2), encoding="utf-8")
