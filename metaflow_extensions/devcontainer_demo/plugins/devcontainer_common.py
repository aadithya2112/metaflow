import json
import os
import shlex
from collections import namedtuple

from metaflow.exception import MetaflowException
from metaflow.user_configs.config_options import ConfigInput

try:
    import pwd
except ImportError:
    pwd = None

WORKSPACE_MOUNT = "/workspace"
LOCAL_CONFIG_MOUNT = "/tmp/metaflow-local-config.json"
DEVCONTAINER_ACTIVE_ENV = "METAFLOW_DEVCONTAINER_ACTIVE"
DEVCONTAINER_IMAGE_ENV = "METAFLOW_DEVCONTAINER_IMAGE"
DEVCONTAINER_JSON_ENV = "METAFLOW_DEVCONTAINER_JSON"
DEVCONTAINER_JSON_DIR = "devcontainer"
CONFLICTING_DECORATORS = frozenset(["batch", "kubernetes", "parallel", "pypi", "conda"])
WorkspaceLayout = namedtuple(
    "WorkspaceLayout",
    [
        "workspace_root",
        "datastore_root",
        "flow_file",
        "flow_relpath",
        "container_workspace",
    ],
)
LaunchSpec = namedtuple(
    "LaunchSpec",
    [
        "docker_command",
        "inner_command",
        "workspace_layout",
        "mounted_local_config",
        "devcontainer_config",
        "devcontainer_json_host_path",
        "devcontainer_json_container_path",
    ],
)


class DevcontainerException(MetaflowException):
    headline = "Devcontainer prototype error"


def conflicting_decorator_names(decorators):
    return sorted(
        deco.name for deco in decorators if deco.name in CONFLICTING_DECORATORS
    )


def resolve_workspace_layout(flow_file, datastore_root):
    if not datastore_root:
        raise DevcontainerException(
            "The *@devcontainer* prototype requires a local datastore root."
        )

    datastore_root = os.path.abspath(datastore_root)
    workspace_root = os.path.dirname(datastore_root)
    flow_file = os.path.abspath(flow_file)

    try:
        common_path = os.path.commonpath([workspace_root, flow_file])
    except ValueError as ex:
        raise DevcontainerException(
            "The flow file and datastore root must live on the same filesystem."
        ) from ex

    if common_path != workspace_root:
        raise DevcontainerException(
            "The flow file must live under the same workspace as the local datastore."
        )

    flow_relpath = os.path.relpath(flow_file, workspace_root)
    if flow_relpath.startswith(".."):
        raise DevcontainerException(
            "The flow file must be reachable from the mounted workspace."
        )

    return WorkspaceLayout(
        workspace_root=workspace_root,
        datastore_root=datastore_root,
        flow_file=flow_file,
        flow_relpath=flow_relpath,
        container_workspace=WORKSPACE_MOUNT,
    )


def dict_to_cli_tokens(params, skip_keys=None):
    skip_keys = set(skip_keys or [])
    for key, value in params.items():
        if key in skip_keys or value is None or value is False:
            continue

        if key == "decospecs":
            key = "with"

        if key in ("config", "config_value"):
            for config_name in value.keys():
                yield "--config-value"
                yield str(config_name)
                yield str(ConfigInput.make_key_name(config_name))
            continue

        key = key.replace("_", "-")
        values = value if isinstance(value, (list, tuple, set)) else [value]
        for item in values:
            yield "--%s" % key
            if not isinstance(item, bool):
                token_values = item if isinstance(item, tuple) else (item,)
                for token in token_values:
                    yield str(token)


def docker_command_to_string(command):
    return " ".join(shlex.quote(part) for part in command)


def step_arg_value(step_args, option_name, default=None):
    option_name = "--%s" % option_name.lstrip("-")
    for index, value in enumerate(step_args):
        if value == option_name and index + 1 < len(step_args):
            return step_args[index + 1]
    return default


def host_user_env():
    username = (
        os.environ.get("SUDO_USER")
        or os.environ.get("USERNAME")
        or os.environ.get("USER")
    )
    if not username and pwd is not None and hasattr(os, "getuid"):
        try:
            username = pwd.getpwuid(os.getuid()).pw_name
        except KeyError:
            username = None

    if not username:
        return {}

    return {
        "USER": username,
        "USERNAME": username,
    }


def container_path_for_host_file(layout, host_path):
    host_path = os.path.abspath(host_path)
    try:
        common_path = os.path.commonpath([layout.workspace_root, host_path])
    except ValueError as ex:
        raise DevcontainerException(
            "Expected a path under the mounted workspace but got: %s" % host_path
        ) from ex

    if common_path != layout.workspace_root:
        raise DevcontainerException(
            "Expected a path under the mounted workspace but got: %s" % host_path
        )

    rel_path = os.path.relpath(host_path, layout.workspace_root)
    return os.path.join(layout.container_workspace, rel_path).replace("\\", "/")


