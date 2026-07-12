import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

print("PROJECT_ROOT:", PROJECT_ROOT)
print("sys.path[0]:", sys.path[0])

from ssip_agents.discovery_agent import DiscoveryAgent

agent = DiscoveryAgent()
agent.run()
agent.close()