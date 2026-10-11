"""Block expansion with original definition identity across type conversions.

ezdxf's ordinary expansion creates ellipses for non-uniform circles without a
source-of-copy link. Preserve that link explicitly rather than infer handles
from matching coordinates. Only enabled for the separate precision pipeline.
"""
from ezdxf.entities import Ellipse
from ezdxf.math import Vec3
from ezdxf.math.transformtools import NonUniformScalingError, InsertTransformationError


def virtual_entities(blockref, skipped_entity_callback):
    matrix = blockref.matrix44()

    def transform(entity, original):
        if entity.dxftype()=='INSERT':
            # Check the rotated INSERT basis explicitly. Some ezdxf versions
            # check unrotated OCS axes and can silently approximate a shear.
            composed=entity.matrix44()*matrix
            axes=[Vec3(composed.get_row(i)[:3]).normalize() for i in range(3)]
            if any(abs(axes[i].dot(axes[j]))>1e-9 for i,j in ((0,1),(0,2),(1,2))):
                skipped_entity_callback(original,'non-representable nested INSERT transform; raw definition preserved')
                return
        try:
            entity.transform(matrix)
        except NonUniformScalingError:
            if entity.dxftype() in ('CIRCLE','ARC'):
                converted = Ellipse.from_arc(entity)
                converted.set_source_of_copy(original)
                yield converted.transform(matrix)
            elif entity.dxftype() in ('LWPOLYLINE','POLYLINE'):
                for segment in entity.virtual_entities():
                    segment.set_source_of_copy(original)
                    yield from transform(segment,original)
            else:
                skipped_entity_callback(original,'unsupported non-uniform scaling')
        except InsertTransformationError:
            # A shear cannot be expressed as a normal INSERT. Preserve raw
            # block definitions and report this explicitly; do not lose the
            # nested instance identity by flattening it without a parent.
            skipped_entity_callback(original,'non-representable nested INSERT transform; raw definition preserved')
        except (NotImplementedError, ValueError) as exc:
            skipped_entity_callback(original,str(exc))
        else:
            yield entity

    for original in blockref.block():
        if original.dxftype()=='ATTDEF':
            continue
        try:
            copied = original.copy()
            if hasattr(copied,'remove_association'):
                copied.remove_association()
        except Exception as exc:
            skipped_entity_callback(original,f'copy failed: {exc}')
            continue
        for transformed in transform(copied,original):
            transformed.set_source_block_reference(blockref)
            yield transformed
