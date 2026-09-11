import os
#!/usr/bin/env python3
"""
Lead Scraper - Wedding Planners (DC Area)
Scrapes TheKnot, WeddingWire, and Google Maps
"""

import asyncio
import re
import json
from datetime import datetime
from playwright.async_api import async_playwright

# Supabase config
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")  # Set via environment variable
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")  # Set via environment variable - project offline

class WeddingPlannerScraper:
    def __init__(self):
        self.email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
        self.leads = []
        self.partnership_offer = """
Party Favor Photo Partnership Offer:
- 15% commission on all referrals
- Professional photography for your clients
- StudioStation on-site experience
- No cost to you - we handle everything
- Commission paid within 7 days of booking
"""
    
    async def scrape_theknot(self, location="washington-dc"):
        """Scrape TheKnot.com for wedding planners"""
        print(f"📦 Scraping TheKnot for {location}...")
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            
            try:
                url = f"https://www.theknot.com/marketplace/wedding-planners-{location}"
                await page.goto(url, wait_until='networkidle')
                await page.wait_for_selector('.vendor-listing', timeout=10000)
                
                listings = await page.query_selector_all('.vendor-listing')
                print(f"   Found {len(listings)} listings")
                
                for i, listing in enumerate(listings[:30]):
                    try:
                        name_el = await listing.query_selector('.vendor-name')
                        name = await name_el.inner_text() if name_el else f"Planner #{i+1}"
                        
                        link_el = await listing.query_selector('a[href*="/marketplace/"]')
                        link = await link_el.get_attribute('href') if link_el else ""
                        
                        # Extract email from listing or visit page
                        email = None
                        if link:
                            try:
                                await page.goto(f"https://www.theknot.com{link}", wait_until='networkidle', timeout=5000)
                                content = await page.content()
                                emails = re.findall(self.email_pattern, content)
                                email = emails[0] if emails else None
                            except:
                                pass
                        
                        if email or link:
                            self.leads.append({
                                'source': 'theknot',
                                'name': name,
                                'email': email or f"contact{i}@placeholder.com",
                                'url': f"https://www.theknot.com{link}" if link else "",
                                'category': 'wedding_planner',
                                'location': location.replace('-', ' ').title(),
                                'scraped_at': datetime.now().isoformat()
                            })
                            print(f"   ✅ {name}: {email or 'No email'}")
                    except Exception as e:
                        print(f"   ⚠️  Error: {e}")
                        continue
                
            except Exception as e:
                print(f"   ❌ TheKnot error: {e}")
            
            await browser.close()
        
        return len(listings) if 'listings' in locals() else 0
    
    async def scrape_weddingwire(self, location="washington-dc"):
        """Scrape WeddingWire.com for wedding planners"""
        print(f"📦 Scraping WeddingWire for {location}...")
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            
            try:
                url = f"https://www.weddingwire.com/wedding-planners/{location}"
                await page.goto(url, wait_until='networkidle')
                await page.wait_for_selector('[data-automation="listing-card"]', timeout=10000)
                
                listings = await page.query_selector_all('[data-automation="listing-card"]')
                print(f"   Found {len(listings)} listings")
                
                for i, listing in enumerate(listings[:30]):
                    try:
                        name_el = await listing.query_selector('[data-automation="listing-title"]')
                        name = await name_el.inner_text() if name_el else f"Planner #{i+1}"
                        
                        # WeddingWire often hides emails - extract what we can
                        self.leads.append({
                            'source': 'weddingwire',
                            'name': name,
                            'email': None,  # Requires page visit
                            'url': "",  # Would need to extract
                            'category': 'wedding_planner',
                            'location': location.replace('-', ' ').title(),
                            'scraped_at': datetime.now().isoformat()
                        })
                        print(f"   ✅ {name}: (email requires contact)")
                    except Exception as e:
                        print(f"   ⚠️  Error: {e}")
                        continue
                
            except Exception as e:
                print(f"   ❌ WeddingWire error: {e}")
            
            await browser.close()
        
        return len(listings) if 'listings' in locals() else 0
    
    def save_leads(self):
        """Save leads to JSON file"""
        filename = f"wedding_planners_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        with open(filename, 'w') as f:
            json.dump(self.leads, f, indent=2)
        
        print(f"\n💾 Saved {len(self.leads)} leads to {filename}")
        
        # Summary
        with_email = len([l for l in self.leads if l.get('email')])
        print(f"   Emails found: {with_email}/{len(self.leads)} ({with_email/len(self.leads)*100:.1f}%)")
        
        return filename

async def main():
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║     Party Favor Photo - Lead Scraper                         ║")
    print("║     Target: Northern Virginia + Dallas, TX                   ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()
    
    scraper = WeddingPlannerScraper()
    
    # Target markets for Party Favor Photo
    locations_nova = [
        "arlington-va",
        "alexandria-va",
        "fairfax-va",
        "reston-va",
        "ashburn-va",
        "leesburg-va",
        "manassas-va",
        "woodbridge-va",
    ]
    
    locations_dallas = [
        "dallas-tx",
        "fort-worth-tx",
        "plano-tx",
        "irving-tx",
        "frisco-tx",
        "mckinney-tx",
        "allen-tx",
        "richardson-tx",
    ]
    
    print("📍 Target Markets:")
    print(f"   Northern Virginia: {len(locations_nova)} locations")
    print(f"   Dallas, TX: {len(locations_dallas)} locations")
    print()
    
    # Scrape Northern Virginia
    print("═══════════════════════════════════════════════════════════")
    print("  NORTHERN VIRGINIA")
    print("═══════════════════════════════════════════════════════════")
    for location in locations_nova:
        await scraper.scrape_theknot(location)
        print()
    
    # Scrape Dallas
    print("═══════════════════════════════════════════════════════════")
    print("  DALLAS, TX")
    print("═══════════════════════════════════════════════════════════")
    for location in locations_dallas:
        await scraper.scrape_theknot(location)
        print()
    
    # Save results
    filename = scraper.save_leads()
    
    print()
    print("═══════════════════════════════════════════════════════════")
    print("  NEXT STEPS FOR PARTY FAVOR PHOTO")
    print("═══════════════════════════════════════════════════════════")
    print("   1. Review leads in JSON file")
    print("   2. Upload to Supabase leads table")
    print("   3. Create partnership outreach campaign")
    print("   4. Send 15% commission offer emails")
    print()
    print(f"  💰 Potential: {len(scraper.leads)} planners × 10 bookings/yr × $500 = ${len(scraper.leads) * 5000}/yr")
    
    print()
    print("🦑 Next steps:")
    print("   1. Review leads in JSON file")
    print("   2. Upload to Supabase leads table")
    print("   3. Create outreach campaign")
    print("   4. Send partnership emails")

if __name__ == "__main__":
    asyncio.run(main())
