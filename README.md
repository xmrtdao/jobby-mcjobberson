# Lead Scraper - Automated Lead Generation

## Overview

Automated scraping system to find emails for:
1. Wedding planners and venues (for Party Favor Photo)
2. AI agent developers (for Agent Clearinghouse)
3. B2B partners (for XMRT Consulting + Fleet SaaS)

---

## 🎯 Target Sources

### Wedding Planners/Venues

| Source | Type | Estimated Leads |
|--------|------|-----------------|
| TheKnot.com | Directory | 10,000+ |
| WeddingWire.com | Directory | 15,000+ |
| Google Maps | Local search | 50,000+ |
| Yelp | Reviews + business | 20,000+ |
| Facebook Groups | Community | 5,000+ |
| Instagram | Hashtag search | 30,000+ |
| LinkedIn | Professional | 10,000+ |

### AI Agent Developers

| Source | Type | Estimated Leads |
|--------|------|-----------------|
| GitHub | Code repos | 5,000+ |
| Hugging Face | Models + demos | 3,000+ |
| Reddit (r/LocalLLaMA) | Community | 2,000+ |
| Discord (AI servers) | Community | 5,000+ |
| Twitter/X | Social | 10,000+ |
| LinkedIn | Professional | 5,000+ |
| Product Hunt | Launches | 1,000+ |

### B2B Partners

| Source | Type | Estimated Leads |
|--------|------|-----------------|
| Crunchbase | Startups | 10,000+ |
| AngelList | Startups | 5,000+ |
| LinkedIn | Companies | 50,000+ |
| Industry directories | Niche | 5,000+ |

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Lead Scraper System                       │
│                                                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │   Source 1  │  │   Source 2  │  │   Source 3  │         │
│  │  (TheKnot)  │  │ (WeddingWire)│  │ (Google)    │         │
│  └─────────────┘  └─────────────┘  └─────────────┘         │
│         │                │                │                 │
│         └────────────────┼────────────────┘                 │
│                          ▼                                  │
│              ┌─────────────────────────┐                   │
│              │   Scraper Engine        │                   │
│              │   - Playwright/Selenium │                   │
│              │   - BeautifulSoup       │                   │
│              │   - Rate limiting       │                   │
│              │   - Proxy rotation      │                   │
│              └─────────────────────────┘                   │
│                          │                                  │
│                          ▼                                  │
│              ┌─────────────────────────┐                   │
│              │   Data Processing       │                   │
│              │   - Email extraction    │                   │
│              │   - Deduplication       │                   │
│              │   - Validation          │                   │
│              │   - Enrichment          │                   │
│              └─────────────────────────┘                   │
│                          │                                  │
│                          ▼                                  │
│              ┌─────────────────────────┐                   │
│              │   Supabase Storage      │                   │
│              │   - leads table         │                   │
│              │   - campaigns table     │                   │
│              │   - outreach table      │                   │
│              └─────────────────────────┘                   │
└─────────────────────────────────────────────────────────────┘
```

---

## 🔧 Technical Implementation

### Scraper Engine

```python
# scraper.py
import asyncio
from playwright.async_api import async_playwright
from supabase import create_client
import re

