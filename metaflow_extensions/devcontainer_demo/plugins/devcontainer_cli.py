import os
import subprocess
import sys

from metaflow._vendor import click

from metaflow.exception import CommandException
from metaflow.plugins.datastores.local_storage import LocalStorage
from metaflow.util import which

from .devcontainer_common import (
    build_launch_spec,
    docker_command_to_string,
    write_devcontainer_config,
)


@click.group()
def cli():
    pass


@cli.group(help="Commands related to the @devcontainer prototype.")
def devcontainer():
    pass


@devcontainer.command(
    "step",
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
    help="Execute a single task inside a local Docker sandbox.",
)
@click.argument("step-name")
@click.option(
    "--image",
    default="metaflow-devcontainer-demo:local",
    show_default=True,
    help="Docker image used for the sandboxed step.",
)
@click.pass_context
def step(ctx, step_name, image):
    if which("docker") is None:
        raise CommandException(
            "The *@devcontainer* prototype requires Docker to be installed."
        )

    datastore_root = LocalStorage.get_datastore_root_from_config(
        lambda *args, **kwargs: None, create_on_absent=False
    )
    if datastore_root is None:
        raise CommandException(
            "The *@devcontainer* prototype requires an existing local *.metaflow* datastore."
        )

    top_level_params = dict(ctx.parent.parent.params)
    launch_spec = build_launch_spec(
        image=image,
        flow_file=sys.argv[0],
        datastore_root=datastore_root,
        top_level_params=top_level_params,
        step_name=step_name,
        step_args=list(ctx.args),
    )

    echo = getattr(ctx.obj, "echo_always", click.echo)
    echo(
        "[devcontainer] Redirecting step *%s* to Docker image *%s*"
        % (step_name, image),
        fg="magenta",
        bold=False,
    )
    echo(
        "[devcontainer] Mounting workspace *%s* at */workspace*"
        % launch_spec.workspace_layout.workspace_root,
        fg="magenta",
        bold=False,
    )
    write_devcontainer_config(
        launch_spec.devcontainer_json_host_path,
        launch_spec.devcontainer_config,
    )
    echo(
        "[devcontainer] Generated devcontainer.json: *%s*"
        % launch_spec.devcontainer_json_host_path,
        fg="magenta",
        bold=False,
    )
    echo(
        "[devcontainer] Docker command: %s"
        % docker_command_to_string(launch_spec.docker_command),
        fg="magenta",
        bold=False,
    )

    result = subprocess.run(
        launch_spec.docker_command,
        env=os.environ.copy(),
        check=False,
    )
    ctx.exit(result.returncode)
