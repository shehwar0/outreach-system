from __future__ import annotations

from typing import Any, Dict


NICHE_CATEGORIES = {
    "auto_repair": ["auto repair", "mechanic", "car repair", "garage", "auto shop", "auto service"],
    "plumber": ["plumber", "plumbing", "pipe", "drain"],
    "electrician": ["electrician", "electrical", "wiring"],
    "dentist": ["dentist", "dental", "clinic", "orthodontist"],
    "hvac": ["ac repair", "hvac", "air conditioning", "heating", "cooling"],
    "salon": ["salon", "barber", "beauty", "hair", "spa", "nails"],
    "car_detailing": ["car detailing", "car wash", "auto detailing", "vehicle cleaning"],
    "painter": ["painter", "painting", "home painter", "wall painting"],
    "pest_control": ["pest control", "exterminator", "pest", "fumigation"],
    "mobile_repair": ["mobile repair", "phone repair", "cell repair", "screen repair"],
    "gym": ["gym", "fitness", "workout"],
    "tutor": ["tutor", "academy", "coaching", "classes", "teaching"],
    "real_estate": ["real estate", "property", "realtor", "agent"],
    "restaurant": ["restaurant", "food", "cafe", "eatery", "catering"],
}

TIER_1_NICHES = {"auto_repair", "plumber", "electrician", "dentist", "hvac"}
TIER_2_NICHES = {"salon", "car_detailing", "painter", "pest_control", "mobile_repair"}
TIER_3_NICHES = {"gym", "tutor", "real_estate", "restaurant"}


def detect_niche(business: str, category: str) -> str:
    combined = f"{business} {category}".lower().strip()
    if not combined.strip():
        return ""

    for niche_key, keywords in NICHE_CATEGORIES.items():
        for keyword in keywords:
            if keyword in combined:
                return niche_key
    return ""


def calculate_lead_score(lead: Dict[str, Any]) -> int:
    score = 0

    # +35 if no website
    website_exists = lead.get("website_exists", False)
    if isinstance(website_exists, str):
        website_exists = website_exists.lower().strip() in {"true", "1", "yes"}
    if not website_exists:
        score += 35

    # +20 for category fit (service/local business)
    niche = lead.get("niche", "") or detect_niche(
        lead.get("business", ""), lead.get("category", "")
    )
    if niche in TIER_1_NICHES:
        score += 20
    elif niche in TIER_2_NICHES:
        score += 15
    elif niche in TIER_3_NICHES:
        score += 10

    # +15 for direct contact
    name = str(lead.get("name", "")).lower().strip()
    if name and name not in {"info", "admin", "contact", "support", "office", "there", ""}:
        score += 15

    # +5 to +15 for reviews
    reviews = int(lead.get("reviews_count", 0))
    if reviews > 50:
        score += 15
    elif reviews > 10:
        score += 10
    elif reviews > 0:
        score += 5

    # +10 for city
    city = str(lead.get("city", "")).strip()
    if city:
        score += 10

    # +5 for no/weak social presence
    social = str(lead.get("social_presence", "")).strip().lower()
    if not social or social in {"none", "weak", "no", ""}:
        score += 5

    return min(score, 100)


def assign_segment(score: int) -> str:
    if score >= 75:
        return "high"
    elif score >= 50:
        return "medium"
    return "low"


def score_and_segment_lead(lead: Dict[str, Any]) -> Dict[str, Any]:
    niche = lead.get("niche", "") or detect_niche(
        lead.get("business", ""), lead.get("category", "")
    )
    score = calculate_lead_score(lead)
    segment = assign_segment(score)

    lead["niche"] = niche
    lead["lead_score"] = score
    lead["segment"] = segment
    return lead
