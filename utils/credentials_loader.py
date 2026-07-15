"""Load Google credentials from base64 env var for cloud deployment."""
import os
import json
import base64
from pathlib import Path

def load_credentials():
    """
    Load Google service account credentials.
    Priority:
    1. GOOGLE_CREDENTIALS_BASE64 env var (for Render/Railway)
    2. credentials.json file (for local dev)
    """
    # Cloud: decode from base64
    creds_base64 = os.getenv("GOOGLE_CREDENTIALS_BASE64")
    if creds_base64:
        try:
            creds_json = base64.b64decode(creds_base64).decode('utf-8')
            creds_dict = json.loads(creds_json)

            # Write to temp file
            temp_path = "/tmp/credentials.json"
            with open(temp_path, 'w') as f:
                json.dump(creds_dict, f)
            return temp_path
        except Exception as e:
            raise ValueError(f"Failed to decode GOOGLE_CREDENTIALS_BASE64: {e}")

    # Local: use file directly
    local_path = Path(__file__).parent.parent / "credentials.json"
    if local_path.exists():
        return str(local_path)

    raise FileNotFoundError(
        "Google credentials not found. "
        "Set GOOGLE_CREDENTIALS_BASE64 env var or add credentials.json file."
    )
