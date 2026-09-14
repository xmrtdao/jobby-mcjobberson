"""Jobby McJobberson Orchestrator.

This is the central command engine that ties together ingestion, cleaning, 
routing, personalization, and delivery, with durable state persistence.
"""

import logging
from typing import Any, Dict, List
from profile import load_profile
import lead_utils
import routing
import personalizer
import delivery_adapter
import ats_adapter
import state_manager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("jobby.orchestrator")

class JobbyOrchestrator:
    def __init__(self, dry_run: bool = True):
        self.dry_run = dry_run
        self.profile = load_profile()

    def run_pipeline(self, raw_leads: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Executes the full Jobby pipeline with durable state:
        Ingest -> Normalize -> Deduplicate -> Persist/Route -> Personalize -> Dispatch
        """
        logger.info(f"Starting pipeline for {len(raw_leads)} raw leads...")

        # 1. Clean & Normalize
        pipeline_result = lead_utils.prepare_recipients(raw_leads)
        eligible = pipeline_result["eligible"]
        suppressed = pipeline_result["suppressed"]
        discarded = pipeline_result["discarded"]
        
        logger.info(f"Pipeline: {len(eligible)} eligible, {len(suppressed)} suppressed, {len(discarded)} discarded.")

        # 2. Persist & Route
        processed_leads = []
        for lead in eligible:
            # Map normalized lead fields to the DB columns
            db_lead = {
                "company_name": lead.get("company"),
                "contact_name": lead.get("name"),
                "contact_email": lead.get("email"),
                "contact_phone": lead.get("phone"),
                "source": lead.get("source"),
                "source_url": lead.get("url"),
                "track": routing.determine_track(f"{lead.get('name', '')} {lead.get('company', '')}"),
                "state": "QUALIFIED"
            }
            
            # Persist to local-sb via state_manager
            saved_lead = state_manager.create_lead(db_lead)
            
            if saved_lead and "id" in saved_lead:
                # Attach the DB ID back to the lead for tracking
                lead["id"] = saved_lead["id"]
                processed_leads.append(lead)
            else:
                logger.warning(f"Could not persist lead {lead.get('email')}")

        # 3. Final Routing & Scoring
        routed_leads = routing.process_batch(processed_leads)
        logger.info(f"Routed {len(routed_leads)} leads into their respective tracks.")

        # 4. Segment by Delivery Method
        email_leads = []
        ats_leads = []

        for lead in routed_leads:
            track = lead.get("track", "track3")
            if track == "track4":
                ats_leads.append(lead)
            else:
                email_leads.append(lead)

        # 5. Process Email Tracks (1, 2, 3)
        email_results = []
        if email_leads:
            logger.info(f"Personalizing {len(email_leads)} email outreach messages...")
            personalized = personalizer.prepare_outreach_batch(email_leads)
            
            logger.info(f"Dispatching email batch via delivery_adapter...")
            delivery_log = delivery_adapter.deliver_batch(personalized, dry_run=self.dry_run)
            
            for msg, res in zip(personalized, delivery_log):
                # Use the lead's ID (cross-referenced by email)
                lead_id = next((l["id"] for l in processed_leads if l["email"] == msg["recipient_email"]), None)
                if lead_id:
                    state_manager.transition_state(lead_id, "PITCHED")
                    
                    # Agentic CRM: Set a default follow-up reason for the next cycle
                    followup_reason = f"Initial pitch sent for {msg['recipient_company']}. Following up on interest in {self.profile.get('specialization', 'AI Systems')}."
                    state_manager.set_followup_reason(lead_id, followup_reason)
            
            email_results = delivery_log

        # 6. Process ATS Track (4)
        ats_results = []
        if ats_leads:
            logger.info(f"Preparing {len(ats_leads)} ATS application payloads...")
            ats_payloads = ats_adapter.process_ats_batch(ats_leads)
            
            for payload in ats_payloads:
                if "error" not in payload:
                    # Transition state to APPLIED
                    lead_id = payload["context"].get("lead_id")
                    if lead_id:
                        state_manager.transition_state(lead_id, "APPLIED")
                    
                    if self.dry_run:
                        logger.info(f"[DRY RUN] ATS Dispatch: {payload.get('target_url')}")
                    else:
                        logger.info(f"ATS Dispatch: {payload.get('target_url')}")
                ats_results.append(payload)

        return {
            "stats": {
                "total_input": len(raw_leads),
                "eligible": len(eligible),
                "suppressed": len(suppressed),
                "discarded": len(discarded),
                "emails_sent": len(email_results),
                "ats_submitted": len(ats_results)
            },
            "delivery_log": {
                "emails": email_results,
                "ats": ats_results
            }
        }

if __name__ == "__main__":
    import json
    test_leads = [
        {"name": "Senior Software Engineer", "company": "TechCorp", "email": "hr@techcorp.com", "url": "https://techcorp.com/careers", "source": "LinkedIn"},
        {"name": "Consultancy Lead", "company": "StrategyX", "email": "partner@strategyx.com", "url": "https://strategyx.com", "source": "Direct"},
        {"name": "ATS Job Post", "company": "GovAgency", "email": "apply@gov.gov", "url": "https://gov.gov/apply/123", "source": "JobBoard", "track": "track4"},
    ]
    orchestrator = JobbyOrchestrator(dry_run=True)
    print(json.dumps(orchestrator.run_pipeline(test_leads), indent=2))
