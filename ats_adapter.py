"""ATS Automation boundary for Jobby McJobberson.

This module prepares leads for the canonical 'page-agent' service,
which handles the actual browser automation for form filling and resume uploads.
"""

from typing import Any, Dict, List, Optional
from profile import load_profile

def prepare_ats_payload(lead: Dict[str, Any]) -> Dict[str, Any]:
    """
    Transform a Track 4 lead into a structured task for the page-agent.
    
    The page-agent expects a target URL and a set of fields to find and fill.
    """
    profile = load_profile()
    
    # The target URL is essential for page-agent
    target_url = lead.get("url")
    if not target_url:
        raise ValueError("Track 4 (ATS) leads must have a target URL.")

    # Map lead/profile data to common ATS form fields
    # page-agent uses these as 'hints' to identify form inputs
    form_data = {
        "first_name": profile.get("full_name", "").split(' ')[0],
        "last_name": " ".join(profile.get("full_name", "").split(' ')[1:]),
        "email": lead.get("email"),
        "phone": profile.get("preferences", {}).get("phone", ""),
        "linkedin": "https://linkedin.com/in/josephlee",
        "resume_url": profile.get("resume_url"),
        "target_role": lead.get("name", ""),
    }

    return {
        "action": "ats_apply",
        "target_url": target_url,
        "payload": form_data,
        "context": {
            "client": profile.get("full_name"),
            "track": "track4",
            "lead_id": lead.get("id", "unknown")
        }
    }

def process_ats_batch(leads: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Prepare a batch of ATS applications."""
    results = []
    for lead in leads:
        try:
            results.append(prepare_ats_payload(lead))
        except ValueError as e:
            # Log failure for malformed ATS leads
            results.append({"lead_id": lead.get("id"), "error": str(e)})
    return results
