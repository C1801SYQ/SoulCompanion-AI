"""Deployment entry point: uvicorn app:app from cloud/api."""

from soulcompanion_cloud.app import create_app

app = create_app()
