import os
import platform
import socket

from metaflow import FlowSpec, devcontainer, step


class DevcontainerDemoFlow(FlowSpec):
    """
    A minimal proposal demo for the @devcontainer prototype.
    """

    @step
    def start(self):
        self.host_python = platform.python_version()
        self.host_cwd = os.getcwd()
        print("Host step running with Python", self.host_python)
        print("Host working directory:", self.host_cwd)
        self.next(self.sandboxed)

    @devcontainer(image="metaflow-devcontainer-demo:local")
    @step
    def sandboxed(self):
        with open("/etc/os-release", encoding="utf-8") as handle:
            os_release = handle.read().strip()

        self.message = "sandboxed step completed inside Docker"
        self.execution_env = {
            "hostname": socket.gethostname(),
            "python": platform.python_version(),
            "cwd": os.getcwd(),
            "devcontainer_active": os.environ.get("METAFLOW_DEVCONTAINER_ACTIVE"),
            "image": os.environ.get("METAFLOW_DEVCONTAINER_IMAGE"),
            "devcontainer_json": os.environ.get("METAFLOW_DEVCONTAINER_JSON"),
            "os_release": os_release,
        }

        print("Sandbox marker:", self.execution_env["devcontainer_active"])
        print("Generated devcontainer.json:", self.execution_env["devcontainer_json"])
        print("Container hostname:", self.execution_env["hostname"])
        print("Container Python:", self.execution_env["python"])
        print("Container cwd:", self.execution_env["cwd"])
        print("Container /etc/os-release:")
        print(self.execution_env["os_release"])
        self.next(self.end)

    @step
    def end(self):
        assert self.message == "sandboxed step completed inside Docker"
        assert self.execution_env["devcontainer_active"] == "1"

        print("Received message:", self.message)
        print(
            "Downstream artifact devcontainer.json:",
            self.execution_env["devcontainer_json"],
        )
        print("Downstream artifact image:", self.execution_env["image"])
        print("Downstream artifact cwd:", self.execution_env["cwd"])
        print("Flow continuation confirmed.")


if __name__ == "__main__":
    DevcontainerDemoFlow()
