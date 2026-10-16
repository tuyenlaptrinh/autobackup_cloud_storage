#!/usr/bin/python
# coding: utf-8
"""Storage provider catalog (Google Drive + S3-compatible services)."""

from __future__ import print_function

# provider_id -> metadata used by UI / backend
PROVIDERS = {
    "gdrive": {
        "id": "gdrive",
        "name": "Google Drive",
        "kind": "gdrive",
        "hint": "OAuth2 via credentials.json (Desktop app).",
    },
    "aws_s3": {
        "id": "aws_s3",
        "name": "AWS S3",
        "kind": "s3",
        "endpoint": "",
        "region": "us-east-1",
        "path_style": False,
        "hint": "Leave endpoint empty to use the default AWS endpoint.",
    },
    "cloudflare_r2": {
        "id": "cloudflare_r2",
        "name": "Cloudflare R2",
        "kind": "s3",
        "endpoint": "https://<ACCOUNT_ID>.r2.cloudflarestorage.com",
        "region": "auto",
        "path_style": False,
        "hint": "Replace <ACCOUNT_ID> with your Cloudflare account id.",
    },
    "backblaze_b2": {
        "id": "backblaze_b2",
        "name": "Backblaze B2",
        "kind": "s3",
        "endpoint": "https://s3.<REGION>.backblazeb2.com",
        "region": "us-west-004",
        "path_style": False,
        "hint": "Use the S3-compatible endpoint for your B2 region.",
    },
    "do_spaces": {
        "id": "do_spaces",
        "name": "DigitalOcean Spaces",
        "kind": "s3",
        "endpoint": "https://<REGION>.digitaloceanspaces.com",
        "region": "nyc3",
        "path_style": False,
        "hint": "Example: https://nyc3.digitaloceanspaces.com",
    },
    "linode": {
        "id": "linode",
        "name": "Linode Object Storage",
        "kind": "s3",
        "endpoint": "https://<REGION>.linodeobjects.com",
        "region": "us-east-1",
        "path_style": False,
        "hint": "Example: https://us-east-1.linodeobjects.com",
    },
    "wasabi": {
        "id": "wasabi",
        "name": "Wasabi",
        "kind": "s3",
        "endpoint": "https://s3.<REGION>.wasabisys.com",
        "region": "us-east-1",
        "path_style": False,
        "hint": "Example: https://s3.us-east-1.wasabisys.com",
    },
    "minio": {
        "id": "minio",
        "name": "MinIO",
        "kind": "s3",
        "endpoint": "https://minio.example.com",
        "region": "us-east-1",
        "path_style": True,
        "hint": "Self-hosted MinIO or similar. Path-style addressing enabled.",
    },
    "s3_compat": {
        "id": "s3_compat",
        "name": "Other S3-compatible",
        "kind": "s3",
        "endpoint": "",
        "region": "us-east-1",
        "path_style": True,
        "hint": "Any S3-compatible API (Scaleway, Vultr, Contabo, etc.).",
    },
}


def list_providers():
    return [PROVIDERS[k] for k in (
        "gdrive",
        "aws_s3",
        "cloudflare_r2",
        "backblaze_b2",
        "do_spaces",
        "linode",
        "wasabi",
        "minio",
        "s3_compat",
    )]


def get_provider(provider_id):
    return PROVIDERS.get(provider_id) or PROVIDERS["s3_compat"]


def is_s3(provider_id):
    meta = get_provider(provider_id)
    return meta.get("kind") == "s3"
