"""Executed by the Unreal Editor Python runtime in the isolated test project."""
import json
import sys
from pathlib import Path
import unreal

root = Path(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir())).resolve()
sys.path.insert(0, str(root / 'Plugins/GameWorkbench/Content/Python'))
import gameworkbench_bridge as bridge

result = {'engine': unreal.SystemLibrary.get_engine_version(), 'checks': {}}
try:
    texture = unreal.AssetImportTask()
    texture.filename = str(root / 'test.png')
    texture.destination_path = '/Game/WorkbenchTest'
    texture.automated, texture.save, texture.replace_existing = True, True, True
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([texture])
    texture_path = texture.imported_object_paths[0] if texture.imported_object_paths else '/Game/WorkbenchTest/test.test'
    assert unreal.EditorAssetLibrary.does_asset_exist(texture_path)
    result['checks']['texture_inspect'] = bridge.handle({'op': 'inspect', 'path': texture_path})
    result['checks']['texture_preview'] = bridge.handle({'op': 'preview', 'path': texture_path})
    parent = unreal.EditorAssetLibrary.load_asset('/Game/WorkbenchTest/TestParent')
    if not parent:
        parent = unreal.AssetToolsHelpers.get_asset_tools().create_asset('TestParent', '/Game/WorkbenchTest', unreal.Material, unreal.MaterialFactoryNew())
        expression = unreal.MaterialEditingLibrary.create_material_expression(parent, unreal.MaterialExpressionVectorParameter)
        expression.set_editor_property('parameter_name', 'Tint')
        expression.set_editor_property('default_value', unreal.LinearColor(1, 1, 1, 1))
        unreal.MaterialEditingLibrary.connect_material_property(expression, '', unreal.MaterialProperty.MP_BASE_COLOR)
        unreal.MaterialEditingLibrary.recompile_material(parent)
        unreal.EditorAssetLibrary.save_loaded_asset(parent)
    instance = unreal.EditorAssetLibrary.load_asset('/Game/WorkbenchTest/TestInstance') or unreal.AssetToolsHelpers.get_asset_tools().create_asset('TestInstance', '/Game/WorkbenchTest', unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
    unreal.MaterialEditingLibrary.set_material_instance_parent(instance, parent)
    unreal.EditorAssetLibrary.save_loaded_asset(instance)
    path = instance.get_path_name()
    changed = bridge.handle({'op': 'set_material_color', 'path': path, 'name': 'Tint', 'color': [0.2, 0.4, 0.6, 1]})
    result['checks']['material_edit'] = changed
    actual = unreal.MaterialEditingLibrary.get_material_instance_vector_parameter_value(instance, 'Tint')
    assert abs(actual.r - 0.2) < 0.001
    result['checks']['restore'] = bridge.handle({'op': 'set_material_color', 'path': path, 'name': 'Tint', 'color': changed['previous_color']})
    result['checks']['asset_list'] = len(bridge.handle({'op': 'list_assets'})['assets'])
    result['passed'] = True
except Exception as error:
    import traceback
    result['passed'] = False
    result['error'] = str(error)
    result['traceback'] = traceback.format_exc()
(root / 'verification.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
unreal.log('WORKBENCH_VERIFICATION ' + json.dumps(result))
