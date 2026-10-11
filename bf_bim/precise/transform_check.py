"""Check archived nested INSERTs against independently composed raw matrices."""
from ezdxf.math import Matrix44


def check_transforms(data):
    if data.get('precision_transform_check_version')==1:
        return False
    definitions={e['handle']:e for block in data['blocks'] for e in block.get('entities',[]) if e.get('handle')}
    scene={e['id']:e for e in data['scene_entities']}
    changed_ids={w.get('entity_id') for w in data['warnings'] if w['code']=='TRANSFORM_TYPE_CHANGED'}
    for entity in data['scene_entities']:
        original=definitions.get(entity.get('definition_handle'))
        entity['definition_type']=original['type'] if original is not None else entity['type']
        if original is not None and original['type']!=entity['type'] and entity['id'] not in changed_ids:
            data['warnings'].append({'code':'TRANSFORM_TYPE_CHANGED','entity_id':entity['id'],
                'definition_handle':entity.get('definition_handle'),'original_type':original['type'],
                'transformed_type':entity['type'],'message':'Native definition identity retained across geometry conversion'})
    failures=set()
    for entity in data['scene_entities']:
        parent=scene.get(entity.get('parent_insert_id'))
        original=definitions.get(entity.get('definition_handle'))
        if entity['type']!='INSERT' or parent is None or original is None or original['type']!='INSERT':
            continue
        # MINSERT cells carry their individually positioned matrix and are not
        # equivalent to the unsplit original array definition.
        if entity['id'].rsplit('/',1)[-1].startswith('cell:'):
            continue
        local=original['geometry']['block_to_layout_matrix_rows']
        parent_rows=parent['geometry']['block_to_layout_matrix_rows']
        actual=entity['geometry']['block_to_layout_matrix_rows']
        expected=Matrix44([x for row in local for x in row])*Matrix44([x for row in parent_rows for x in row])
        mismatch=any(abs(expected.get_row(i)[j]-actual[i][j])>(1e-4 if i==3 else 1e-9) for i in range(4) for j in range(4))
        if mismatch:
            failures.add(entity['id'])
            data['warnings'].append({'code':'BLOCK_TRANSFORM_LOSS','entity_id':entity['id'],
                'definition_handle':entity['definition_handle'],
                'message':'Expanded INSERT differs from original composed transform; derived geometry blocked',
                'expected_matrix_rows':[list(expected.get_row(i)) for i in range(4)],'actual_matrix_rows':actual})
    for entity in data['scene_entities']:
        if entity['id'] in failures or failures.intersection(entity.get('insert_ancestry',[])):
            entity['precision_geometry_blocked']='BLOCK_TRANSFORM_LOSS'
    data['precision_transform_check_version']=1
    data['precision_block_transform_losses']=len(failures)
    return True
