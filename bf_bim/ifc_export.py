"""IFC4 architectural solids, planar unknowns and assemblies with CAD evidence."""
import hashlib
import json
import ifcopenshell
import ifcopenshell.api
import ifcopenshell.guid
from shapely.geometry.polygon import orient
from shapely.geometry import Polygon
from shapely.ops import unary_union
from .geometry import footprint, polygon_parts, solid_parts,opening_footprint,architectural_footprint
from .schema import Model

CLASSES={'wall':'IfcWall','column':'IfcColumn','beam':'IfcBeam','floor':'IfcSlab','roof':'IfcRoof','window':'IfcWindow','opening':'IfcBuildingElementProxy','door':'IfcDoor',
    'space':'IfcSpace','corridor':'IfcSpace','stair':'IfcStair','ramp':'IfcRamp',
    'elevator':'IfcTransportElement','obstacle':'IfcBuildingElementProxy','unclassified':'IfcBuildingElementProxy'}

def export_ifc(model:Model, *, coordination_draft=False):
    if coordination_draft and (model.provenance.get('export_status') != 'coordination_draft' or any(e.verified for e in model.elements)):
        raise ValueError('Draft export requires an explicitly labelled, unverified coordination model')
    if model.provenance.get('precision_rebuild') and not coordination_draft:
        raise ValueError('미확정 재구축 미리보기는 IFC로 출력할 수 없습니다. 별도의 verified.ifc를 사용하세요.')
    f=ifcopenshell.api.run('project.create_file',version='IFC4')
    def root(cls,name,identity):
        obj=ifcopenshell.api.run('root.create_entity',f,ifc_class=cls,name=name)
        obj.GlobalId=ifcopenshell.guid.compress(hashlib.md5((model.id+'/'+identity).encode()).hexdigest())
        return obj
    project=root('IfcProject',model.name,'project')
    if coordination_draft:
        ps=ifcopenshell.api.run('pset.add_pset',f,product=project,name='Pset_CoordinationDraft')
        ifcopenshell.api.run('pset.edit_pset',f,pset=ps,properties={'Status':'DRAFT - NOT DESIGN VERIFIED','VerifiedSolids':int(model.provenance.get('verified_solids',0)),
            'Assumptions':f.create_entity('IfcText',json.dumps(model.provenance.get('assumption_parameters',{}),ensure_ascii=False))})
    unit=ifcopenshell.api.run('unit.add_si_unit',f,unit_type='LENGTHUNIT')
    ifcopenshell.api.run('unit.assign_unit',f,units=[unit])
    ctx=ifcopenshell.api.run('context.add_context',f,context_type='Model')
    body=ifcopenshell.api.run('context.add_context',f,context_type='Model',context_identifier='Body',target_view='MODEL_VIEW',parent=ctx)
    site=root('IfcSite','Site','site');building=root('IfcBuilding',model.name,'building')
    ifcopenshell.api.run('aggregate.assign_object',f,products=[site],relating_object=project)
    ifcopenshell.api.run('aggregate.assign_object',f,products=[building],relating_object=site)
    if model.provenance.get('drawing_evidence'):
        evidence=ifcopenshell.api.run('pset.add_pset',f,product=building,name='Pset_DrawingSurvey')
        ifcopenshell.api.run('pset.edit_pset',f,pset=evidence,properties={
            'MemberAssignmentVerified':False,'DrawingEvidence':f.create_entity('IfcText',json.dumps(model.provenance['drawing_evidence'],ensure_ascii=False)),
            'Note':'Detail/schedule specifications are evidence candidates, not member assignments.'})
    floors={}
    for floor in model.floors:
        storey=root('IfcBuildingStorey',floor.name,floor.id);storey.Elevation=floor.elevation
        ifcopenshell.api.run('aggregate.assign_object',f,products=[storey],relating_object=building)
        floors[floor.id]=storey
    elevations={r.id:r.elevation for r in model.floors}
    styled=[];objects={};member_types={}
    def placement(obj):
        obj.ObjectPlacement=f.create_entity('IfcLocalPlacement',RelativePlacement=f.create_entity(
            'IfcAxis2Placement3D',Location=f.create_entity('IfcCartesianPoint',Coordinates=[0.,0.,0.])))
    def component_geometry(obj,poly,z,depth,mesh=None):
        poly=orient(poly,sign=1.)
        if mesh is not None:
            coordinates=f.create_entity('IfcCartesianPointList3D',CoordList=[(float(x),float(y),float(v+z)) for x,y,v in mesh.vertices])
            item=f.create_entity('IfcTriangulatedFaceSet',Coordinates=coordinates,Closed=True,
                CoordIndex=[tuple(i+1 for i in t) for t in mesh.triangles])
            rep_type='Tessellation'
        elif depth is None:
            def loop(coords):return f.create_entity('IfcPolyLoop',Polygon=[f.create_entity('IfcCartesianPoint',Coordinates=[float(x),float(y),float(z)]) for x,y in list(coords)[:-1]])
            bounds=[f.create_entity('IfcFaceOuterBound',Bound=loop(poly.exterior.coords),Orientation=True)]
            bounds.extend(f.create_entity('IfcFaceBound',Bound=loop(r.coords),Orientation=True) for r in poly.interiors)
            face=f.create_entity('IfcFace',Bounds=bounds)
            item=f.create_entity('IfcFaceBasedSurfaceModel',FbsmFaces=[f.create_entity('IfcConnectedFaceSet',CfsFaces=[face])])
            rep_type='SurfaceModel'
        else:
            def curve(coords):return f.create_entity('IfcPolyline',Points=[f.create_entity('IfcCartesianPoint',Coordinates=[float(x),float(y)]) for x,y in coords])
            profile=f.create_entity('IfcArbitraryProfileDefWithVoids',ProfileType='AREA',OuterCurve=curve(poly.exterior.coords),InnerCurves=[curve(r.coords) for r in poly.interiors]) if poly.interiors else f.create_entity('IfcArbitraryClosedProfileDef',ProfileType='AREA',OuterCurve=curve(poly.exterior.coords))
            item=f.create_entity('IfcExtrudedAreaSolid',SweptArea=profile,Position=f.create_entity('IfcAxis2Placement3D',Location=f.create_entity('IfcCartesianPoint',Coordinates=[0.,0.,float(z)])),ExtrudedDirection=f.create_entity('IfcDirection',DirectionRatios=[0.,0.,1.]),Depth=float(depth))
            rep_type='SweptSolid'
        rep=f.create_entity('IfcShapeRepresentation',ContextOfItems=body,RepresentationIdentifier='Body',RepresentationType=rep_type,Items=[item])
        ifcopenshell.api.run('geometry.assign_representation',f,product=obj,representation=rep)
    for e in model.elements:
        if e.excluded:continue
        obj=root(CLASSES[e.type],e.name,e.id)
        objects[e.id]=obj
        definition=e.source.get('type_definition')
        if definition and e.type in ('window','door'):
            key=json.dumps({k:definition.get(k) for k in ('kind','mark','width_m','height_m','glass_thickness_m')},sort_keys=True)
            if key not in member_types:
                identity=e.type+'-type/'+hashlib.sha256(key.encode()).hexdigest()[:20]
                member_types[key]=root('IfcWindowType' if e.type=='window' else 'IfcDoorType',definition['mark'],identity)
                member_types[key].PredefinedType=e.type.upper()
                if e.type=='door':member_types[key].OperationType='NOTDEFINED'
                ps=ifcopenshell.api.run('pset.add_pset',f,product=member_types[key],name='Pset_DrawingTypeEvidence')
                ifcopenshell.api.run('pset.edit_pset',f,pset=ps,properties={
                    'Status':definition['status'],'DesignVerified':False,
                    'Specifications':f.create_entity('IfcText',json.dumps(definition,ensure_ascii=False))})
            ifcopenshell.api.run('type.assign_type',f,related_objects=[obj],relating_type=member_types[key],should_map_representations=False)
            obj.OverallWidth=definition['width_m'];obj.OverallHeight=definition['height_m']
        styled.append((obj,e.type,e.source.get('material','unknown')))
        # Profiles and solid elevations are in model world coordinates. An identity
        # placement preserves those coordinates and satisfies IFC's product rule.
        obj.ObjectPlacement=f.create_entity('IfcLocalPlacement',RelativePlacement=f.create_entity(
            'IfcAxis2Placement3D',Location=f.create_entity('IfcCartesianPoint',Coordinates=[0.,0.,0.])))
        if e.type=='elevator':obj.PredefinedType='ELEVATOR'
        if e.type in ('space','corridor'):
            ifcopenshell.api.run('aggregate.assign_object',f,products=[obj],relating_object=floors[e.floor_id])
        else:
            ifcopenshell.api.run('spatial.assign_container',f,products=[obj],relating_structure=floors[e.floor_id])
        props=ifcopenshell.api.run('pset.add_pset',f,product=obj,name='Pset_BFNavigation')
        ifcopenshell.api.run('pset.edit_pset',f,pset=props,properties={'ModelElementId':e.id,'Verified':e.verified,
            'CADSource':f.create_entity('IfcText',json.dumps(e.source,ensure_ascii=False)),
            'MobilityProperties':f.create_entity('IfcText',e.properties.model_dump_json()),
            'GeometryNote':'Architectural vertical slices; opening head retained when height is known. Unknown heights are planar. Stair assembly evidence in CADSource.'})
        evidence=ifcopenshell.api.run('pset.add_pset',f,product=obj,name='Pset_ArchitecturalEvidence')
        ifcopenshell.api.run('pset.edit_pset',f,pset=evidence,properties={
            'GeometryStatus':str(e.source.get('geometry_status','legacy')),
            'HeightEvidence':str(e.source.get('height_source','unknown')),
            'AssemblyComponents':f.create_entity('IfcText',json.dumps([c.model_dump() for c in e.components],ensure_ascii=False)),
            'PlanAreaM2':float(Polygon(e.polygon,e.holes).area),
            'QuantityVerified':False})
        if e.source.get('unresolved_no_representation'):
            continue
        if e.components:
            children=[]
            for i,c in enumerate(e.components):
                identity=c.id or e.id+f'/component/{i}'
                part=root('IfcBuildingElementPart',f'{e.name} · {c.role} {i+1}',identity)
                placement(part);children.append(part)
                component_geometry(part,Polygon(c.polygon,c.holes),elevations[e.floor_id]+e.z_offset+c.z_offset,c.height,c.mesh)
                props=ifcopenshell.api.run('pset.add_pset',f,product=part,name='Pset_ArchitecturalEvidence')
                ifcopenshell.api.run('pset.edit_pset',f,pset=props,properties={'ParentElementId':e.id,'ComponentId':identity,'Role':c.role,
                    'GeometryStatus':str(c.source.get('geometry_status','reconstruction_candidate')),
                    'DimensionVerified':bool(c.source.get('dimension_verified',False)),
                    'CADSource':f.create_entity('IfcText',json.dumps(c.source,ensure_ascii=False))})
                styled.append((part,'window' if c.source.get('material')=='glazing' else 'column' if c.source.get('material')=='metal' else 'floor' if c.source.get('material')=='finish' else e.type,c.source.get('material',e.source.get('material','unknown'))))
            ifcopenshell.api.run('aggregate.assign_object',f,products=children,relating_object=obj)
            continue
        if e.height is None:
            faces=[]
            for poly,relative_z,depth in solid_parts(e,model.elements):
                poly=orient(poly,sign=1.)
                def loop(coords):
                    return f.create_entity('IfcPolyLoop',Polygon=[f.create_entity('IfcCartesianPoint',Coordinates=[float(x),float(y),float(elevations[e.floor_id]+relative_z)]) for x,y in list(coords)[:-1]])
                bounds=[f.create_entity('IfcFaceOuterBound',Bound=loop(poly.exterior.coords),Orientation=True)]
                bounds.extend(f.create_entity('IfcFaceBound',Bound=loop(r.coords),Orientation=True) for r in poly.interiors)
                faces.append(f.create_entity('IfcFace',Bounds=bounds))
            if faces:
                surface=f.create_entity('IfcFaceBasedSurfaceModel',FbsmFaces=[f.create_entity('IfcConnectedFaceSet',CfsFaces=faces)])
                rep=f.create_entity('IfcShapeRepresentation',ContextOfItems=body,RepresentationIdentifier='Body',RepresentationType='SurfaceModel',Items=[surface])
                ifcopenshell.api.run('geometry.assign_representation',f,product=obj,representation=rep)
            continue
        solids=[]
        pieces=solid_parts(e,model.elements)
        if e.type=='wall' and any(d.type in ('door','window') and not d.excluded and d.floor_id==e.floor_id and
            (d.height is not None or d.source.get('provisional_opening')) and opening_footprint(d).intersects(architectural_footprint(e)) for d in model.elements):
            # IFC engines apply IfcRelVoidsElement. Export an unsliced host so the
            # boolean is evaluated once; pre-slicing followed by void subtraction
            # can erase thin finish fragments through OCCT tolerances.
            envelopes=e.source.get('architectural_vertical_profiles')
            pieces=[(Polygon(q['polygon'],q.get('holes',[])),q['z_offset'],q['height']) for q in envelopes] if envelopes is not None else [(p,e.z_offset,e.height) for p in polygon_parts(architectural_footprint(e))]
        for poly,relative_z,depth in pieces:
            if depth is None:
                # Landing surfaces are retained separately below, without fabricated slab thickness.
                continue
            def curve(coords):
                return f.create_entity('IfcPolyline',Points=[f.create_entity('IfcCartesianPoint',Coordinates=[float(x),float(y)]) for x,y in coords])
            outer=curve(poly.exterior.coords)
            profile=f.create_entity('IfcArbitraryProfileDefWithVoids',ProfileType='AREA',OuterCurve=outer,InnerCurves=[curve(r.coords) for r in poly.interiors]) if poly.interiors else f.create_entity('IfcArbitraryClosedProfileDef',ProfileType='AREA',OuterCurve=outer)
            position=f.create_entity('IfcAxis2Placement3D',Location=f.create_entity('IfcCartesianPoint',Coordinates=[0.,0.,float(elevations[e.floor_id]+relative_z)]))
            solid=f.create_entity('IfcExtrudedAreaSolid',SweptArea=profile,Position=position,ExtrudedDirection=f.create_entity('IfcDirection',DirectionRatios=[0.,0.,1.]),Depth=float(depth))
            solids.append(solid)
        if solids:
            rep=f.create_entity('IfcShapeRepresentation',ContextOfItems=body,RepresentationIdentifier='Body',RepresentationType='SweptSolid',Items=solids)
            ifcopenshell.api.run('geometry.assign_representation',f,product=obj,representation=rep)
    # Semantic void/fill relationships complement the identical pre-sliced wall solids.
    # Opening bounds are clipped to the host; unverified heights remain identified.
    for e in model.elements:
        if e.id not in objects or e.type not in ('door','window'):continue
        provisional=e.source.get('provisional_opening',{})
        height=e.height if e.height is not None else provisional.get('height')
        z=e.z_offset+(0 if e.height is not None else provisional.get('z_offset',0))
        if height is None:continue
        filled=False
        for wall in model.elements:
            if wall.id not in objects or wall.type!='wall' or wall.floor_id!=e.floor_id:continue
            if wall.height is None:
                # Coordination hosts have pre-cut component bodies and no parent
                # height. Preserve their explicit envelope instead of dropping
                # the semantic opening or inventing a parent solid.
                envelope=wall.source.get('assumptions',{}).get('height',{}).get('value_m')
                if not wall.components or envelope is None:continue
                records=[q for q in e.source.get('host_openings',[]) if q['host_wall_id']==wall.id]
                if not records:continue
                intersection=unary_union([Polygon(q['polygon'],q.get('holes',[])) for q in records])
                host_height=envelope
            else:
                intersection=architectural_footprint(wall).intersection(opening_footprint(e))
                host_height=wall.height
            lo=max(z,wall.z_offset);hi=min(z+height,wall.z_offset+host_height)
            if hi<=lo:continue
            for i,poly in enumerate(polygon_parts(intersection)):
                if poly.area<1e-6:continue
                opening=root('IfcOpeningElement',e.name+' · 개구부 후보',e.id+'/'+wall.id+f'/void/{i}')
                placement(opening);component_geometry(opening,poly,elevations[e.floor_id]+lo,hi-lo)
                opening.PredefinedType='OPENING'
                f.create_entity('IfcRelVoidsElement',GlobalId=ifcopenshell.guid.new(),RelatingBuildingElement=objects[wall.id],RelatedOpeningElement=opening)
                if not filled:
                    f.create_entity('IfcRelFillsElement',GlobalId=ifcopenshell.guid.new(),RelatingOpeningElement=opening,RelatedBuildingElement=objects[e.id]);filled=True
                ps=ifcopenshell.api.run('pset.add_pset',f,product=opening,name='Pset_OpeningEvidence')
                ifcopenshell.api.run('pset.edit_pset',f,pset=ps,properties={'DimensionVerified':e.height is not None and e.verified,'ModelElementId':e.id,'HostWallId':wall.id})
    palette={'wall':(.79,.82,.8),'column':(.46,.51,.55),'floor':(.89,.87,.82),'roof':(.7,.73,.75),
        'door':(.59,.44,.27),'window':(.5,.78,.87),'stair':(.69,.67,.63),'elevator':(.54,.6,.67),'space':(.57,.75,.69),'corridor':(.66,.76,.85)}
    styles={};materials={}
    for obj,kind,material_name in styled:
        if obj.is_a('IfcElement'):
            if material_name not in materials:materials[material_name]=f.create_entity('IfcMaterial',Name=material_name+' (CAD classification candidate)')
            f.create_entity('IfcRelAssociatesMaterial',GlobalId=ifcopenshell.guid.new(),RelatedObjects=[obj],RelatingMaterial=materials[material_name])
        if obj.Representation is None:continue
        if kind not in styles:
            r,g,b=palette.get(kind,(.65,.7,.72));rgb=f.create_entity('IfcColourRgb',Red=r,Green=g,Blue=b)
            shade=f.create_entity('IfcSurfaceStyleRendering',SurfaceColour=rgb,Transparency=.5 if kind=='window' else .8 if kind=='elevator' else 0.,ReflectanceMethod='NOTDEFINED')
            styles[kind]=f.create_entity('IfcSurfaceStyle',Name=kind,Side='BOTH',Styles=[shade])
        for rep in obj.Representation.Representations:
            for item in rep.Items:f.create_entity('IfcStyledItem',Item=item,Styles=[styles[kind]])
    return f.to_string()
