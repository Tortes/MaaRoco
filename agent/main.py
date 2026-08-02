import sys

from maa.agent.agent_server import AgentServer
from maa.tasker import Tasker

import pipa_bird


def main() -> None:
    Tasker.set_log_dir("./debug")

    if len(sys.argv) < 2:
        print("Usage: python agent/main.py <socket_id>")
        raise SystemExit(1)

    if not AgentServer.start_up(sys.argv[-1]):
        raise SystemExit("Failed to connect MaaRoco agent server.")

    AgentServer.join()
    AgentServer.shut_down()


if __name__ == "__main__":
    main()
