import json
import os
import tempfile
import unittest

import metaflow

from metaflow_extensions.devcontainer_demo.plugins.devcontainer_common import (
    DEVCONTAINER_JSON_ENV,
    DEVCONTAINER_IMAGE_ENV,
    DEVCONTAINER_JSON_DIR,
    LOCAL_CONFIG_MOUNT,
    WORKSPACE_MOUNT,
    build_launch_spec,
    devcontainer_json_host_path,
    resolve_workspace_layout,
    write_devcontainer_config,
)
from metaflow_extensions.devcontainer_demo.plugins.devcontainer_decorator import (
    DevcontainerDecorator,
)
from metaflow_extensions.devcontainer_demo.plugins.devcontainer_common import (
    DevcontainerException,
)


class DummyDecorator(object):
    def __init__(self, name):
        self.name = name


class DummyFlowDatastore(object):
    def __init__(self, datastore_type):
        self.TYPE = datastore_type


class DummyCLIArgs(object):
    def __init__(self):
        self.commands = ["step"]
        self.command_options = {}


class TestDevcontainerPrototype(unittest.TestCase):
    def test_metaflow_exports_devcontainer(self):
        self.assertTrue(callable(metaflow.devcontainer))

    def test_step_init_requires_local_datastore(self):
        decorator = DevcontainerDecorator()

        with self.assertRaises(DevcontainerException):
            decorator.step_init(
                flow=None,
                graph=None,
                step_name="sandboxed",
                decorators=[decorator],
                environment=None,
                flow_datastore=DummyFlowDatastore("s3"),
                logger=None,
            )

    def test_step_init_rejects_conflicting_decorators(self):
        decorator = DevcontainerDecorator()

        with self.assertRaises(DevcontainerException):
            decorator.step_init(
                flow=None,
                graph=None,
                step_name="sandboxed",
                decorators=[decorator, DummyDecorator("batch")],
                environment=None,
                flow_datastore=DummyFlowDatastore("local"),
                logger=None,
            )

    def test_runtime_step_cli_rewrites_command(self):
        decorator = DevcontainerDecorator(attributes={"image": "demo:latest"})
        cli_args = DummyCLIArgs()

        decorator.runtime_step_cli(
            cli_args, retry_count=0, max_user_code_retries=1, ubf_context=None
        )

        self.assertEqual(["devcontainer", "step"], cli_args.commands)
        self.assertEqual("demo:latest", cli_args.command_options["image"])

    def test_runtime_step_cli_stops_rewriting_after_user_retries(self):
        decorator = DevcontainerDecorator(attributes={"image": "demo:latest"})
        cli_args = DummyCLIArgs()

        decorator.runtime_step_cli(
            cli_args, retry_count=3, max_user_code_retries=1, ubf_context=None
        )

        self.assertEqual(["step"], cli_args.commands)
        self.assertEqual({}, cli_args.command_options)

    def test_resolve_workspace_layout_uses_flow_relative_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            datastore_root = os.path.join(tmpdir, ".metaflow")
            nested = os.path.join(tmpdir, "flows")
            os.makedirs(datastore_root)
            os.makedirs(nested)
            flow_file = os.path.join(nested, "demo_flow.py")
            with open(flow_file, "w", encoding="utf-8") as handle:
                handle.write("print('hello')\n")

            layout = resolve_workspace_layout(flow_file, datastore_root)

            self.assertEqual(tmpdir, layout.workspace_root)
            self.assertEqual("flows/demo_flow.py", layout.flow_relpath)

    def test_devcontainer_json_host_path_is_stable_and_scoped_by_attempt(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            datastore_root = os.path.join(tmpdir, ".metaflow")
            os.makedirs(datastore_root)

            path = devcontainer_json_host_path(
                datastore_root,
                "sandboxed",
                [
                    "--run-id",
                    "123",
                    "--task-id",
                    "7",
                    "--retry-count",
                    "2",
                ],
            )

            self.assertEqual(
                os.path.join(
                    datastore_root,
                    DEVCONTAINER_JSON_DIR,
                    "123",
                    "sandboxed",
                    "7",
                    "attempt-2",
                    "devcontainer.json",
                ),
                path,
            )

    def test_build_launch_spec_mounts_workspace_and_local_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            datastore_root = os.path.join(tmpdir, ".metaflow")
            os.makedirs(datastore_root)

            flow_file = os.path.join(tmpdir, "demo_flow.py")
            with open(flow_file, "w", encoding="utf-8") as handle:
                handle.write("print('hello')\n")

            config_file = os.path.join(tmpdir, "config.json")
            with open(config_file, "w", encoding="utf-8") as handle:
                handle.write("{}\n")

            launch_spec = build_launch_spec(
                image="metaflow-devcontainer-demo:local",
                flow_file=flow_file,
                datastore_root=datastore_root,
                top_level_params={
                    "quiet": True,
                    "metadata": "local",
                    "environment": "local",
                    "datastore": "local",
                    "datastore_root": datastore_root,
                    "local_config_file": config_file,
                },
                step_name="sandboxed",
                step_args=[
                    "--run-id",
                    "123",
                    "--task-id",
                    "1",
                    "--retry-count",
                    "0",
                ],
            )

            command = launch_spec.docker_command
            config = launch_spec.devcontainer_config

            self.assertIn("%s:%s" % (tmpdir, WORKSPACE_MOUNT), command)
            self.assertIn(
                "%s:%s:ro" % (config_file, LOCAL_CONFIG_MOUNT),
                command,
            )
            self.assertIn(
                "%s=metaflow-devcontainer-demo:local" % DEVCONTAINER_IMAGE_ENV,
                command,
            )
            self.assertIn(
                "%s=%s"
                % (DEVCONTAINER_JSON_ENV, launch_spec.devcontainer_json_container_path),
                command,
            )
            self.assertNotIn(datastore_root, launch_spec.inner_command)
            self.assertEqual(
                LOCAL_CONFIG_MOUNT,
                launch_spec.mounted_local_config["container_path"],
            )
            self.assertEqual(
                os.path.join(
                    datastore_root,
                    DEVCONTAINER_JSON_DIR,
                    "123",
                    "sandboxed",
                    "1",
                    "attempt-0",
                    "devcontainer.json",
                ),
                launch_spec.devcontainer_json_host_path,
            )
            self.assertEqual(
                [
                    "python",
                    "-u",
                    "demo_flow.py",
                    "--quiet",
                    "--metadata",
                    "local",
                    "--environment",
                    "local",
                    "--datastore",
                    "local",
                    "--local-config-file",
                    LOCAL_CONFIG_MOUNT,
                    "step",
                    "sandboxed",
                    "--run-id",
                    "123",
                    "--task-id",
                    "1",
                    "--retry-count",
                    "0",
                ],
                launch_spec.inner_command,
            )
            self.assertEqual("metaflow-devcontainer-demo:local", config["image"])
            self.assertEqual(WORKSPACE_MOUNT, config["workspaceFolder"])
            self.assertEqual(False, config["overrideCommand"])
            self.assertEqual(
                launch_spec.devcontainer_json_container_path,
                config["containerEnv"][DEVCONTAINER_JSON_ENV],
            )
            self.assertIn(
                "source=%s,target=%s,type=bind" % (tmpdir, WORKSPACE_MOUNT),
                config["mounts"],
            )
            self.assertIn(
                "source=%s,target=%s,type=bind,readonly"
                % (config_file, LOCAL_CONFIG_MOUNT),
                config["mounts"],
            )
            self.assertEqual(
                ["--user", "%s:%s" % (os.getuid(), os.getgid())],
                config["runArgs"],
            )

    def test_write_devcontainer_config_writes_json_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = os.path.join(tmpdir, "nested", "devcontainer.json")
            config = {"image": "demo", "workspaceFolder": "/workspace"}

            write_devcontainer_config(target, config)

            with open(target, "r", encoding="utf-8") as handle:
                persisted = json.load(handle)

            self.assertEqual(config, persisted)


if __name__ == "__main__":
    unittest.main()
