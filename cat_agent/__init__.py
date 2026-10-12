"""
CatAgent - Autonomous Be100 Gmail & Cat Video Generation Agent.
Monitors Gmail for 'Be100 Prod: [title]' video requests, transcribes them,
and generates a 10-second cat explanation video saved locally.
"""

from .coordinator import CatAgent, cat_agent_instance

__all__ = ["CatAgent", "cat_agent_instance"]
