import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "feed"))
import pins as P  # noqa: E402
import topics as T  # noqa: E402
from test_feed import STAMP, gkg_row  # noqa: E402


def test_headline_words_decide_the_topic():
    assert T.tags_for("Oil prices fall as US crude stocks rise") == ["economy"]
    assert "conflict" in T.tags_for("Is Trump giving Iran a way out of the war?")
    assert T.tags_for("The Gen Z holiday travel guide to Christmas markets across Europe") == ["lifestyle"]
    assert T.tags_for("Hanukkah gift guide") == ["lifestyle"]
    assert T.tags_for("Measles vaccination rates: where does your state rank?") == ["health"]
    assert T.tags_for("Red Sox fans can't overlook Abreu's statement season") == []


def test_words_inside_other_words_do_not_count():
    assert T.tags_for("Indiana bill signed by governor") == ["politics"]          # not India
    assert T.tags_for("Ali Larter shares behind-the-scenes photos") == []         # 'shares' is not a market move
    assert T.tags_for("Bill Gates talks about his new book") == []                # 'Bill' is a name
    assert T.tags_for("Christmas markets open in Cologne") == []                  # 'markets' alone is not economy
    assert T.tags_for("Skills fair held at school") == []                         # 'SKILLS' once matched the 'KILL' theme code


def test_festivals_and_india_tags():
    t = T.tags_for("Diwali sales lift Sensex as rupee firms")
    assert t[0] == "festivals" and "economy" in t and t[-1] == "india"
    assert T.main_topic(t) == "festivals"
    assert "india" not in T.PRIMARY_ORDER and T.tags_for("Rain delays match", cc="IN") == ["india"]
    assert T.main_topic(["india"]) == "other"


def test_ai_is_case_sensitive_but_other_words_are_not():
    assert T.tags_for("AI chips in demand") == ["science_tech"]
    assert T.tags_for("Said the mail was late") == []


def test_themes_alone_need_several_whole_code_hits():
    three = "PROTEST,10;PROTEST,50;PROTEST,90;"
    four = three + "PROTEST,120;"
    assert T.tags_for("Local update", three) == []
    assert T.tags_for("Local update", four) == ["protests"]
    # whole codes only: 'TAX_FNCACT_SKILLS' must not count as the conflict code KILL, 'AI_' text must not count as tech
    assert T.tags_for("Local update", "TAX_FNCACT_SKILLS,1;" * 6) == []
    # disease codes belong to health, not disasters
    assert T.tags_for("Local update", "TAX_DISEASE_CHOLERA,1;" * 5) == ["health"]
    # old-style themes (no offsets) still work
    assert T.tags_for("Local update", "", "ARMEDCONFLICT;TERROR;MILITARY;ARMEDCONFLICT;") == ["conflict"]


def test_site_suffixes_are_removed_only_when_they_are_the_outlet():
    assert T.strip_site_suffix("Urine recycled to beat fertiliser crisis | The Rural", "therural.com.au") == "Urine recycled to beat fertiliser crisis"
    assert T.strip_site_suffix("Rewind week of Nov. 13 – Lansing City Pulse", "lansingcitypulse.com") == "Rewind week of Nov. 13"
    assert T.strip_site_suffix("Trump heads to China - betting on diplomacy", "fox21online.com") == "Trump heads to China - betting on diplomacy"
    assert T.strip_site_suffix("Just a headline", "x.com") == "Just a headline"


def test_same_story_from_many_sites_is_one_pin():
    rows = [gkg_row(1, title="UTS scientists recycle human urine to beat fertiliser crisis | The Rural", source="therural.com.au"),
            gkg_row(2, title="UTS scientists recycle human urine to beat fertiliser crisis | Milton Ulladulla Times", source="ulladullatimes.com.au"),
            gkg_row(3, title="UTS scientists recycle human urine to beat fertiliser crisis", source="irrigator.com.au")]
    _, pins = P.parse_gkg("\n".join(rows), STAMP)
    assert len(pins) == 1 and pins[0]["t"] == "UTS scientists recycle human urine to beat fertiliser crisis"


def test_pins_carry_topic_and_topics():
    _, pins = P.parse_gkg(gkg_row(1, themes="", title="Diwali sales lift Sensex"), STAMP)
    p = pins[0]
    assert p["topic"] == "festivals" and p["topics"] == ["festivals", "economy", "india"]
    _, pins = P.parse_gkg(gkg_row(2, themes="", title="Mavericks try to regroup against Warriors", v2loc="4#Dallas#US#USTX#1#32.8#-96.8#x#1"), STAMP)
    assert pins[0]["topic"] == "other" and pins[0]["topics"] == []


def test_a_quiet_topic_is_not_crowded_out_by_the_cap():
    loud = [gkg_row(i, themes="", title=f"Mavericks game number {i} recap and notes",
                    v2loc=f"4#P{i}#US#USTX#1#{20 + i / 1000:.3f}#-96.8#x#1") for i in range(P.PINS_PER_FILE + 60)]
    quiet = [gkg_row(1000 + i, themes="", title=f"Diwali celebrations in town number {i}",
                     v2loc=f"1#Country{i}#XX#XX##{40 + i}#10#x#1") for i in range(5)]   # country-level place = ranked last
    stats, pins = P.parse_gkg("\n".join(loud + quiet), STAMP)
    assert len(pins) == P.PINS_PER_FILE
    assert sum("festivals" in p["topics"] for p in pins) == 5
    assert stats["topics"]["festivals"] == 5


def test_quota_does_not_exceed_the_cap_when_everything_is_one_topic():
    rows = [gkg_row(i, themes="", title=f"Oil prices story number {i} on markets",
                    v2loc=f"4#P{i}#US#USTX#1#{20 + i / 1000:.3f}#-96.8#x#1") for i in range(P.PINS_PER_FILE + 100)]
    stats, pins = P.parse_gkg("\n".join(rows), STAMP)
    assert len(pins) == P.PINS_PER_FILE and stats["pins"] == P.PINS_PER_FILE
