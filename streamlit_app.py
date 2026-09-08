"""Cloud entrypoint that binds the bundled AnyLogic evidence before loading the UI."""
import sys

from services import anylogic_cloud_service


# Keep the existing app UI unchanged while replacing its external AnyLogic path.
sys.modules["services.anylogic_service"] = anylogic_cloud_service

from app import *  # noqa: E402,F401,F403
