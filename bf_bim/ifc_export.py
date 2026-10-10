"""IFC4 architectural solids, planar unknowns and assemblies with CAD evidence."""
import hashlib
import json
import ifcopenshell
import ifcopenshell.api
import ifcopenshell.guid
from shapely.geometry.polygon import orient
from shapely.geometry import Polygon
from .geometry import footprint, polygon_parts, solid_parts
from .schema import Model

CLASSES={'wall':'IfcWall','column':'IfcColumn','beam':'IfcBeam','floor':'IfcSlab','roof':'IfcRoof','window':'IfcWindow','opening':'IfcBuildingElementProxy','door':'IfcDoor',
    'space':'IfcSpace','corridor':'IfcSpace','stair':'IfcStair','ramp':'IfcRamp',
    'elevator':'IfcTransportElement','obstacle':'IfcBuildingElementProxy','unclassified':'IfcBuildingElementProxy'}

def export_ifc(model:Model):
    f=ifcopenshell.api.run('project.create_file',version='IFC4')
    def root(cls,name,identity):
        obj=ifcopenshell.api.run('root.create_entity',f,ifc_class=cls,name=name)
        obj.GlobalId=ifcopenshell.guid.compress(hashlib.md5((model.id+'/'+identity).encode()).hexdigest())
        return obj
    project=root('IfcProject',model.name,'project')
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
    styled=[]
    def placement(obj):
        obj.ObjectPlacement=f.create_entity('IfcLocalPlacement',RelativePlacement=f.create_entity(
            'IfcAxis2Placement3D',Location=f.create_entity('IfcCartesianPoint',Coordinates=[0.,0.,0.])))
    def component_geometry(obj,poly,z,depth):
        poly=orient(poly,sign=1.)
        if depth is None:
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
        if e.components:
            children=[]
            for i,c in enumerate(e.components):
                part=root('IfcBuildingElementPart',f'{e.name} · {c.role} {i+1}',e.id+f'/component/{i}')
                placement(part);children.append(part)
                component_geometry(part,Polygon(c.polygon,c.holes),elevations[e.floor_id]+e.z_offset+c.z_offset,c.height)
                props=ifcopenshell.api.run('pset.add_pset',f,product=part,name='Pset_ArchitecturalEvidence')
                ifcopenshell.api.run('pset.edit_pset',f,pset=props,properties={'ParentElementId':e.id,'Role':c.role,
                    'GeometryStatus':'reconstruction_candidate','CADSource':f.create_entity('IfcText',json.dumps(c.source,ensure_ascii=False))})
                styled.append((part,e.type,e.source.get('material','unknown')))
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
        for poly,relative_z,depth in solid_parts(e,model.elements):
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
