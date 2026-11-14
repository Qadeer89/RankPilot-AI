import uuid

from app.models.page import Page
from app.models.page_image import ImageStatus, PageImage
from app.seo_rules.rules import images


def _image(**overrides) -> PageImage:
    defaults = dict(
        image_src="https://example.com/photo.jpg",
        alt_text="A dog running on the beach",
        has_alt=True,
        is_decorative=False,
        has_dimensions=True,
        image_status=ImageStatus.ok,
    )
    defaults.update(overrides)
    return PageImage(**defaults)


def test_check_flags_missing_src():
    page_id = uuid.uuid4()
    candidates = images.check(page_id, [_image(image_src=None, image_status=ImageStatus.missing_src)])
    codes = {c.rule_code for c in candidates}
    assert "IMAGE_MISSING_SRC" in codes


def test_check_flags_missing_alt_but_not_decorative_images():
    page_id = uuid.uuid4()
    missing_alt = _image(has_alt=False, alt_text=None)
    decorative = _image(has_alt=True, alt_text=None, is_decorative=True)
    candidates = images.check(page_id, [missing_alt, decorative])
    codes = {c.rule_code for c in candidates}
    assert "IMAGE_MISSING_ALT" in codes
    finding = next(c for c in candidates if c.rule_code == "IMAGE_MISSING_ALT")
    assert finding.evidence["count"] == 1


def test_check_flags_filename_like_alt_text_as_unhelpful():
    page_id = uuid.uuid4()
    for bad_alt in ("IMG_1234", "dsc00421", "photo.jpg", "screenshot2024.png"):
        candidates = images.check(page_id, [_image(alt_text=bad_alt)])
        codes = {c.rule_code for c in candidates}
        assert "IMAGE_UNHELPFUL_ALT_TEXT" in codes, f"expected unhelpful alt for {bad_alt!r}"


def test_check_does_not_flag_descriptive_alt_text_as_unhelpful():
    page_id = uuid.uuid4()
    candidates = images.check(page_id, [_image(alt_text="A golden retriever running on the beach at sunset")])
    codes = {c.rule_code for c in candidates}
    assert "IMAGE_UNHELPFUL_ALT_TEXT" not in codes


def test_check_never_flags_decorative_images_as_unhelpful_even_with_odd_alt():
    page_id = uuid.uuid4()
    candidates = images.check(
        page_id, [_image(alt_text=None, has_alt=True, is_decorative=True)]
    )
    codes = {c.rule_code for c in candidates}
    assert "IMAGE_UNHELPFUL_ALT_TEXT" not in codes
    assert "IMAGE_MISSING_ALT" not in codes


def test_check_flags_missing_dimensions():
    page_id = uuid.uuid4()
    candidates = images.check(page_id, [_image(has_dimensions=False)])
    codes = {c.rule_code for c in candidates}
    assert "IMAGE_MISSING_DIMENSIONS" in codes


def test_check_returns_nothing_for_a_fully_clean_image():
    page_id = uuid.uuid4()
    candidates = images.check(page_id, [_image()])
    assert candidates == []


def test_check_broken_images_cross_references_known_crawled_pages_only():
    page_id = uuid.uuid4()
    broken_page = Page(
        id=uuid.uuid4(),
        website_id=uuid.uuid4(),
        canonical_url="https://example.com/dead",
        normalized_url="https://example.com/dead",
        last_status_code=404,
    )
    pages_by_normalized_url = {"https://example.com/dead": broken_page}
    page_images_by_page_id = {
        page_id: [_image(image_src="https://example.com/dead")],
    }
    candidates = images.check_broken_images(
        pages_by_normalized_url, page_images_by_page_id, lambda u: u
    )
    assert len(candidates) == 1
    assert candidates[0].rule_code == "IMAGE_BROKEN"


def test_check_broken_images_does_not_flag_unverifiable_external_media():
    page_id = uuid.uuid4()
    page_images_by_page_id = {
        page_id: [_image(image_src="https://cdn.example.com/photo.jpg")],
    }
    candidates = images.check_broken_images({}, page_images_by_page_id, lambda u: u)
    assert candidates == []
