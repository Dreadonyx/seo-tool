# Audit on every deploy with GitHub Actions

```yaml
# .github/workflows/seo.yml
name: SEO audit
on:
  deployment_status:
  workflow_dispatch:
jobs:
  audit:
    if: github.event_name == 'workflow_dispatch' || github.event.deployment_status.state == 'success'
    runs-on: ubuntu-latest
    steps:
      - uses: Dreadonyx/seo-tool@main
        with:
          url: ${{ github.event.deployment_status.environment_url || 'https://example.com' }}
          max-pages: "300"
          fail-on: critical
          pagespeed-api-key: ${{ secrets.PAGESPEED_API_KEY }}
```

The report is uploaded as the `seoforge-report` artifact and the Markdown summary appears on
the run page. Use `fail-on: never` to report without blocking deploys.
