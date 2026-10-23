FROM node:22-bookworm-slim AS web
WORKDIR /build/web
RUN npm install --global pnpm@9.15.9
COPY web/package.json web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY web/ ./
RUN pnpm build

FROM python:3.12-slim-trixie
WORKDIR /app
RUN pip install --no-cache-dir uv==0.9.5
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project --extra market --extra longbridge
COPY src/ src/
RUN uv sync --frozen --no-dev --extra market --extra longbridge
COPY alembic.ini ./
COPY migrations/ migrations/
COPY --from=web /build/web/dist/ web/dist/
RUN useradd --create-home --uid 10001 tradeguard && chown -R tradeguard:tradeguard /app
USER tradeguard
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8188
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn tradeguard.console:create_app --factory --host 0.0.0.0 --port 8188"]
