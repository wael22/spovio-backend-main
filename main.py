"""
Main entry point for Railway deployment
Imports the application from src.main
"""
import os
from src.main import create_app

# Get environment configuration
env = os.environ.get('FLASK_ENV', 'production')

# Create the Flask application
app = create_app(env)

if __name__ == '__main__':
    # Railway injects PORT as environment variable
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
