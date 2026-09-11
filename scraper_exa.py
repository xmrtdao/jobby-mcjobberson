import os
#!/usr/bin/env python3
"""
Party Favor Photo - Lead Generator using Exa AI Search
Exa.ai is an AI-powered search engine perfect for finding business leads
API: https://exa.ai/
"""

import requests
import json
from datetime import datetime

# Exa API (sign up at exa.ai for free API key)
EXA_API_KEY = "YOUR_EXA_API_KEY"  # Get free key at https://exa.ai/

# Supabase config
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")  # Set via environment variable
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")  # Set via environment variable - project offline

class ExaLeadGenerator:
    def __init__(self):
        self.leads = []
        self.exa_url = "https://api.exa.ai/search"
        self.headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "x-api-key": EXA_API_KEY
        }
    
    def search_wedding_planners(self, location, num_results=20):
        """Search Exa for wedding planners in a location"""
        print(f"🔍 Exa Search: wedding planners in {location}...")
        
        query = f"wedding planner {location} contact email phone"
        
        payload = {
            "query": query,
            "numResults": num_results,
            "type": "keyword",
            "contents": {
                "text": True,
                "emails": True,
                "links": True
            }
        }
        
        try:
            response = requests.post(self.exa_url, json=payload, headers=self.headers, timeout=30)
            
            if response.status_code != 200:
                print(f"   ⚠️  API Error: {response.status_code}")
                print(f"   {response.text[:200]}")
                return 0
            
            data = response.json()
            results = data.get('results', [])
            
            print(f"   Found {len(results)} results")
            
            for result in results:
                # Extract emails from result
                emails = result.get('emails', [])
                
                # Also search text for emails
                import re
                email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
                text_emails = re.findall(email_pattern, result.get('text', ''))
                emails.extend(text_emails)
                emails = list(set(emails))[:3]
                
                if emails:
                    for email in emails:
                        if not any(x in email.lower() for x in ['gmail', 'yahoo', 'hotmail']):
                            self.leads.append({
                                'source': 'exa_search',
                                'name': result.get('title', 'Unknown')[:100],
                                'email': email,
                                'url': result.get('url', ''),
                                'category': 'wedding_planner',
                                'location': location,
                                'scraped_at': datetime.now().isoformat()
                            })
                            print(f"   ✅ {result.get('title', 'Unknown')[:50]}: {email}")
                            break
                else:
                    # Still save the lead without email
                    self.leads.append({
                        'source': 'exa_search',
                        'name': result.get('title', 'Unknown')[:100],
                        'email': None,
                        'url': result.get('url', ''),
                        'category': 'wedding_planner',
                        'location': location,
                        'scraped_at': datetime.now().isoformat()
                    })
                    print(f"   ✅ {result.get('title', 'Unknown')[:50]}: (no email)")
            
            return len(results)
        
        except Exception as e:
            print(f"   ❌ Error: {e}")
            return 0
    
    def search_ai_developers(self, topic="autonomous AI agent", num_results=30):
        """Search Exa for AI agent developers"""
        print(f"🔍 Exa Search: {topic}...")
        
        query = f"{topic} github contact email"
        
        payload = {
            "query": query,
            "numResults": num_results,
            "type": "keyword",
            "contents": {
                "text": True,
                "emails": True,
                "links": True
            }
        }
        
        try:
            response = requests.post(self.exa_url, json=payload, headers=self.headers, timeout=30)
            
            if response.status_code != 200:
                print(f"   ⚠️  API Error: {response.status_code}")
                return 0
            
            data = response.json()
            results = data.get('results', [])
            
            print(f"   Found {len(results)} results")
            
            for result in results:
                emails = result.get('emails', [])
                
                if emails and 'github' in result.get('url', '').lower():
                    self.leads.append({
                        'source': 'exa_search',
                        'name': result.get('title', 'Unknown')[:100],
                        'email': emails[0],
                        'url': result.get('url', ''),
                        'category': 'ai_developer',
                        'scraped_at': datetime.now().isoformat()
                    })
                    print(f"   ✅ {result.get('title', 'Unknown')[:50]}: {emails[0]}")
            
            return len(results)
        
        except Exception as e:
            print(f"   ❌ Error: {e}")
            return 0
    
    def save_leads(self):
        """Save leads to JSON"""
        filename = f"pfp_exa_leads_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        with open(filename, 'w') as f:
            json.dump(self.leads, f, indent=2)
        
        print(f"\n💾 Saved {len(self.leads)} leads to {filename}")
        
        if self.leads:
            with_email = len([l for l in self.leads if l.get('email')])
            print(f"   With emails: {with_email}/{len(self.leads)} ({with_email/len(self.leads)*100:.1f}%)")
        
        return filename
    
    def save_to_supabase(self):
        """Upload to Supabase"""
        print("\n📤 Uploading to Supabase...")
        
        saved = 0
        for lead in self.leads:
            if not lead.get('email'):
                continue
            try:
                resp = requests.post(
                    f"{SUPABASE_URL}/rest/v1/leads",
                    headers={
                        'apikey': SUPABASE_KEY,
                        'Authorization': f'Bearer {SUPABASE_KEY}',
                        'Content-Type': 'application/json',
                        'Prefer': 'return=minimal'
                    },
                    json=lead,
                    timeout=10
                )
                if resp.status_code in [201, 204]:
                    saved += 1
            except:
                pass
        
        print(f"   {saved} leads uploaded")

def main():
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║     Party Favor Photo - Exa AI Lead Generator                ║")
    print("║     Requires: Free Exa.ai API key                            ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()
    
    # Check if API key is set
    if EXA_API_KEY == "YOUR_EXA_API_KEY":
        print("⚠️  EXA API KEY NOT SET!")
        print()
        print("To get your free API key:")
        print("  1. Go to https://exa.ai/")
        print("  2. Sign up for free account")
        print("  3. Get API key from dashboard")
        print("  4. Edit this file and replace YOUR_EXA_API_KEY")
        print()
        print("Alternative: Use the manual lead collection methods")
        return
    
    gen = ExaLeadGenerator()
    
    # Target markets for Party Favor Photo
    locations = [
        "Northern Virginia",
        "Arlington VA",
        "Alexandria VA",
        "Fairfax VA",
        "Reston VA",
        "Ashburn VA",
        "Dallas TX",
        "Fort Worth TX",
        "Plano TX",
        "Frisco TX",
    ]
    
    print("📍 Searching for wedding planners...")
    print()
    
    for location in locations:
        gen.search_wedding_planners(location, num_results=15)
        print()
    
    # Save results
    gen.save_leads()
    gen.save_to_supabase()
    
    print()
    print("═══════════════════════════════════════════════════════════")
    print("  NEXT STEPS")
    print("═══════════════════════════════════════════════════════════")
    print("  1. Review leads in JSON file")
    print("  2. Upload to Supabase (automatic)")
    print("  3. Create outreach campaign in Resend")
    print("  4. Send partnership emails (15% commission)")
    print()

if __name__ == "__main__":
    main()
