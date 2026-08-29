FROM python:3.12-alpine

RUN apk upgrade --no-cache openssl

RUN addgroup -S runner \
    && adduser -S -u 10001 -G runner runner

RUN pip install --no-cache-dir \
    "pytest>=8.2,<9" "fastapi>=0.115,<1" "httpx>=0.27,<1" "pydantic>=2.8,<3"
USER runner
WORKDIR /workspace/repo
ENTRYPOINT ["python"]
