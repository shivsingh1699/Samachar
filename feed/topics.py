"""Samachar: tag each pin with the topics it is about.

Why headlines only: GDELT's theme tags come from the WHOLE web page (menus, sidebars, "related stories"), so one
article can carry dozens of unrelated themes. Two live checks showed it: a theme-only rule filed travel guides under
conflict, and even when a topic's codes had to appear 4+ times, about 4 in 5 of the tags that came from themes alone were
wrong (a school report card as "disasters", a hockey story as "politics"). So themes are OFF (USE_THEMES = False) and
only the headline decides. The theme code is kept so it can be tried again later on real data.

Standard library only. English headlines only; other languages usually end up with no tag, never a wrong one.
"""
from __future__ import annotations

import re

USE_THEMES = False   # off: measured to be wrong about 4 times in 5 on live data (see the note above)
THEME_MIN = 4        # only used when USE_THEMES is True

# Single main topic, first match wins. "india" is a cross-cutting tag and is never the main one.
PRIMARY_ORDER = ["festivals", "conflict", "disasters", "protests", "health", "economy", "policy",
                 "politics", "science_tech", "lifestyle"]
TAG_ORDER = PRIMARY_ORDER + ["india"]


def _rx(*words: str) -> re.Pattern:
    """Case-insensitive, whole-word match. (?-i:AI) inside a word keeps that part case-sensitive."""
    return re.compile(r"\b(?:" + "|".join(words) + r")\b", re.IGNORECASE)


HEADLINE = {
    "festivals": _rx("diwali", "deepavali", "dussehra", "dasara", "navratri", "navaratri", "durga puja", "ganesh chaturthi",
                     "ganeshotsav", "raksha bandhan", "rakhi", "janmashtami", "maha shivaratri", "shivratri", "makar sankranti",
                     "sankranti", "pongal", "onam", "ugadi", "gudi padwa", "chhath", "karva chauth", "karwa chauth", "ram navami",
                     "hanuman jayanti", "kumbh", "rath yatra", "akshaya tritiya", "vasant panchami", "basant panchami", "lohri",
                     "dhanteras", "bhai dooj", "holi", "hindu festival", "puja", "navami", "diwali sales?"),
    "conflict": _rx("wars?", "warfare", "air ?strikes?", "missiles?", "drones? strikes?", "troops?", "military", "army", "soldiers?",
                    "cease-?fire", "hostages?", "invasion", "invade[sd]?", "bombing", "bombed", "shelling", "front ?lines?",
                    "rebels?", "militants?", "terror\\w*", "nato", "hamas", "hezbollah", "houthis?", "taliban", "gaza", "pentagon",
                    "ukrain\\w+", "crimea", "drone attacks?", "dirty bomb", "navy", "air force", "warships?", "aircraft carriers?", "nuclear weapons?", "insurgents?", "genocide"),
    "disasters": _rx("earthquakes?", "quakes?", "tsunamis?", "floods?", "flooding", "flooded", "hurricanes?", "typhoons?", "cyclones?",
                     "tornad(?:o|oes)", "wildfires?", "bushfires?", "landslides?", "avalanches?", "droughts?", "heat ?waves?",
                     "storms?", "blizzards?", "volcano(?:es)?", "eruption", "plane crash", "train derailment", "building collapse",
                     "shipwreck", "capsized", "death toll", "evacuat\\w+", "sandbags?", "el ni.o", "severe weather", "heavy rain", "snowfall", "rainfall", "monsoon"),
    "protests": _rx("protests?", "protesters?", "protesting", "demonstrations?", "demonstrators?", "riots?", "unrest", "walkouts?",
                    "strike action", "general strike", "on strike", "(?:workers|teachers|doctors|nurses|union|nationwide|rail) strikes?",
                    "march(?:es)? against"),
    "health": _rx("health", "healthcare", "hospitals?", "diseases?", "virus", "outbreaks?", "measles", "covid", "flu", "cancer",
                  "vaccines?", "vaccinations?", "vaccinated", "pandemic", "epidemic", "medicines?", "medical", "pharma\\w*", "fda",
                  "clinics?", "patients?", "surgery", "diabetes", "obesity", "cholera", "dengue", "malaria", "tuberculosis",
                  "mental health", "public health", "drug approval"),
    "economy": _rx("stocks?", "shares (?:fall|rise|jump|slump|surge|drop|tumble|slide)", "share price", "sensex", "nifty", "dow", "nasdaq", "s&p 500", "wall street", "inflation", "interest rates?",
                   "rate (?:hike|cut)s?", "central bank", "gdp", "economy", "economic", "economists?", "recession", "tariffs?",
                   "trade (?:deal|war|talks|surplus|deficit)", "oil prices?", "crude", "gas prices", "fuel prices", "petrol",
                   "diesel", "dollar", "rupee", "yen", "yuan", "currency", "bond yields?", "debt", "deficit", "budget",
                   "unemployment", "layoffs?", "jobs report", "earnings", "profits?", "revenues?", "ipo", "mergers?",
                   "acquisitions?", "acquires", "bitcoin", "crypto\\w*", "mortgages?", "home values", "house prices",
                   "property tax", "real estate", "investors?", "(?:stock|bond|oil|housing|labou?r|job|financial|crypto) markets?", "exports?", "imports?"),
    "policy": _rx("laws?", "legislation", "regulations?", "regulators?", "regulatory", "reforms?", "policy", "policies",
                  "new rules?", "bans?", "banned", "visas?", "immigration", "mandates?", "subsid(?:y|ies)", "crackdown",
                  "ruling", "court rules?", "supreme court", "amendments?", "legislat\\w+", "tax (?:cuts?|hikes?|rules?)"),
    "politics": _rx("elections?", "voters?", "voting", "parliament\\w*", "congress", "senate", "lawmakers?", "prime minister",
                    "president\\w*", "minister\\w*", "ministry", "(?-i:PM)", "government", "opposition", "coalition", "referendum", "governor", "mayor",
                    "summit", "diplomat\\w*", "sanctions?", "treaty", "white house", "kremlin", "trump", "putin", "modi",
                    "xi jinping", "takaichi", "starmer", "macron", "zelensky", "lok sabha", "bjp", "democrats?", "republicans?"),
    "science_tech": _rx("(?-i:AI)", "artificial intelligence", "chatbots?", "openai", "nvidia", "tech", "technology", "software",
                        "cyber\\w*", "hackers?", "hacked", "data cent(?:er|re)s?", "semiconductors?", "(?:computer|ai|memory) chips?", "chipmakers?", "robots?", "robotics",
                        "quantum", "satellites?", "nasa", "spacex", "rockets?", "startups?", "smartphones?", "iphone", "android",
                        "algorithms?", "5g", "scientists?", "researchers?", "autonomous", "self-driving", "electric vehicles?"),
    "lifestyle": _rx("travel (?:guide|tips|destinations?|deals?)", "tourism", "vacation", "holiday (?:gift|travel|guide|season|shopping)s?", "gift guides?", "recipes?",
                     "cooking", "food", "restaurants?", "cafes?", "wine", "fashion", "outfits?", "dress(?:es)?", "beauty", "skincare",
                     "wellness", "fitness", "yoga", "diet", "lifestyle", "home decor", "gardening", "parenting", "wedding", "hotels?",
                     "resorts?", "black friday", "things to do", "cool finds", "bestselling"),
    "india": _rx("india", "indians?", "new delhi", "delhi", "mumbai", "bengaluru", "bangalore", "chennai", "kolkata", "hyderabad", "modi",
                 "rupee", "rbi", "sensex", "nifty", "bjp", "lok sabha", "rajya sabha", "kashmir", "pakistan", "line of control"),
}

