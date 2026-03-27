"""
Main entry point for the PrimeMart Flask application.
Run this script to start the development server.
"""

import os
import sys

# Add the current directory to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from marketplace import create_app

# Set environment variables for development
os.environ['FLASK_APP'] = 'marketplace'
os.environ['FLASK_ENV'] = 'development'

# Create the application instance
app = create_app()

if __name__ == '__main__':
    # Start the Flask development server on port 5001
    # Host '0.0.0.0' allows external access (e.g., from other devices on local network)
    print("Starting PrimeMart MarketPlace on http://localhost:5001")
    app.run(debug=True, port=5001, host='0.0.0.0')
