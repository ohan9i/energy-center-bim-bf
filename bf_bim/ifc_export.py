"""IFC4 metre-based simplified footprint extrusions with stable IDs and CAD provenance."""
import hashlib
import json
import ifcopenshell
import ifcopenshell.api
import ifcopenshell.guid
from shapely.geometry.polygon import orient
from .geometry import footprint, polygon_parts
from .schema import Model

CLASSES={'wall':'IfcWall','column':'IfcColumn','floor':'IfcSlab','door':'IfcDoor',
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
    floors={}
    for floor in model.floors:
        storey=root('IfcBuildingStorey',floor.name,floor.id);storey.Elevation=floor.elevation
        ifcopenshell.api.run('aggregate.assign_object',f,products=[storey],relating_object=building)
        floors[floor.id]=storey
    elevations={r.id:r.elevation for r in model.floors}
    for e in model.elements:
        if e.excluded:continue
        obj=root(CLASSES[e.type],e.name,e.id)
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
            'GeometryNote':'Simplified full-height door opening; no lintel. Null height has planar footprint only.'})
        if e.height is None:
            faces=[]
            for poly in polygon_parts(footprint(e,model.elements)):
                poly=orient(poly,sign=1.)
                def loop(coords):
                    return f.create_entity('IfcPolyLoop',Polygon=[f.create_entity('IfcCartesianPoint',Coordinates=[float(x),float(y),float(elevations[e.floor_id]+e.z_offset)]) for x,y in list(coords)[:-1]])
                bounds=[f.create_entity('IfcFaceOuterBound',Bound=loop(poly.exterior.coords),Orientation=True)]
                bounds.extend(f.create_entity('IfcFaceBound',Bound=loop(r.coords),Orientation=True) for r in poly.interiors)
                faces.append(f.create_entity('IfcFace',Bounds=bounds))
            if faces:
                surface=f.create_entity('IfcFaceBasedSurfaceModel',FbsmFaces=[f.create_entity('IfcConnectedFaceSet',CfsFaces=faces)])
                rep=f.create_entity('IfcShapeRepresentation',ContextOfItems=body,RepresentationIdentifier='Body',RepresentationType='SurfaceModel',Items=[surface])
                ifcopenshell.api.run('geometry.assign_representation',f,product=obj,representation=rep)
            continue
        solids=[]
        for poly in polygon_parts(footprint(e,model.elements)):
            def curve(coords):
                return f.create_entity('IfcPolyline',Points=[f.create_entity('IfcCartesianPoint',Coordinates=[float(x),float(y)]) for x,y in coords])
            outer=curve(poly.exterior.coords)
            profile=f.create_entity('IfcArbitraryProfileDefWithVoids',ProfileType='AREA',OuterCurve=outer,InnerCurves=[curve(r.coords) for r in poly.interiors]) if poly.interiors else f.create_entity('IfcArbitraryClosedProfileDef',ProfileType='AREA',OuterCurve=outer)
            position=f.create_entity('IfcAxis2Placement3D',Location=f.create_entity('IfcCartesianPoint',Coordinates=[0.,0.,float(elevations[e.floor_id]+e.z_offset)]))
            solid=f.create_entity('IfcExtrudedAreaSolid',SweptArea=profile,Position=position,ExtrudedDirection=f.create_entity('IfcDirection',DirectionRatios=[0.,0.,1.]),Depth=float(e.height))
            solids.append(solid)
        if solids:
            rep=f.create_entity('IfcShapeRepresentation',ContextOfItems=body,RepresentationIdentifier='Body',RepresentationType='SweptSolid',Items=solids)
            ifcopenshell.api.run('geometry.assign_representation',f,product=obj,representation=rep)
    return f.to_string()
