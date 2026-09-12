import sys
from pathlib import Path

# CPython's embeddable distribution uses an isolated ``._pth`` file and does
# not automatically add the executed script's directory to sys.path. Make the
# sibling Agent modules importable regardless of how MFA launches this file.
agent_dir = str(Path(__file__).resolve().parent)
if agent_dir not in sys.path:
    sys.path.insert(0, agent_dir)

from maa.agent.agent_server import AgentServer
from maa.tasker import Tasker

import pipa_bird
import launch_game
import battle_input


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
