# SEOForge container. Build with JS rendering support:
#   docker build --build-arg WITH_BROWSER=1 -t seoforge .
# Run (reports land in ./seoforge-report on the host):
#   docker run --rm --user "$(id -u):$(id -g)" -v "$PWD:/work" seoforge audit https://example.com
FROM python:3.11-slim

ARG WITH_BROWSER=0
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --upgrade pip && pip install ".[google]" \
    && if [ "$WITH_BROWSER" = "1" ]; then playwright install --with-deps chromium; fi

RUN useradd --create-home --uid 10001 seoforge && mkdir /work && chown seoforge /work
USER seoforge
WORKDIR /work
ENTRYPOINT ["seoforge"]
CMD ["--help"]
