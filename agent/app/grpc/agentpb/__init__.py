"""Generated gRPC bindings for agent.v1."""

import sys

from . import agent_pb2 as _agent_pb2

# grpc_tools generates absolute imports in agent_pb2_grpc.py. Register the
# generated module under the expected top-level name so package imports work.
sys.modules.setdefault("agent_pb2", _agent_pb2)
