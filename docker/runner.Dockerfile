FROM python:3.12-slim

RUN apt-get update \
    && apt-get install --only-upgrade -y --no-install-recommends openssl \
    && apt-get purge -y perl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    "pytest>=8.2,<9" "fastapi>=0.115,<1" "httpx>=0.27,<1" "pydantic>=2.8,<3" \
    && useradd --create-home --uid 10001 runner

USER runner
WORKDIR /workspace/repo
ENTRYPOINT ["python"]
