from audiokeys.utils import generate_sample_id


def test_generate_sample_id_unique_increment():
    existing = {"tap_1", "tap_2"}
    assert generate_sample_id("tap", existing) == "tap_3"


def test_generate_sample_id_spaces_normalised():
    existing = set()
    assert generate_sample_id("my tap", existing).startswith("my_tap_1")
