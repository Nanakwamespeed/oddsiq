"""Vercel entry point — exposes the Flask WSGI app as 'application'."""
import sys
import os

# Ensure the project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app

application = create_app('production')
