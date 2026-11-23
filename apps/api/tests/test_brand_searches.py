import uuid
from datetime import datetime, timezone

from app.keywords.brand import is_brand_navigational
from app.growth.service import generate_growth_recommendations
from app.models.growth_recommendation import GrowthRecommendation
from app.models.keyword_idea import KeywordDataClassification, KeywordIdea, KeywordIdeaSource, SearchIntent
from tests.ai_search_helpers import make_site


def test_brand_plus_contact_or_navigational_is_a_brand_search():
    n, h = "Guls Rehab", "gulsrehab.com"
    assert is_brand_navigational("contact Gul's Rehab for inquiries", "navigational", n, h)
    assert is_brand_navigational("how to contact Guls Rehab", "navigational", n, h)
    assert is_brand_navigational("gulsrehab login", "informational", n, h)
    assert is_brand_navigational("Guls Rehab address Rawalpindi", "informational", n, h)


def test_topics_that_merely_mention_the_service_are_not_brand_searches():
    n, h = "Guls Rehab", "gulsrehab.com"
    assert not is_brand_navigational("knee pain on stairs solutions", "informational", n, h)
    assert not is_brand_navigational("contact lens physiotherapy", "informational", n, h)  # "contact" alone is not enough
    assert not is_brand_navigational("best physiotherapy in rawalpindi", "commercial", n, h)
    assert not is_brand_navigational("Guls Rehab laser hair removal", "commercial", n, h)  # names the brand but is a service query
    assert not is_brand_navigational("anything", None, None, None)


def _idea(db, site, keyword, intent):
    row = KeywordIdea(website_id=site.id, keyword=keyword, search_intent=intent, source=KeywordIdeaSource.ai_generated,
                      data_classification=KeywordDataClassification.ai_generated_idea, country="PK", relevance=0.9, confidence=0.9,
                      recommended_content_type="blog_post", rationale="r", evidence_json={})
    db.add(row)
    return row


def test_brand_searches_never_become_recommendations_and_old_open_ones_are_removed(db_session):
    site = make_site(db_session, host="gulsrehab.com")
    site.display_name = "Guls Rehab"
    good = _idea(db_session, site, "knee pain on stairs solutions", SearchIntent.informational)
    brand = _idea(db_session, site, "contact Gul's Rehab for inquiries", SearchIntent.navigational)
    db_session.flush()
    # a recommendation from before this rule existed
    generate_growth_recommendations(db_session, site)
    keys = {r.dedupe_key for r in db_session.query(GrowthRecommendation).filter_by(website_id=site.id)}
    assert f"new_content:{good.id}" in keys and f"new_content:{brand.id}" not in keys


def test_an_open_recommendation_made_before_the_rule_is_removed_but_an_approved_one_stays(db_session, monkeypatch):
    from app.growth import service
    from app.models.growth_recommendation import RecommendationStatus

    site = make_site(db_session, host="gulsrehab.com")
    site.display_name = "Guls Rehab"
    open_one = _idea(db_session, site, "contact Gul's Rehab for inquiries", SearchIntent.navigational)
    approved_one = _idea(db_session, site, "gulsrehab login", SearchIntent.navigational)
    db_session.flush()
    monkeypatch.setattr(service, "is_brand_navigational", lambda *a, **k: False)  # the world before the rule
    generate_growth_recommendations(db_session, site)
    monkeypatch.undo()
    by_key = {r.dedupe_key: r for r in db_session.query(GrowthRecommendation).filter_by(website_id=site.id)}
    by_key[f"new_content:{approved_one.id}"].status = RecommendationStatus.approved
    db_session.flush()
    generate_growth_recommendations(db_session, site)
    keys = {r.dedupe_key for r in db_session.query(GrowthRecommendation).filter_by(website_id=site.id)}
    assert f"new_content:{open_one.id}" not in keys and f"new_content:{approved_one.id}" in keys
