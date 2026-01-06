"""
Main entry point for Railway deployment
Imports the application from src.main
"""
from src.main import create_app

# Create the Flask application
application = create_app()
app = application  # Alias for compatibility

if __name__ == '__main__':
    app.run()
