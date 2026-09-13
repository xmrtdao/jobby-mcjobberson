"""Client profile management for Jobby McJobberson.

This module handles the storage and retrieval of the client's professional 
identity and targeting preferences, used to route and filter opportunities.
"""

import json
from typing import Any, Dict, List, Optional
from pathlib import Path

PROFILE_FILE = Path("client_profile.json")

def save_profile(profile_data: Dict[str, Any]) -> None:
    """Save the client profile to a local JSON file."""
    with open(PROFILE_FILE, "w", encoding="utf-8") as f:
        json.dump(profile_data, f, indent=2, ensure_ascii=False)

def load_profile() -> Dict[str, Any]:
    """Load the client profile from disk. Returns default profile if not found."""
    if not PROFILE_FILE.exists():
        return {
            "full_name": "Unknown",
            "target_roles": [],
            "resume_url": None,
            "cover_letter_url": None,
            "primary_sources": [],
            "preferences": {}
        }
    
    try:
        with open(PROFILE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}

def update_profile(updates: Dict[str, Any]) -> Dict[str, Any]:
    """Update specific fields in the profile and save."""
    profile = load_profile()
    profile.update(updates)
    save_profile(profile)
    return profile
