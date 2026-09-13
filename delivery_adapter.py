"""Delivery integration layer for Jobby McJobberson.

This module adapts personalized messages into payloads compatible with 
the canonical fleet services: 'campaign-scheduler' and Resend.
"""

import json
import logging
from typing import Any, Dict, List, Optional
from profile import load_profile

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("jobby.delivery")

def resolve_canonical_blocks(profile: Dict[str, Any]) -> Dict[str, str]:
    """
    Resolve the placeholders for the resume and contact blocks.
    In production, these are fetched from the shared context/vault.
    """
    # These would normally be real file reads or API calls to the fleet's assets
    return {
        "[CANONICAL_RESUME_BLOCK]": f"--- ATTACHED: {profile.get('resume_url', 'resume.pdf')} ---",
        "[CONTACT_BLOCK]": f"LinkedIn: linkedin.com/in/josephlee\nPhone: {profile.get('preferences', {}).get('phone', 'Contact via Email')}"
    }

def prepare_delivery_payload(personalized_msg: Dict[str, str], profile: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert a personalized message into a delivery payload for the fleet scheduler.
    """
    body = personalized_msg["body"]
    blocks = resolve_canonical_blocks(profile)
    
    # Replace placeholders with actual canonical content
    for placeholder, content in blocks.items():
        body = body.replace(placeholder, content)
    
    return {
        "recipient": personalized_msg["recipient_email"],
        "subject": personalized_msg["subject"],
        "body": body,
        "metadata": {
            "track": personalized_msg["track"],
            "source": "jobby-mcjobberson",
            "client": profile.get("full_name")
        }
    }

def dispatch_to_fleet(payloads: List[Dict[str, Any]], dry_run: bool = True) -> List[Dict[str, Any]]:
    """
    Interface with the fleet's campaign-scheduler.
    
    Args:
        payloads: List of prepared delivery payloads.
        dry_run: If True, logs the dispatch without calling the remote API.
    """
    results = []
    for payload in payloads:
        if dry_run:
            logger.info(f"[DRY RUN] Dispatching to {payload['recipient']} | Subject: {payload['subject']}")
            results.append({"recipient": payload["recipient"], "status": "dry_run_success"})
        else:
            # This is where the actual HTTP call to the fleet's campaign-scheduler API would go.
            # Example: requests.post("https://fleet.internal/dispatch", json=payload)
            logger.info(f"Dispatching to {payload['recipient']}...")
            results.append({"recipient": payload["recipient"], "status": "dispatched"})
            
    return results

def deliver_batch(personalized_messages: List[Dict[str, Any]], dry_run: bool = True) -> List[Dict[str, Any]]:
    """Full pipeline: resolve blocks -> prepare payloads -> dispatch."""
    profile = load_profile()
    payloads = [prepare_delivery_payload(msg, profile) for msg in personalized_messages]
    return dispatch_to_fleet(payloads, dry_run=dry_run)
