from training.platform_rating import decomposed_platform_utility, tenhou_dan_utility
from training.rating import GameResult, tenhou_rate_utility
from training.rating_router import RatingObjectiveRouter


def test_tenhou_dan_4p_houou_south_6dan_last():
    result = GameResult(4, 4, 25000, 25000, round_kind="south", room="houou", rank="6dan")
    utility = tenhou_dan_utility("tenhou_dan", {}, result)
    assert utility.total == -120.0


def test_tenhou_dan_3p_houou_east_7dan():
    first = GameResult(3, 1, 35000, 35000, round_kind="east", room="houou", rank="7dan")
    last = GameResult(3, 3, 35000, 35000, round_kind="east", room="houou", rank="7dan")
    assert tenhou_dan_utility("tenhou_dan", {}, first).total == 90.0
    assert tenhou_dan_utility("tenhou_dan", {}, last).total == -90.0


def test_tenhou_rate_formula():
    cfg = {"placement_4p": [30, 10, -10, -30], "minimum_table_rating": 1500, "rating_divisor": 40}
    result = GameResult(
        4, 1, 25000, 25000, self_rating=2000, table_average_rating=2100, games_played=400
    )
    # 0.2 * (30 + (2100-2000)/40) = 6.5
    assert tenhou_rate_utility("tenhou_rate", cfg, result).total == 6.5


def test_decomposed_score_uma_room_rank():
    cfg = {
        "score_divisor": 1000,
        "uma_4p": [15, 5, -5, -15],
        "room_rules": [{"players": 4, "round": "south", "room": "jade", "placement": [110, 55, 0, 0]}],
        "rank_rules": [{"players": 4, "round": "south", "rank": "saint3", "placement": [0, 0, 0, -240]}],
    }
    result = GameResult(4, 4, 12000, 25000, round_kind="south", room="jade", rank="saint3")
    utility = decomposed_platform_utility("mahjongsoul", cfg, result)
    assert utility.total == -268.0  # -13 raw score -15 uma -240 rank penalty


def test_curriculum_becomes_target_profile():
    catalog = {
        "catalog": {"normalize_clip": 6},
        "universal": {"4p": {"tenhou_dan": 1.0}},
        "profiles": {"tenhou_dan": {"kind": "tenhou_dan", "normalization_scale": 100}},
    }
    router = RatingObjectiveRouter(
        catalog,
        players=4,
        strategy="curriculum",
        target_profile="tenhou_dan",
        specialize_start=0.7,
        seed=1,
    )
    result = GameResult(4, 1, 25000, 25000, round_kind="east", room="houou", rank="6dan")
    routed = router.evaluate(result, progress=1.0)
    assert routed.profile == "tenhou_dan"
    assert routed.specialization_probability == 1.0
    assert routed.raw.total == 60.0
