from pathlib import Path

from scripts.check_release import problems


def test_service_url_is_public_but_personal_paths_and_skill_keys_are_rejected():
    url = b'https://www.suno.cn/home/#/mcp/authorize?code=fixture&source=skill'
    assert 'personal absolute path' not in problems(Path('fixture.txt'), url)
    local = ('/' + 'home/' + 'example/design.txt').encode()
    assert 'personal absolute path' in problems(Path('fixture.txt'), local)
    key = ('sks_' + 'a' * 64).encode()
    assert 'possible secret' in problems(Path('fixture.txt'), key)


def test_windows_runtime_and_generated_app_files_stay_out_of_source():
    assert 'private or generated path' in problems(Path('.runtime/python/LICENSE.txt'), b'fixture')
    for name in ('packaged.json', 'SHA256SUMS.json', 'ZAOWU.exe', 'ZAOWU-Picker.exe', 'Questweft.exe', 'Questweft-Picker.exe'):
        assert 'generated Windows distribution file' in problems(Path(name), b'fixture')
    assert not problems(Path('scripts/windows/Launcher.cs'), b'fixture source')
