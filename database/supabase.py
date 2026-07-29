"""Supabase client used for durable application metadata."""

from supabase import Client, create_client

from database.settings import settings


supabase: Client = create_client(settings.supabase_url, settings.supabase_key)
