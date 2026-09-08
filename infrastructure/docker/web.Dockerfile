# syntax=docker/dockerfile:1.7
#
# Build from the repository root. Both Node image arguments are intentionally
# required and must be supplied as immutable image references with @sha256
# digests.

ARG NODE_BUILD_IMAGE
ARG NODE_RUNTIME_IMAGE

FROM ${NODE_BUILD_IMAGE} AS dependencies

WORKDIR /opt/rick/apps/web

COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund

FROM ${NODE_BUILD_IMAGE} AS builder

WORKDIR /opt/rick/apps/web
COPY --from=dependencies /opt/rick/apps/web/node_modules ./node_modules
COPY apps/web/app ./app
COPY apps/web/components ./components
COPY apps/web/lib ./lib
COPY apps/web/types ./types
COPY apps/web/middleware.ts apps/web/next-env.d.ts apps/web/next.config.mjs \
     apps/web/tsconfig.json apps/web/eslint.config.mjs ./
COPY apps/web/package.json apps/web/package-lock.json ./

ENV NEXT_TELEMETRY_DISABLED=1 \
    NODE_ENV=production
ARG RICK_API_INTERNAL_URL=http://api:8000
ENV RICK_API_INTERNAL_URL=${RICK_API_INTERNAL_URL}

RUN npm run build

FROM ${NODE_RUNTIME_IMAGE} AS runtime

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000

WORKDIR /opt/rick/apps/web

RUN addgroup --system --gid 10001 rick \
    && adduser --system --uid 10001 --ingroup rick --home /nonexistent \
       --shell /sbin/nologin rick

COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts --no-audit --no-fund \
    && npm cache clean --force
COPY --from=builder /opt/rick/apps/web/.next ./.next

RUN chown -R 10001:10001 /opt/rick

USER 10001:10001

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:3000/login').then((response) => process.exit(response.ok ? 0 : 1)).catch(() => process.exit(1))"

ENTRYPOINT ["npm", "run", "start", "--", "--hostname", "0.0.0.0", "--port", "3000"]
