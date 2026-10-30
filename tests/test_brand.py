import asyncio

from backend import path_picker, store


def test_new_picker_is_preferred_and_legacy_packaged_layout_remains_supported(monkeypatch, tmp_path):
    monkeypatch.setattr(store, 'ROOT', tmp_path)
    old = tmp_path / 'ZAOWU-Picker.exe'
    new = tmp_path / 'Questweft-Picker.exe'
    old.write_bytes(b'legacy fixture')
    assert asyncio.run(path_picker.executable()) == old
    new.write_bytes(b'new fixture')
    assert asyncio.run(path_picker.executable()) == new
    assert old.read_bytes() == b'legacy fixture'