class LeadScraper:
    def __init__(self):
        self.supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        self.email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    
    async def scrape_theknot(self, location="Washington DC"):
        """Scrape TheKnot.com for wedding planners"""
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            
            # Search for planners in location
            await page.goto(f"https://www.theknot.com/marketplace/wedding-planners-{location.replace(' ', '-')}")
            
            # Extract listings
            listings = await page.query_selector_all('.vendor-listing')
            
            leads = []
            for listing in listings[:50]:  # Limit per run
                try:
                    name = await listing.query_selector('.vendor-name')
                    name = await name.inner_text() if name else ""
                    
                    link = await listing.query_selector('a')
                    link = await link.get_attribute('href') if link else ""
                    
                    # Visit individual page for email
                    if link:
                        await page.goto(f"https://www.theknot.com{link}")
                        content = await page.content()
                        emails = re.findall(self.email_pattern, content)
                        
                        if emails:
                            leads.append({
                                'source': 'theknot',
                                'name': name,
                                'email': emails[0],
                                'url': link,
                                'category': 'wedding_planner',
                                'location': location
                            })
                except Exception as e:
                    print(f"Error: {e}")
                    continue
            
            await browser.close()
            return leads
    
    async def scrape_github(self, query="ai agent"):
        """Scrape GitHub for AI agent developers"""
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            
            await page.goto(f"https://github.com/search?q={query}&type=repositories")
            
            repos = await page.query_selector_all('.repo-list-item')
            
            leads = []
            for repo in repos[:50]:
                try:
                    name = await repo.query_selector('.v-card-names')
                    name = await name.inner_text() if name else ""
                    
                    link = await repo.query_selector('a')
                    link = await link.get_attribute('href') if link else ""
                    
                    # Visit repo for contact info
                    if link:
                        await page.goto(f"https://github.com{link}")
                        content = await page.content()
                        emails = re.findall(self.email_pattern, content)
                        
                        # Also check README
                        readme_link = await page.query_selector('a[href*="README"]')
                        if readme_link:
                            await page.goto(f"https://github.com{link}/blob/main/README.md")
                            content = await page.content()
                            emails.extend(re.findall(self.email_pattern, content))
                        
                        if emails:
                            leads.append({
                                'source': 'github',
                                'name': name,
                                'email': emails[0],
                                'url': link,
                                'category': 'ai_developer'
                            })
                except Exception as e:
                    print(f"Error: {e}")
                    continue
            
            await browser.close()
            return leads
    
    def save_leads(self, leads):
        """Save leads to Supabase"""
        for lead in leads:
            # Check for duplicates
            existing = self.supabase.table('leads').select('id').eq('email', lead['email']).execute()
            
            if not existing.data:
                self.supabase.table('leads').insert(lead).execute()
                print(f"Saved: {lead['email']}")
            else:
                print(f"Duplicate: {lead['email']}")
```

### Database Schema

```sql
-- Leads table
CREATE TABLE leads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    email TEXT UNIQUE NOT NULL,
    name TEXT,
    company TEXT,
    category TEXT NOT NULL, -- wedding_planner, ai_developer, b2b_partner
    source TEXT NOT NULL, -- theknot, github, linkedin, etc.
    url TEXT,
    location TEXT,
    phone TEXT,
    social_links JSONB,
    status TEXT DEFAULT 'new', -- new, contacted, responded, converted
    campaign_id UUID REFERENCES campaigns(id),
    metadata JSONB DEFAULT '{}'
);

-- Campaigns table
CREATE TABLE campaigns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    target_count INT,
    sent_count INT DEFAULT 0,
    response_count INT DEFAULT 0,
    conversion_count INT DEFAULT 0,
    status TEXT DEFAULT 'active'
);

-- Outreach table
CREATE TABLE outreach (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    lead_id UUID REFERENCES leads(id),
    campaign_id UUID REFERENCES campaigns(id),
    email_subject TEXT,
    email_body TEXT,
    sent_at TIMESTAMPTZ,
    opened_at TIMESTAMPTZ,
    clicked_at TIMESTAMPTZ,
    responded_at TIMESTAMPTZ,
    status TEXT DEFAULT 'pending' -- pending, sent, opened, clicked, responded
);

CREATE INDEX idx_leads_email ON leads(email);
CREATE INDEX idx_leads_category ON leads(category);
CREATE INDEX idx_leads_status ON leads(status);
```

---

## 📋 Scraping Targets

### Priority 1: Wedding Planners (DC Area)

```python
targets_wedding = [
    {
        'source': 'theknot.com',
        'url': 'https://www.theknot.com/marketplace/wedding-planners-washington-dc',
        'estimated': 200
    },
    {
        'source': 'weddingwire.com',
        'url': 'https://www.weddingwire.com/wedding-planners/washington-dc',
        'estimated': 250
    },
    {
        'source': 'google_maps',
        'query': 'wedding planner Washington DC',
        'estimated': 500
    },
    {
        'source': 'yelp.com',
        'url': 'https://www.yelp.com/search?find_desc=wedding+planner&find_loc=Washington%2C+DC',
        'estimated': 300
    }
]
```

### Priority 2: AI Agent Developers

```python
targets_ai = [
    {
        'source': 'github.com',
        'query': 'ai agent autonomous',
        'estimated': 1000
    },
    {
        'source': 'huggingface.co',
        'url': 'https://huggingface.co/models?search=agent',
        'estimated': 500
    },
    {
        'source': 'reddit.com',
        'subreddits': ['r/LocalLLaMA', 'r/artificial', 'r/MachineLearning'],
        'estimated': 2000
    },
    {
        'source': 'twitter.com',
        'hashtags': ['#AIAgent', '#AutonomousAgent', '#LLM'],
        'estimated': 3000
    }
]
```

---

## 🚀 Deployment

### Option 1: Local (Termux)
```bash
cd /data/data/com.termux/files/home/lead-scraper
pip install playwright beautifulsoup4 supabase
playwright install
python scraper.py
```

### Option 2: Supabase Edge Function (Scheduled)
```typescript
// edge function: lead-scraper
import { serve } from "https://deno.land/std@0.168.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

