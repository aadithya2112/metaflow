from metaflow.decorators import StepDecorator

from .devcontainer_common import (
    DevcontainerException,
    conflicting_decorator_names,
)


class DevcontainerDecorator(StepDecorator):
    name = "devcontainer"
    defaults = {
        "image": "metaflow-devcontainer-demo:local",
    }

    def step_init(
        self, flow, graph, step_name, decorators, environment, flow_datastore, logger
    ):
        if flow_datastore.TYPE != "local":
            raise DevcontainerException(
                "The *@devcontainer* prototype only supports the local datastore. "
                "Run the demo with *--datastore=local*."
            )

        conflicts = conflicting_decorator_names(decorators)
        if conflicts:
            raise DevcontainerException(
                "The *@devcontainer* prototype does not support combining with %s."
                % ", ".join("*@%s*" % name for name in conflicts)
            )

    def runtime_step_cli(
        self, cli_args, retry_count, max_user_code_retries, ubf_context
    ):
        if retry_count > max_user_code_retries:
            return

        cli_args.commands = ["devcontainer", "step"]
        cli_args.command_options["image"] = self.attributes["image"]