def devcontainer_json_host_path(datastore_root, step_name, step_args):
    run_id = step_arg_value(step_args, "run-id")
    task_id = step_arg_value(step_args, "task-id")
    retry_count = step_arg_value(step_args, "retry-count", "0")

    if run_id is None or task_id is None:
        raise DevcontainerException(
            "Could not derive the generated devcontainer.json path because the step "
            "arguments are missing --run-id or --task-id."
        )

    return os.path.join(
        os.path.abspath(datastore_root),
        DEVCONTAINER_JSON_DIR,
        str(run_id),
        step_name,
        str(task_id),
        "attempt-%s" % retry_count,
        "devcontainer.json",
    )


def build_container_env(image, devcontainer_json_container_path):
    container_env = {
        "PYTHONPATH": WORKSPACE_MOUNT,
        "METAFLOW_EXTENSIONS_SEARCH_DIRS": WORKSPACE_MOUNT,
        "PYTHONUNBUFFERED": "x",
        DEVCONTAINER_ACTIVE_ENV: "1",
        DEVCONTAINER_IMAGE_ENV: image,
        DEVCONTAINER_JSON_ENV: devcontainer_json_container_path,
    }
    container_env.update(host_user_env())
    return container_env


def build_mounts(layout, mounted_local_config=None):
    mounts = [
        "source=%s,target=%s,type=bind"
        % (layout.workspace_root, layout.container_workspace)
    ]
    if mounted_local_config:
        mounts.append(
            "source=%s,target=%s,type=bind,readonly"
            % (
                mounted_local_config["host_path"],
                mounted_local_config["container_path"],
            )
        )
    return mounts


def build_run_args():
    if hasattr(os, "getuid") and hasattr(os, "getgid"):
        return ["--user", "%s:%s" % (os.getuid(), os.getgid())]
    return []


def build_devcontainer_config(
    image,
    layout,
    mounted_local_config,
    devcontainer_json_container_path,
    step_name,
    step_args,
):
    task_id = step_arg_value(step_args, "task-id", "unknown")
    config = {
        "name": "metaflow-%s-%s" % (step_name, task_id),
        "image": image,
        "workspaceFolder": layout.container_workspace,
        "containerEnv": build_container_env(image, devcontainer_json_container_path),
        "mounts": build_mounts(layout, mounted_local_config),
        "runArgs": build_run_args(),
        "overrideCommand": False,
    }
    return config


def write_devcontainer_config(path, config):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(config, handle, indent=2, sort_keys=True)
        handle.write("\n")


def build_launch_spec(
    image,
    flow_file,
    datastore_root,
    top_level_params,
    step_name,
    step_args,
):
    layout = resolve_workspace_layout(flow_file, datastore_root)
    top_level_params = dict(top_level_params)

    mounted_local_config = None
    local_config_file = top_level_params.pop("local_config_file", None)
    top_level_params.pop("datastore_root", None)

    extra_mounts = []
    if local_config_file:
        local_config_file = os.path.abspath(local_config_file)
        if not os.path.isfile(local_config_file):
            raise DevcontainerException(
                "The local config file needed by this task does not exist: %s"
                % local_config_file
            )
        mounted_local_config = {
            "host_path": local_config_file,
            "container_path": LOCAL_CONFIG_MOUNT,
        }
        extra_mounts.extend(
            [
                "--volume",
                "%s:%s:ro"
                % (
                    mounted_local_config["host_path"],
                    mounted_local_config["container_path"],
                ),
            ]
        )
        top_level_params["local_config_file"] = mounted_local_config["container_path"]

    devcontainer_json_host = devcontainer_json_host_path(
        layout.datastore_root, step_name, step_args
    )
    devcontainer_json_container = container_path_for_host_file(
        layout, devcontainer_json_host
    )
    devcontainer_config = build_devcontainer_config(
        image=image,
        layout=layout,
        mounted_local_config=mounted_local_config,
        devcontainer_json_container_path=devcontainer_json_container,
        step_name=step_name,
        step_args=step_args,
    )

    top_level_tokens = list(dict_to_cli_tokens(top_level_params))
    inner_command = ["python", "-u", layout.flow_relpath]
    inner_command.extend(top_level_tokens)
    inner_command.extend(["step", step_name])
    inner_command.extend(step_args)

    docker_command = ["docker", "run", "--rm"]
    docker_command.extend(build_run_args())

    for key, value in build_container_env(image, devcontainer_json_container).items():
        docker_command.extend(["--env", "%s=%s" % (key, value)])

    docker_command.extend(
        [
            "--volume",
            "%s:%s" % (layout.workspace_root, layout.container_workspace),
            "--workdir",
            layout.container_workspace,
        ]
    )
    docker_command.extend(extra_mounts)
    docker_command.append(image)
    docker_command.extend(inner_command)

    return LaunchSpec(
        docker_command=docker_command,
        inner_command=inner_command,
        workspace_layout=layout,
        mounted_local_config=mounted_local_config,
        devcontainer_config=devcontainer_config,
        devcontainer_json_host_path=devcontainer_json_host,
        devcontainer_json_container_path=devcontainer_json_container,
    )