serve(async (req) => {
  // Run scraper on schedule (daily/weekly)
  // Save results to Supabase
  // Trigger email campaigns for new leads
});
```

### Option 3: Cloud (VPS)
- Deploy on DigitalOcean/Vultr ($5-10/mo)
- Run with cron job
- Proxy rotation for large-scale scraping

---

## ⚖️ Legal Considerations

### Best Practices
- ✅ Respect robots.txt
- ✅ Rate limit requests (1 req/2-3 sec)
- ✅ Use official APIs when available
- ✅ Include User-Agent header
- ✅ Honor opt-out requests

### Avoid
- ❌ Scraping behind login walls
- ❌ Ignoring rate limits
- ❌ Selling personal data (GDPR)
- ❌ Spam emails (CAN-SPAM Act)

### Compliance
- CAN-SPAM Act: Include unsubscribe in emails
- GDPR: EU residents require consent
- CCPA: California residents can opt-out

---

## 📊 Lead Enrichment

Once emails are collected, enrich with:

```python
enrichment_sources = [
    'clearbit.com',  # Company data
    'hunter.io',     # Email verification
    'neverbounce.com',  # Email validation
    'linkedin.com',  # Professional info
    'crunchbase.com'  # Funding + company size
]
```

---

## 📈 Success Metrics

| Metric | Target | Current |
|--------|--------|---------|
| Leads scraped/day | 100 | TBD |
| Email validity rate | 80%+ | TBD |
| Outreach open rate | 40%+ | TBD |
| Response rate | 10%+ | TBD |
| Conversion rate | 3%+ | TBD |

---

## 🦑 XMRT DAO Integration

This scraper feeds leads into:
1. **Party Favor Photo** - Wedding planner partnerships
2. **Agent Clearinghouse** - Agent developer recruitment
3. **XMRT Consulting** - B2B client acquisition
4. **Fleet SaaS** - Enterprise customer pipeline

---

## 📞 Contact

**Maintained by:** Hermes (XMRT DAO)  
**GitHub:** https://github.com/xmrtdao/lead-scraper

---

## 📸 Party Favor Photo Integration

### Target Markets

**Priority 1: Northern Virginia**
- Arlington, Alexandria, Fairfax
- Reston, Ashburn, Leesburg
- Manassas, Woodbridge
- **Goal:** 100 wedding planners/venues

**Priority 2: Dallas, TX**
- Dallas, Fort Worth, Plano
- Irving, Frisco, McKinney
- Allen, Richardson
- **Goal:** 100 wedding planners/venues

### Partnership Offer

- **15% commission** on all referrals
- Average: $100-150 per booking
- Potential: $1,000-1,500/planner/year passive income

### Outreach Campaign

See: `PFP_PARTNERSHIP_OUTREACH.md` for:
- Email templates
- Follow-up sequence
- Tracking spreadsheet
- Success metrics

### Running the Scraper

```bash
cd /data/data/com.termux/files/home/lead-scraper

# Install dependencies
pip install playwright beautifulsoup4 supabase
playwright install

# Run scraper (targets NoVA + Dallas)
python scraper_wedding.py

# Output: wedding_planners_YYYYMMDD_HHMMSS.json
# Upload to Supabase leads table
```

### Expected Results

| Market | Planners | Email Rate | Partnerships | Revenue |
|--------|----------|------------|--------------|---------|
| NoVA | 100 | 40% | 5 | $7,500/yr |
| Dallas | 100 | 40% | 5 | $7,500/yr |
| **Total** | **200** | **40%** | **10** | **$15,000/yr** |

---
