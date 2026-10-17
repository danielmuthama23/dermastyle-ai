import pytest

from app.agent.budget import build_bundles
from app.agent.preferences import parse_goal
from app.agent.recommender import Evidence, recommend
from app.agent.workflow import InvalidTransition, Session, Stage
from app.catalog.ingredients import Verdict, fragrance_check
from app.catalog.models import Category
from app.catalog.repository import Catalog
from app.media.validation import ImageKind, ImageRejected, validate_image
from app.youcam.skin import SkinConcern, SkinReport

from .conftest import jpeg, png

CATALOG = Catalog.load("data/catalog.json")


def skin(**scores) -> SkinReport:
    return SkinReport(concerns=[SkinConcern(key=k, label=k, ui_score=v) for k, v in scores.items()])


def test_goal_parser_extracts_structured_profile():
    p = parse_goal("Skincare and an elegant outfit for a wedding, under $150, fragrance-free please. Keep it simple.")
    assert p.occasion == "wedding" and p.budget == 150.0
    assert p.fragrance_free and p.simple_routine and p.want_outfit
    assert "elegant" in p.style_tags
    assert Category.serum not in p.want_categories and Category.cleanser in p.want_categories


def test_fragrance_unknown_is_not_free():
    assert fragrance_check(None)[0] is Verdict.unknown
    assert fragrance_check([])[0] is Verdict.unknown
    assert fragrance_check(["Water", "Parfum"])[0] is Verdict.contains
    assert fragrance_check(["Water", "Linalool"])[0] is Verdict.contains
    assert fragrance_check(["Water", "Glycerin"])[0] is Verdict.free


def test_fragrance_free_excludes_contains_and_unknown():
    prefs = parse_goal("fragrance-free skincare routine")
    ranked = recommend(CATALOG, prefs, None)
    cleansers = {r.product.id: r for r in ranked[Category.cleanser]}
    assert cleansers["cl-001"].eligible
    assert not cleansers["cl-002"].eligible  # Parfum
    assert not cleansers["cl-003"].eligible  # no ingredient list
    assert any(w.evidence is Evidence.unknown for w in cleansers["cl-003"].warnings)
    assert ranked[Category.cleanser][0].eligible  # eligible sorted first


def test_scores_use_measured_concerns_and_tag_them():
    prefs = parse_goal("moisturizer")
    ranked = recommend(CATALOG, prefs, skin(moisture=40, oiliness=90, redness=85))
    top = ranked[Category.moisturizer][0]
    assert top.product.id == "mo-001"
    assert any(r.evidence is Evidence.measured and "40/100" in r.text for r in top.reasons)


def test_no_analysis_is_stated_not_faked():
    ranked = recommend(CATALOG, parse_goal("serum"), None)
    assert all(r.score == 0 for r in ranked[Category.serum])
    assert ranked[Category.serum][0].reasons[0].evidence is Evidence.inferred


def test_budget_bundles_fit_and_totals_are_exact():
    prefs = parse_goal("simple skincare routine under $60")
    ranked = recommend(CATALOG, prefs, skin(moisture=40, oiliness=50))
    bundles = build_bundles(ranked, None, prefs.budget)
    assert bundles and bundles[0].within_budget
    assert bundles[0].total == round(sum(r.product.price for r in bundles[0].items), 2)
    assert bundles[0].total <= 60


def test_over_budget_reports_overage_and_offers_skincare_only():
    prefs = parse_goal("simple skincare routine")
    ranked = recommend(CATALOG, prefs, skin(moisture=40))
    garment = CATALOG.garment("gm-002")  # $84
    bundles = build_bundles(ranked, garment, 80.0)
    assert any("over budget" in b.label for b in bundles)
    assert any(b.garment is None and b.within_budget for b in bundles)


def test_no_eligible_products_returns_empty():
    prefs = parse_goal("fragrance-free serum")
    ranked = recommend(CATALOG, prefs, None)
    for r in ranked[Category.serum]:
        r.eligible = False
    assert build_bundles(ranked, None, 100) == []


def test_workflow_rejects_illegal_transition():
    s = Session()
    with pytest.raises(InvalidTransition):
        s.go(Stage.skin_done)
    s.go(Stage.skin_running)
    s.go(Stage.skin_done)


def test_wipe_resets_everything_derived_from_photos():
    s = Session()
    s.skin = skin(moisture=50)
    s.consent_face = True
    s.wipe_images_and_results()
    assert s.skin is None and not s.consent_face and s.stage is Stage.intake


def test_image_validation_rules():
    assert validate_image(jpeg(600, 800), ImageKind.face).content_type == "image/jpeg"
    assert validate_image(png(600, 800), ImageKind.body).content_type == "image/png"
    with pytest.raises(ImageRejected) as e:
        validate_image(jpeg(300, 400), ImageKind.face)
    assert e.value.code == "too_small"
    with pytest.raises(ImageRejected) as e:
        validate_image(jpeg(900, 600), ImageKind.body)
    assert e.value.code == "wrong_orientation"
    with pytest.raises(ImageRejected) as e:
        validate_image(b"not an image", ImageKind.face)
    assert e.value.code == "invalid_image"
    with pytest.raises(ImageRejected):
        validate_image(b"", ImageKind.face)
