"""Opportunity routing and targeting engine for Jobby McJobberson.

This module analyzes incoming leads and routes them into the appropriate 
opportunity tracks based on job roles and target preferences.
"""

import re
from typing import Any, Dict, List, Tuple
from profile import load_profile

# Canonical track definitions
TRACKS = {
    "track1": "Contract consultancy and high-engagement personalized outreach",
    "track2": "Temporary and contract opportunities",
    "track3": "Full-time employment opportunities",
}

# Keyword mappings for automated routing
ROUTING_RULES = {
    "track1": ["consultancy", "consultant", "expert", "advisory", "fractional"],
    "track2": ["temporary", "temp", "contract", "fixed-term", "interim"],
    "track3": ["full-time", "permanent", "fte", "salaried", "direct hire"],
}

def determine_track(text: str) -> str:
    """Route a lead to a track based on keywords in the job title or description."""
    if not text:
        return "track3"  # Default to full-time if unknown
    
    text = text.lower()
    for track, keywords in ROUTING_RULES.items():
        if any(kw in text for kw in keywords):
            return track
            
    return "track3"

def calculate_match_score(lead_text: str, target_roles: List[str]) -> float:
    """Calculate a match score (0.0 to 1.0) based on target roles."""
    if not target_roles:
        return 0.5  # Neutral score if no targets defined
    
    lead_text = lead_text.lower()
    matches = 0
    for role in target_roles:
        if role.lower() in lead_text:
            matches += 1
            
    return matches / len(target_roles)

def route_opportunity(lead: Dict[str, Any]) -> Dict[str, Any]:
    """Analyze a lead and attach routing and targeting metadata."""
    profile = load_profile()
    target_roles = profile.get("target_roles", [])
    
    # Combine name, company, and source for analysis
    analysis_text = f"{lead.get('name', '')} {lead.get('company', '')} {lead.get('source', '')}"
    
    track = determine_track(analysis_text)
    score = calculate_match_score(analysis_text, target_roles)
    
    # Assign match category
    if score >= 0.5:
        category = "High Match"
    elif score >= 0.1:
        category = "Potential"
    else:
        category = "Irrelevant"
        
    return {
        **lead,
        "track": track,
        "match_score": score,
        "match_category": category
    }

def process_batch(leads: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Route and score a batch of leads."""
    return [route_opportunity(lead) for lead in leads]
