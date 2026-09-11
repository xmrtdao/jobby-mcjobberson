#!/usr/bin/env python3
"""
Lead Scraper - AI Agent Developers
Scrapes GitHub, Hugging Face, and Reddit
"""

import asyncio
import re
import json
from datetime import datetime
from playwright.async_api import async_playwright

class AIAgentScraper:
    def __init__(self):
        self.email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
        self.leads = []
    
    async def scrape_github(self, query="autonomous ai agent"):
        """Scrape GitHub for AI agent developers"""
        print(f"📦 Scraping GitHub for '{query}'...")
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            
            try:
                url = f"https://github.com/search?q={query.replace(' ', '+')}&type=repositories"
                await page.goto(url, wait_until='networkidle')
                await page.wait_for_selector('.repo-list-item', timeout=10000)
                
                repos = await page.query_selector_all('.repo-list-item')
                print(f"   Found {len(repos)} repositories")
                
                for i, repo in enumerate(repos[:50]):
                    try:
                        name_el = await repo.query_selector('.v-card-names')
                        name = await name_el.inner_text() if name_el else f"Repo #{i+1}"
                        
                        link_el = await repo.query_selector('a[href*="/"]')
                        link = await link_el.get_attribute('href') if link_el else ""
                        
                        # Visit repo for contact info
                        email = None
                        if link:
                            try:
                                await page.goto(f"https://github.com{link}", wait_until='networkidle', timeout=5000)
                                
                                # Check README for email
                                content = await page.content()
                                emails = re.findall(self.email_pattern, content)
                                
                                # Filter out noreply emails
                                emails = [e for e in emails if 'noreply' not in e.lower()]
                                email = emails[0] if emails else None
                                
                            except Exception as e:
                                pass
                        
                        if name and link:
                            self.leads.append({
                                'source': 'github',
                                'name': name,
                                'email': email,
                                'url': f"https://github.com{link}",
                                'category': 'ai_developer',
                                'scraped_at': datetime.now().isoformat()
                            })
                            print(f"   ✅ {name}: {email or 'No email'}")
                    
                    except Exception as e:
                        continue
                
            except Exception as e:
                print(f"   ❌ GitHub error: {e}")
            
            await browser.close()
        
        return len(repos) if 'repos' in locals() else 0
    
    async def scrape_huggingface(self):
        """Scrape Hugging Face for AI agent models"""
        print(f"📦 Scraping Hugging Face for agent models...")
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            
            try:
                url = "https://huggingface.co/models?search=agent"
                await page.goto(url, wait_until='networkidle')
                await page.wait_for_selector('[data-testid="model-card"]', timeout=10000)
                
                models = await page.query_selector_all('[data-testid="model-card"]')
                print(f"   Found {len(models)} models")
                
                for i, model in enumerate(models[:30]):
                    try:
                        name_el = await model.query_selector('a[href*="/"]')
                        name = await name_el.inner_text() if name_el else f"Model #{i+1}"
                        
                        link_el = await model.query_selector('a[href*="/"]')
                        link = await link_el.get_attribute('href') if link_el else ""
                        
                        self.leads.append({
                            'source': 'huggingface',
                            'name': name,
                            'email': None,  # HF doesn't show emails publicly
                            'url': f"https://huggingface.co{link}" if link else "",
                            'category': 'ai_developer',
                            'scraped_at': datetime.now().isoformat()
                        })
                        print(f"   ✅ {name}")
                    
                    except Exception as e:
                        continue
                
            except Exception as e:
                print(f"   ❌ HuggingFace error: {e}")
            
            await browser.close()
        
        return len(models) if 'models' in locals() else 0
    
    def save_leads(self):
        """Save leads to JSON file"""
        filename = f"ai_agents_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        with open(filename, 'w') as f:
            json.dump(self.leads, f, indent=2)
        
        print(f"\n💾 Saved {len(self.leads)} leads to {filename}")
        
        # Summary
        with_email = len([l for l in self.leads if l.get('email')])
        print(f"   Emails found: {with_email}/{len(self.leads)} ({with_email/len(self.leads)*100:.1f}%)")
        
        return filename

async def main():
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║     AI Agent Developer Lead Scraper                          ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()
    
    scraper = AIAgentScraper()
    
    # Scrape sources
    await scraper.scrape_github("autonomous ai agent")
    print()
    await scraper.scrape_huggingface()
    print()
    
    # Save results
    scraper.save_leads()
    
    print()
    print("🦑 Next steps:")
    print("   1. Review leads in JSON file")
    print("   2. Upload to Supabase leads table")
    print("   3. Create Agent Clearinghouse outreach campaign")
    print("   4. Invite developers to list their agents")

if __name__ == "__main__":
    asyncio.run(main())
