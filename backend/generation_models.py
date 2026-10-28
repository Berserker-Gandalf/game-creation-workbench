"""Project defaults are separate from immutable job specifications and account grants."""
from . import store


def selected(pid):
    from . import music, tripo
    store.project(pid)
    values = store.setting('generation_models:' + pid, {})
    return {'suno': values.get('suno', music.MODELS[0]['id']), 'tripo': values.get('tripo', tripo.MODELS[0])}


def catalog(pid):
    from . import music, tripo
    return {'selected': selected(pid), 'suno': music.MODELS,
            'tripo': [{'id': m, 'label': m} for m in tripo.MODELS], 'image_model': store.setting('image_model', ''),
            'source': {'suno': 'Suno.cn Skill 2.4 接口契约；非账户实时目录', 'tripo': 'Tripo 官方 V3 文档；非账户实时目录'}}


def validate(data):
    from . import music, tripo
    catalogues = {'suno': music.MODELS, 'tripo': [{'id': m} for m in tripo.MODELS]}
    if not isinstance(data, dict) or not data or set(data) - {'suno', 'tripo'}: raise ValueError('生成模型设置无效')
    for service, value in data.items():
        if not isinstance(value, str) or value not in [m['id'] for m in catalogues[service]]: raise ValueError('请选择已接入的生成模型')
    return data


def save(pid, data):
    validate(data)
    store.set_setting('generation_models:' + pid, {**selected(pid), **data})
    return catalog(pid)
