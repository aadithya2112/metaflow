# Devcontainer Prototype Demo

This demo shows a Metaflow step being redirected to a local Docker sandbox with a prototype `@devcontainer` decorator.

## Prerequisites

- Docker installed and running
- The repo's local virtualenv available at `./.venv`

## Build the demo image

```sh
docker build -t metaflow-devcontainer-demo:local -f demo/devcontainer/Dockerfile .
```

## Run the demo flow

```sh
./.venv/bin/python devcontainer_demo_flow.py --datastore=local --metadata=local run
```

## What success looks like

- The logs show `[devcontainer] Redirecting step ...`
- The logs show the generated `devcontainer.json` path under `.metaflow/devcontainer/...`
- The `sandboxed` step prints container-only signals such as `/etc/os-release`, hostname, Python version, and `/workspace` as the cwd
- The `sandboxed` step can print `METAFLOW_DEVCONTAINER_JSON`, showing the generated config is visible inside the mounted workspace
- The `end` step prints the artifact produced in the containerized step
- The run completes successfully with normal Metaflow task artifacts in the local `.metaflow` datastore

## What the generated file means

The generated `devcontainer.json` is illustrative for this demo. It mirrors the Docker launcher inputs for:

- image
- workspace folder
- container environment
- bind mounts
- Docker run arguments such as `--user`

The demo still executes with plain Docker, not `devcontainer up/exec`, so the generated file is not yet the source of truth for execution.
