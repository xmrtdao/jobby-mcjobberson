"""Jobby McJobberson Orchestrator.

This is the central command engine that ties together ingestion, cleaning, 
routing, personalization, and delivery.
"""

import logging
from typing import Any, Dict, List
from profile import load_profile
import lead_utils
import routing
import personalizer
import delivery_adapter
import ats_adapter

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
        Executes the full Jobby pipeline:
        Ingest -> Normalize -> Deduplicate -> Route -> Personalize -> Dispatch
        """
        logger.info(f"Starting pipeline for {len(raw_leads)} raw leads...")

        # 1. Clean & Normalize
        # lead_utils.prepare_recipients handles normalization, dedup, and suppression
        pipeline_result = lead_utils.prepare_recipients(raw_leads)
        eligible = pipeline_result["eligible"]
        suppressed = pipeline_result["suppressed"]
        discarded = pipeline_result["discarded"]
        
        logger.info(f"Pipeline: {len(eligible)} eligible, {len(suppressed)} suppressed, {len(discarded)} discarded.")

        # 2. Route & Score
        routed_leads = routing.process_batch(eligible)
        logger.info(f"Routed {len(routed_leads)} leads into their respective tracks.")

        # 3. Segment by Delivery Method
        email_leads = []
        ats_leads = []

        for lead in routed_leads:
            track = lead.get("track", "track3")
            if track == "track4":
                ats_leads.append(lead)
            else:
                email_leads.append(lead)

        # 4. Process Email Tracks (1, 2, 3)
        email_results = []
        if email_leads:
            logger.info(f"Personalizing {len(email_leads)} email outreach messages...")
            personalized = personalizer.prepare_outreach_batch(email_leads)
            
            logger.info(f"Dispatching email batch via delivery_adapter...")
            email_results = delivery_adapter.deliver_batch(personalized, dry_run=self.dry_run)

        # 5. Process ATS Track (4)
        ats_results = []
        if ats_leads:
            logger.info(f"Preparing {len(ats_leads)} ATS application payloads...")
            ats_payloads = ats_adapter.process_ats_batch(ats_leads)
            
            # In a real system, these would be sent to the page-agent API.
            # For now, we log the dispatch.
            for payload in ats_payloads:
                if self.dry_run:
                    logger.info(f"[DRY RUN] ATS Dispatch: {payload.get('target_url')} for {payload.get('context', {}).get('client')}")
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
    # Simple CLI test
    import json
    
    # Mock raw leads for a full-system test
    test_leads = [
        {
            "name": "Senior Software Engineer",
            "company": "TechCorp",
            "email": "hr@techcorp.com",
            "url": "https://techcorp.com/careers",
            "source": "LinkedIn",
            "track": "track3"
        },
        {
            "name": "Consultancy Lead",
            "company": "StrategyX",
            "email": "partner@strategyx.com",
            "url": "https://strategyx.com",
            "source": "Direct",
            "track": "track1"
        },
        {
            "name": "ATS Job Post",
            "company": "GovAgency",
            "email": "apply@gov.gov",
            "url": "https://gov.gov/apply/123",
            "source": "JobBoard",
            "track": "track4"
        },
        {
            "name": "Malformed Lead",
            "email": "bad-email",
            "source": "junk"
        }
    ]

    orchestrator = JobbyOrchestrator(dry_run=True)
    final_report = orchestrator.run_pipeline(test_leads)
    print(json.dumps(final_report, indent=2))
