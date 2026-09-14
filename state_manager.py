"""State management for Jobby McJobberson.

This module handles the durable persistence of leads and their state transitions
using the local-sb REST API (PostgREST).
"""

import hashlib
import json
import logging
from typing import Any, Dict, List, Optional
import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("jobby.state")

# Configuration for the local-sb REST gateway
# Table is confirmed in public schema
REST_URL = "http://127.0.0.1:54321/rest/v1/jobby_leads"

def generate_dedup_hash(lead: Dict[str, Any]) -> str:
    """
    Create a stable SHA256 hash of company + contact + source_url.
    Normalization is handled by lead_utils before this is called.
    """
    components = [
        str(lead.get("company_name") or "").strip().lower(),
        str(lead.get("contact_email") or lead.get("contact_name") or "").strip().lower(),
        str(lead.get("source_url") or "").strip().lower(),
    ]
    raw_string = "|".join(components)
    return hashlib.sha256(raw_string.encode("utf-8")).hexdigest()

def get_lead_by_hash(dedup_hash: str) -> Optional[Dict[str, Any]]:
    """Fetch a lead by its deduplication hash."""
    try:
        params = {"dedup_hash": "eq." + dedup_hash}
        response = requests.get(REST_URL, params=params, timeout=5)
        if response.status_code == 200:
            data = response.json()
            return data[0] if data else None
    except Exception as e:
        logger.error(f"Error fetching lead by hash {dedup_hash}: {e}")
    return None

def create_lead(lead: Dict[str, Any]) -> Dict[str, Any]:
    """Insert a new lead into the system with Agentic CRM defaults."""
    try:
        # Ensure dedup hash is present
        if "dedup_hash" not in lead:
            lead["dedup_hash"] = generate_dedup_hash(lead)
        
        # Agentic CRM Defaults
        lead.setdefault("dossier", [])
        lead.setdefault("confidence_score", 1.0)
        
        response = requests.post(REST_URL, json=lead, timeout=5)
        if response.status_code in (200, 201):
            return response.json()
        elif response.status_code == 409: # Conflict/Duplicate
            logger.info(f"Duplicate lead detected for hash {lead['dedup_hash']}")
            return get_lead_by_hash(lead["dedup_hash"])
    except Exception as e:
        logger.error(f"Error creating lead: {e}")
    return {}

def add_dossier_entry(lead_id: str, entry: Dict[str, Any]) -> bool:
    """
    Append a research note or evidence claim to the lead's dossier.
    entry format: {'claim': '...', 'evidence': '...', 'date': '...'}
    """
    try:
        res = requests.get(f"{REST_URL}?id=eq.{lead_id}", timeout=5)
        if res.status_code != 200 or not res.json():
            return False
        
        lead = res.json()[0]
        dossier = lead.get("dossier", [])
        if not isinstance(dossier, list):
            dossier = []
            
        dossier.append(entry)
        
        patch_res = requests.patch(f"{REST_URL}?id=eq.{lead_id}", json={"dossier": dossier}, timeout=5)
        return patch_res.status_code == 200
    except Exception as e:
        logger.error(f"Error adding dossier entry to {lead_id}: {e}")
        return False

def set_followup_reason(lead_id: str, reason: str) -> bool:
    """Set the intentional reason for the next follow-up."""
    try:
        patch_res = requests.patch(f"{REST_URL}?id=eq.{lead_id}", json={"next_followup_reason": reason}, timeout=5)
        return patch_res.status_code == 200
    except Exception as e:
        logger.error(f"Error setting followup reason for {lead_id}: {e}")
        return False

def transition_state(lead_id: str, new_state: str, actor: str = "jobby-001") -> bool:
    """
    Transition a lead to a new state and append to the state_history.
    This implements the idempotent guard required by Eliza's spec.
    """
    try:
        # 1. Get current state
        res = requests.get(f"{REST_URL}?id=eq.{lead_id}", timeout=5)
        if res.status_code != 200 or not res.json():
            return False
        
        lead = res.json()[0]
        current_state = lead.get("state")
        
        if current_state == new_state:
            return True # Already in desired state
        
        # 2. Prepare history update
        history = lead.get("state_history", [])
        if not isinstance(history, list):
            history = []
            
        history.append({
            "state": new_state,
            "at": "now()",
            "by": actor
        })
        
        # 3. Update record
        update_payload = {
            "state": new_state,
            "state_history": history,
            "updated_at": "now()",
            "last_activity_at": "now()"
        }
        
        patch_res = requests.patch(f"{REST_URL}?id=eq.{lead_id}", json=update_payload, timeout=5)
        return patch_res.status_code == 200
        
    except Exception as e:
        logger.error(f"Error transitioning lead {lead_id} to {new_state}: {e}")
        return False
