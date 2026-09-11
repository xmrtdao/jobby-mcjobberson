# Party Favor Photo - Partnership Outreach

## Target Markets

### Northern Virginia (NoVA)
- Arlington, Alexandria, Fairfax
- Reston, Ashburn, Leesburg
- Manassas, Woodbridge
- **Total:** ~500 wedding planners/venues

### Dallas, Texas (DFW)
- Dallas, Fort Worth, Plano
- Irving, Frisco, McKinney
- Allen, Richardson
- **Total:** ~600 wedding planners/venues

---

## Partnership Offer

### 15% Commission Structure

| Package | Price | Commission |
|---------|-------|------------|
| StudioStation Basic | $498 | $75 |
| StudioStation Premium | $698 | $105 |
| Full Event Coverage | $1,500+ | $225+ |

**Average per referral:** $100-150  
**Potential per planner:** 10 referrals/yr = $1,000-1,500/yr passive income

---

## Outreach Email Template

```
Subject: Partnership Opportunity - Party Favor Photo 📸

Hi [Name],

I'm reaching out from Party Favor Photo - we specialize in professional 
photography for [school events/weddings/special occasions] in the 
[Northern Virginia/Dallas] area.

I noticed you're a respected wedding planner in the community, and I'd 
love to explore a partnership opportunity.

🤝 PARTNERSHIP OFFER:
- 15% commission on all client referrals
- Professional photography your clients will love
- StudioStation on-site experience (huge hit at events!)
- No cost to you - we handle everything
- Commission paid within 7 days of booking

Our average planner partner earns $1,000-1,500/year in passive 
commission from referrals they're already making.

Would you be open to a quick 15-minute call next week to discuss?

Best regards,
[Your Name]
Party Favor Photo
bookings@partyfavorphoto.com
partyfavorphoto.com

P.S. - We're currently partnering with [X] planners in [area] and 
have capacity for 2-3 more exclusive partners!
```

---

## Follow-Up Sequence

### Email 1: Initial Outreach (Day 0)
- Partnership offer introduction
- 15% commission highlighted
- Call to action: 15-min call

### Email 2: Value Add (Day 3)
- Share testimonial from existing planner partner
- Link to portfolio
- Reiterate commission structure

### Email 3: Social Proof (Day 7)
- "Currently working with [X] planners in your area"
- Scarcity: "Capacity for 2-3 more exclusive partners"
- Limited-time offer: 20% commission for first 3 bookings

### Email 4: Phone Call (Day 10)
- Personal call: "Just wanted to follow up..."
- Answer questions
- Close partnership

### Email 5: Breakup (Day 14)
- "Should I close your file?"
- Leave door open for future
- Send holiday greeting instead

---

## Tracking Spreadsheet

| Planner | Company | Email | Phone | Location | Sent | Responded | Meeting | Partner | Referrals | Revenue |
|---------|---------|-------|-------|----------|------|-----------|---------|---------|-----------|---------|
| Melissa | ANGP | melissa@... | 555-... | DC | 5/26 | ✅ | ✅ | ⏳ | 2 | $996 |
| ... | ... | ... | ... | ... | ... | ... | ... | ... | ... | ... |

---

## Goals

| Metric | Target | Timeline |
|--------|--------|----------|
| Planners contacted | 200 | 30 days |
| Response rate | 20% | 40 planners |
| Meetings booked | 10% | 20 planners |
| Partnerships closed | 5% | 10 planners |
| Referrals/partner/yr | 10 | 100 referrals |
| Revenue from partnerships | $50K/yr | Year 1 |

---

## Venues to Target

### Northern Virginia
1. The Birchmere (Alexandria)
2. Tower Club (Arlington)
3. Salona Village (McLean)
4. The Manor (Clifton)
5. Frying Pan Farm Park (Herndon)

### Dallas, TX
1. The Adolphus (Downtown Dallas)
2. The Joule (Downtown Dallas)
3. Dallas Arboretum
4. The Statler (Downtown Dallas)
5. Union Dallas (Deep Ellum)

---

## School Partnerships (DC Area)

Already in progress with ANGP (Lewis HS):
- 15% commission to school/PTA
- 10 DC schools targeted
- Potential: 3-5 bookings/school × $500 = $1,500-2,500/school

**Target Schools:**
1. Lewis HS (✅ In progress - Melissa)
2. Washington-Liberty HS (Arlington)
3. Thomas Jefferson HS (Fairfax)
4. Langley HS (McLean)
5. Westfield HS (Chantilly)
6. Stone Bridge HS (Ashburn)
7. Riverside HS (Woodbridge)
8. Osbourn HS (Manassas)
9. Freedom HS (South Riding)
10. Briar Woods HS (Leesburg)

---

## CRM Integration

Upload scraped leads to Supabase:

```sql
INSERT INTO leads (email, name, company, category, source, location, status)
VALUES 
  ('planner@example.com', 'Jane Doe', 'Elegant Events', 'wedding_planner', 'theknot', 'Arlington, VA', 'new'),
  ...
```

Then create outreach campaign:

```sql
INSERT INTO campaigns (name, category, target_count)
VALUES ('PFP NoVA Partnerships Q2 2026', 'wedding_planner', 100);
```

---

## Success Metrics

| Week | Contacts | Responses | Meetings | Partners | Referrals | Revenue |
|------|----------|-----------|----------|----------|-----------|---------|
| 1 | 50 | 10 | 5 | 2 | 0 | $0 |
| 2 | 100 | 20 | 10 | 4 | 1 | $500 |
| 3 | 150 | 30 | 15 | 6 | 3 | $1,500 |
| 4 | 200 | 40 | 20 | 10 | 5 | $2,500 |

---

## 🦑 Automation

Once scraper runs:
1. Leads saved to JSON
2. Upload to Supabase
3. Trigger email sequence via Resend
4. Track responses in dashboard
5. Notify when planner responds

**Edge function:** `pfp-partnership-outreach`
- Runs daily
- Sends next email in sequence
- Updates lead status
- Notifies of responses
