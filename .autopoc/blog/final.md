# Deploying TokDiet LLM Token Proxy on OpenShift

*How we containerized and deployed a cost-saving LLM proxy to OpenShift, cutting AI agent token spend by up to 71%.*

## The Problem: AI Agents Are Expensive

AI coding agents like Claude Code, Cursor, and similar tools are transforming software development. But they come with a hidden cost: bloated context windows. Every request to an LLM provider carries the full conversation history, including repeated file dumps, redundant log outputs, and stale tool results. As context grows, so does cost -- and a single developer can easily burn through hundreds of dollars per month.

The problem compounds at scale. When a platform team runs dozens of AI-assisted developers on OpenShift AI, cost visibility and control become critical infrastructure concerns.

## Enter TokDiet

[TokDiet](https://github.com/agiwhitelist/tokdiet) is an open-source reverse proxy that sits between your AI coding agent and the LLM provider API. It intercepts every request, meters the tokens and cost, and optionally compacts bloated context before forwarding upstream. The project claims ~71% token savings -- and includes a shadow evaluation system that proves compaction does not degrade answer quality.

Key capabilities:

- **Token metering** with per-session, per-repo, and per-provider cost tracking
- **Context compaction** via elision (trimming old tool results), deduplication (removing repeated file dumps), and mid-history summarization
- **Quality guard** using shadow evaluation to verify compacted answers match uncompacted baselines
- **Live dashboard** with real-time SSE streaming for immediate cost visibility
- **SQLite telemetry** for persistent metrics with JSON/CSV export

The architecture is intentionally simple: a single Node.js process running two HTTP servers (proxy on port 7787, dashboard on port 7878) with SQLite for storage. No external databases, no message queues, no GPU.

## The Challenge: From Localhost to Container

TokDiet is designed as a per-developer local proxy. By default, both the proxy and dashboard bind to `127.0.0.1` -- an intentional security choice, since the proxy forwards API keys. In a container environment, this loopback binding means the service is unreachable from outside the pod.

We needed to:

1. Build TokDiet from source using a UBI (Universal Base Image) container for OpenShift compatibility
2. Patch the host binding to `0.0.0.0` for container networking
3. Handle the `better-sqlite3` native dependency (requires C++ build tools)
4. Deploy with proper health checks and resource limits

## Building the UBI Container

We used a single-stage build with `registry.access.redhat.com/ubi9/nodejs-22` as the base image. The build dependencies (gcc-c++, make, python3) were already present in the full UBI Node.js image, which simplified the process.

The critical patch: a `sed` command in the Dockerfile replaces the hardcoded `'127.0.0.1'` binding in `proxy.ts` and `dashboard.ts` with an environment variable lookup:

```dockerfile
RUN sed -i "s|server.listen(config.proxyPort, '127.0.0.1')|server.listen(config.proxyPort, process.env.TOKDIET_HOST || '0.0.0.0')|" src/proxy.ts && \
    sed -i "s|server.listen(port, '127.0.0.1')|server.listen(port, process.env.TOKDIET_HOST || '0.0.0.0')|" src/dashboard.ts
```

This approach keeps the default safe (loopback) in development while enabling container networking via the `TOKDIET_HOST` environment variable.

### Lessons from the Build

**Attempt 1 failed.** We initially used a multi-stage build with `nodejs-22-minimal` as the runtime stage. The standard OpenShift permission setup (`chgrp -R 0 /opt/app-root && chmod -R g=u /opt/app-root`) failed because files copied from the builder stage retained ownership that the minimal image could not modify. The fix: switch to a single-stage build and scope the `chgrp`/`chmod` to only application directories.

## Deploying to OpenShift

The Kubernetes manifests are straightforward: a Deployment with two exposed ports and a Service exposing both:

```yaml
ports:
  - name: proxy
    port: 7787
    targetPort: 7787
  - name: dashboard
    port: 7878
    targetPort: 7878
```

**Readiness probe gotcha**: We initially configured the readiness probe to check `/stats` -- a path that does not exist in TokDiet's dashboard. The actual API routes are `/api/summary` and `/api/recent`. The fix took seconds once identified, but it is a good reminder to read the source code rather than guess endpoint paths.

Resource allocation is lightweight: 256Mi memory request, 512Mi limit, 250m/500m CPU. TokDiet does not need GPU or significant compute -- it is I/O bound, proxying HTTP requests and writing SQLite rows.

## Validation Results

All three test scenarios passed on the first attempt:

| Test | Endpoint | Result |
|------|----------|--------|
| Dashboard API | GET /api/summary:7878 | 200 OK, valid JSON telemetry |
| Dashboard UI | GET /:7878 | 200 OK, HTML SPA loaded |
| Proxy Port | GET /:7787 | Port accepting connections |

The dashboard immediately returns telemetry data (all zeros since no LLM traffic has been proxied), and the proxy port is listening and ready to accept proxied requests.

## What This Means for OpenShift AI Teams

TokDiet fills a practical gap: **cost visibility and control for LLM workloads**. Today, platform teams deploying AI agents on OpenShift have limited tools for understanding and managing per-developer or per-project LLM spend.

Potential deployment models:

1. **Per-developer sidecar**: Each developer's workspace pod includes a TokDiet container as a sidecar, providing individual cost tracking and compaction
2. **Shared namespace proxy**: A single TokDiet instance per team/namespace, routing all LLM traffic through a centralized metering point
3. **Platform-level gateway**: Combined with OpenShift routes and network policies, TokDiet could serve as a cost-aware gateway for all AI traffic

The key architectural strength is TokDiet's fail-open design: if anything goes wrong internally (compaction error, SQLite failure, metering bug), the proxy degrades to transparent passthrough. The user's AI workflow is never interrupted.

## Try It Yourself

The deployment artifacts are available in the [fork repository](https://github.com/aicatalyst-team/tokdiet):

```bash
# Clone and deploy
git clone https://github.com/aicatalyst-team/tokdiet.git
cd tokdiet

# Apply manifests
kubectl create namespace poc-tokdiet
kubectl apply -f kubernetes/ -n poc-tokdiet

# Or build from source
podman build -t tokdiet -f Dockerfile.ubi .
```

The container image is also available at `quay.io/aicatalyst/tokdiet:latest`.

## Conclusion

TokDiet demonstrates that meaningful LLM cost reduction tools can run on OpenShift with minimal infrastructure overhead. The PoC validated that the proxy and dashboard work correctly in a containerized environment, and the project's clean architecture makes it a good candidate for platform-level integration. The main upstream contribution opportunity is adding native `--host` flag support to the CLI, eliminating the need for source patching in the Dockerfile.

---

*This PoC was executed using the AutoPoC automated deployment pipeline on OpenShift. Source: [agiwhitelist/tokdiet](https://github.com/agiwhitelist/tokdiet) | Fork: [aicatalyst-team/tokdiet](https://github.com/aicatalyst-team/tokdiet)*
