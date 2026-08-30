from app.configuration import merge_preset


def test_merge_preset_deep_merge():
    current = {"control": {"device": "cpu", "online": False}, "env": {"gamma": 1}}
    preset = {"control": {"device": "cuda", "batch_size": 512}}
    merged = merge_preset(current, preset)
    assert merged["control"]["device"] == "cuda"
    assert merged["control"]["online"] is False
    assert merged["control"]["batch_size"] == 512
    assert merged["env"]["gamma"] == 1
