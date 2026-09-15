"""Personalization layer for Jobby McJobberson.

This module replaces static templates with LLM-driven generation to create 
bespoke outreach messages and tailored resumes based on lead research 
and client dossiers.
"""

import logging
import requests
from typing import Any, Dict, Optional, List
from profile import load_profile

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("jobby.personalizer")

# Configuration for the LLM Brain
DEFAULT_MODEL = "gemma4:31b"
OLLAMA_API_URL = "https://relay.mobilemonero.com/tools/llm-generate"

def generate_ai_content(prompt: str, model: str = DEFAULT_MODEL) -> str:
    """
    Calls the LLM to generate high-conversion professional content.
    """
    try:
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.7,
                "top_p": 0.9
            }
        }
        
        resp = requests.post(OLLAMA_API_URL, json=payload, timeout=30)
        if resp.status_code == 200:
            return resp.json().get("response", "").strip()
        else:
            logger.error(f"LLM Generation failed: {resp.status_code} {resp.text}")
            return " [ERROR: AI generation failed] "
    except Exception as e:
        logger.error(f"Network error during AI generation: {e}")
        return " [ERROR: AI connection failed] "

def personalize_message(lead: Dict[str, Any], profile: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """
    Generate a personalized outreach message using the LLM.
    """
    if profile is None:
        profile = load_profile()
    
    research = lead.get("research", {})
    dossier = lead.get("dossier", [])
    
    # Use a raw string for the prompt to avoid escape issues
    prompt = f"""
You are a world-class talent agent (think Hollywood or Pro Sports). 
Your goal is to represent your client, {profile.get('full_name')}, in the best possible light.

CLIENT PROFILE:
- Target Roles: {', '.join(profile.get('target_roles', []))}
- Core Expertise: {profile.get('specialization', 'AI Systems and Blockchain')}
- Key Businesses/Projects: {profile.get('businesses', [])}

LEAD DATA:
- Company: {lead.get('company')}
- Contact: {lead.get('name')}
- Role/Opportunity: {lead.get('name')}
- Research Hooks: {research}
- Dossier Evidence: {dossier}

TASK:
Write a high-conversion, professional, yet bold outreach email. 
1. Use a 'hook' from the research to show we've done our homework.
2. Position the client as a high-value asset who solves specific problems for {lead.get('company')}.
3. Avoid generic 'AI-isms'. Sound human, confident, and strategic.
4. Keep it concise.

OUTPUT FORMAT:
Subject: [Compelling Subject Line]
Body: [The email body]
"""

    ai_output = generate_ai_content(prompt)
    
    subject = "Professional Inquiry"
    body = ai_output
    
    if "Subject:" in ai_output:
        parts = ai_output.split("Body:", 1)
        subject_part = parts[0].replace("Subject:", "").strip()
        body = parts[1].strip() if len(parts) > 1 else ai_output
        subject = subject_part

    return {
        "subject": subject,
        "body": f"{body}\n\n[CANONICAL_RESUME_BLOCK]\n\n[CONTACT_BLOCK]",
        "recipient_email": lead.get("email"),
        "track": lead.get("track", "track3")
    }

def prepare_outreach_batch(leads: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Personalize messages for a batch of routed leads."""
    profile = load_profile()
    return [personalize_message(lead, profile) for lead in leads]
