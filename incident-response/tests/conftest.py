import sys
from pathlib import Path

# The responder modules live next to this folder (incident-response/ is not a package).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
