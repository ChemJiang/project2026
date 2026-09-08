"""Cloud entrypoint that binds the bundled AnyLogic evidence before loading the UI."""
import runpy
import sys
from pathlib import Path

from services import anylogic_cloud_service


# Keep the existing app UI unchanged while replacing its external AnyLogic path.
sys.modules["services.anylogic_service"] = anylogic_cloud_service

# Streamlit reruns this entry file after every widget interaction. Importing
# ``app`` would only execute it once because Python caches imported modules,
# leaving later reruns with a blank page. Execute the UI script on every rerun.
runpy.run_path(str(Path(__file__).with_name("app.py")), run_name="__main__")
