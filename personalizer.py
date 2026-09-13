"""Personalization layer for Jobby McJobberson.

This module generates tailored outreach messages by combining routed lead 
data with canonical templates and client profile information.
"""

from typing import Any, Dict, Optional
from profile import load_profile

# Professional fallbacks for missing data
FALLBACKS = {
    "name": "Hiring Manager",
    "company": "your company",
}

# Template Registry (Structure only - actual bodies reside in shared context/profile)
# In a real production environment, these would be loaded from a secure vault or DB.
TEMPLATES = {
    "track1": {
        "subject": "Consultancy Inquiry: {role} - {client_name}",
        "greeting": "Hi {recipient_name},",
        "pitch": "I've been following {company}'s work in the sector and believe my expertise in {target_roles} could provide immediate value to your current initiatives.",
    },
    "track2": {
        "subject": "Contract Opportunity: {role} - {client_name}",
        "greeting": "Hello {recipient_name},",
        "pitch": "I am reaching out regarding contract opportunities at {company}. My background in {target_roles} aligns well with the requirements for temporary high-impact roles.",
    },
    "track3": {
        "subject": "Application for {role} - {client_name}",
        "greeting": "Dear {recipient_name},",
        "pitch": "I am writing to express my strong interest in the {role} position at {company}. With a proven track record in {target_roles}, I am confident I can contribute to your team's success.",
    },
}

def get_template(track: str) -> Dict[str, str]:
    """Retrieve the template for the given track, defaulting to track3."""
    return TEMPLATES.get(track, TEMPLATES["track3"])

def personalize_message(lead: Dict[str, Any], profile: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """
    Generate a personalized outreach message for a routed lead.
    
    Args:
        lead: The routed lead containing 'track', 'name', 'company', etc.
        profile: Optional client profile. If None, loads from disk.
    """
    if profile is None:
        profile = load_profile()
    
    track = lead.get("track", "track3")
    template = get_template(track)
    
    # Resolve recipient details with fallbacks
    recipient_name = lead.get("name") or FALLBACKS["name"]
    company_name = lead.get("company") or FALLBACKS["company"]
    
    # Resolve client details
    client_name = profile.get("full_name", "Joseph Lee")
    target_roles = ", ".join(profile.get("target_roles", ["my field"]))
    
    # Use the lead's name as the 'role' if it's a job-title lead, 
    # otherwise use the first target role from the profile.
    role_context = lead.get("name") if "Engineer" in str(lead.get("name", "")) else \
                   (profile.get("target_roles", ["Professional"])[0] if profile.get("target_roles") else "Professional")

    # Build Subject
    subject = template["subject"].format(
        role=role_context,
        client_name=client_name
    )
    
    # Build Body
    # Order: Greeting -> Pitch -> Resume/Contact (to be appended by the sender)
    greeting = template["greeting"].format(recipient_name=recipient_name)
    
    # Pitch formatting: The templates currently don't use {role} in the pitch,
    # but they do use {company}, {target_roles}, and {recipient_name}.
    pitch = template["pitch"].format(
        company=company_name,
        target_roles=target_roles,
        recipient_name=recipient_name,
        role=role_context
    )
    
    # The "canonical" block mentioned in the README:
    # "a short positioning pitch, the canonical chronological resume, then Joseph's LinkedIn and phone contact block."

    # We prepare the body as a structured object so the sender can inject the actual resume file/text.
    
    body = f"{greeting}\n\n{pitch}\n\n[CANONICAL_RESUME_BLOCK]\n\n[CONTACT_BLOCK]"
    
    return {
        "subject": subject,
        "body": body,
        "recipient_email": lead.get("email"),
        "track": track
    }

def prepare_outreach_batch(leads: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    """Personalize messages for a batch of routed leads."""
    profile = load_profile()
    return [personalize_message(lead, profile) for lead in leads]
