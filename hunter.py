""""Autonomous Lead Hunter for Jobby McJobberson.
Proactively discovers new professional opportunities and leads 
based on the client's target roles and businesses.
"""

import logging
import requests
from typing import Any, Dict, List
from profile import load_profile

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("jobby.hunter")

class JobbyHunter:
    def __init__(self, relay_url: str = "https://relay.mobilemonero.com/tools"):
        self.relay_url = relay_url

    def discover_opportunities(self) -> List[Dict[str, Any]]:
        """
        Proactively searches the web for job postings, consultancy needs, 
        and relevant business leads based on the client profile.
        """
        profile = load_profile()
        target_roles = profile.get("target_roles", [])
        leads = []

        for role in target_roles:
            logger.info(f"Hunting for opportunities: {role}...")
            
            # Construct a high-intent search query
            # Example: "Senior AI Architect jobs LinkedIn" or "Blockchain Consultant opportunities"
            query = f""{role}" jobs OR opportunities site:linkedin.com/jobs OR site:indeed.com"
            
            try:
                # Call the relay's web_search tool
                resp = requests.post(
                    f"{self.relay_url}/web_search", 
                    json={"query": query, "limit": 10}, 
                    timeout=30
                )
                
                if resp.status_code == 200:
                    data = resp.json().get("data", {}).get("web", [])
                    for item in data:
                        leads.append({
                            "name": role, 
                            "company": item.get("title", "Unknown Company").split("-")[-1].strip(),
                            "url": item.get("url"),
                            "source": "Autonomous Hunter",
                            "description": item.get("description", ""),
                            "email": None # Hunter finds the opportunity; Orchestrator/Researcher finds the contact
                        })
                else:
                    logger.error(f"Search failed for {role}: {resp.status_code}")
            except Exception as e:
                logger.error(f"Network error hunting for {role}: {e}")

        return leads

if __name__ == "__main__":
    hunter = JobbyHunter()
    found = hunter.discover_opportunities()
    print(f"Hunter discovered {len(found)} potential opportunities.")
