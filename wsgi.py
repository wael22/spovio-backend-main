"""
WSGI entry point for production deployment
"""
import os
import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.absolute()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Load environment variables from .env if exists
env_file = project_root / '.env'
if env_file.exists():
    print(f"📁 Loading environment variables from {env_file}")
    with open(env_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip())

# Import the Flask application factory
from src.main import create_app

# Create the application instance
env = os.environ.get('FLASK_ENV', 'production')
app = create_app(env)

# This is what Gunicorn will use
application = app

if __name__ == '__main__':
    # For local testing with: python wsgi.py
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