# Whole theme CODES (matched at the start of a code, never inside text) and how they map to topics.
THEME_PREFIX = {
    "conflict": ("ARMEDCONFLICT", "TERROR", "MILITARY", "WB_2433_CONFLICT", "SECURITY_SERVICES"),
    "disasters": ("NATURAL_DISASTER", "MANMADE_DISASTER"),
    "protests": ("PROTEST", "UNREST"),
    "health": ("HEALTH_", "MEDICAL", "WB_621_HEALTH", "TAX_DISEASE", "EPIDEMIC", "VACCIN"),
    "economy": ("ECON_", "WB_1104_MACROECONOMIC", "FUELPRICES", "CENTRAL_BANK"),
    "science_tech": ("CYBER_ATTACK", "WB_133_INFORMATION_AND_COMMUNICATION", "SCIENCE", "TECHNOLOGY"),
    "politics": ("ELECTION", "GENERAL_GOVERNMENT", "DIPLOMACY", "SANCTION"),
}

_SITE_SEPARATORS = (" | ", " - ", " – ", " — ")


def theme_codes(v2themes: str, v1themes: str) -> list[str]:
    """V2 entries look like CODE,charoffset;CODE,charoffset; V1 entries are bare codes."""
    if v2themes:
        return [e.split(",", 1)[0] for e in v2themes.split(";") if e]
    return [e for e in (v1themes or "").split(";") if e]


def theme_counts(codes: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for c in codes:
        for topic, prefixes in THEME_PREFIX.items():
            if c.startswith(prefixes):
                out[topic] = out.get(topic, 0) + 1
    return out


def tags_for(title: str, v2themes: str = "", v1themes: str = "", cc: str = "") -> list[str]:
    """Every topic the story is about, in TAG_ORDER. Headline words always count; themes need THEME_MIN hits."""
    found = {t for t, rx in HEADLINE.items() if rx.search(title or "")}
    if USE_THEMES:
        for t, n in theme_counts(theme_codes(v2themes, v1themes)).items():
            if n >= THEME_MIN:
                found.add(t)
    if cc == "IN":
        found.add("india")
    return [t for t in TAG_ORDER if t in found]


def main_topic(tags: list[str]) -> str:
    for t in PRIMARY_ORDER:
        if t in tags:
            return t
    return "other"


def strip_site_suffix(title: str, site: str) -> str:
    """'Story | The Rural' -> 'Story' when the tail is just the outlet name. A ' | ' tail is always an outlet; for dashes
    the tail must also look like the site's name, so real subtitles are left alone."""
    core = re.sub(r"[^a-z0-9]", "", (site or "").lower().removeprefix("www.").split(".")[0])
    for sep in _SITE_SEPARATORS:
        head, found, tail = title.rpartition(sep)
        if not found or not head.strip() or len(tail) > 45:
            continue
        tail_l = re.sub(r"[^a-z0-9]", "", tail.lower())
        if sep == " | " or (len(core) > 3 and tail_l and (tail_l in core or core in tail_l)):
            return head.strip()
    return title


def dedupe_key(title: str, lat: float, lon: float) -> tuple:
    """The same wire story appears on many local sites: one pin per headline. Very short headlines also need the place."""
    k = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()[:80]
    return (k,) if len(k) >= 25 else (k, lat, lon)
