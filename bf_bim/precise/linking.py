"""Explicit member-specific cross-view assignments; no nearest-text sizing."""
from __future__ import annotations

from .schema import Member, Observation
from .validation import resolve_dimension


def attach_evidence(member: Member, observations: list[Observation], *,
                    drawing_hashes: dict[str, str], member_match_confirmed: bool) -> Member:
    result = Member.model_validate(member.model_dump())
    for observation in observations:
        ref = observation.reference
        if drawing_hashes.get(ref.drawing_id) != ref.source_sha256:
            raise ValueError('Evidence revision is not the active drawing revision')
        if observation.status == 'confirmed' and not member_match_confirmed:
            raise ValueError('A schedule/dimension value cannot be assigned without a confirmed member match')
        if observation.status=='confirmed' and observation.member_id!=member.id:
            raise ValueError('Confirmed observation must identify this exact member')
        if observation.status == 'confirmed' and not ref.drawing_number:
            raise ValueError('Confirmed cross-view evidence requires an identified drawing number')
        if observation.id not in result.evidence_ids:
            result.evidence_ids.append(observation.id)
        if ref not in result.references:
            result.references.append(ref)
    if member_match_confirmed:
        for field in result.dimensions:
            resolved = resolve_dimension(field,observations)
            if resolved.status == 'unknown': continue
            # Existing evidence must be supplied too; otherwise revisions could
            # silently overwrite contradictory values.
            previous = result.dimensions[field]
            if previous.evidence_ids and not set(previous.evidence_ids).issubset({e.id for e in observations}):
                raise ValueError('Include all existing dimension observations when resolving an update')
            result.dimensions[field] = resolved
            if resolved.status == 'conflict':
                result.conflicts.append({'type':'dimension_conflict','field':field,'evidence_ids':resolved.evidence_ids})
                result.verification='conflict'
            elif field in result.unknowns:
                result.unknowns.remove(field)
    # Attachment cannot silently promote geometry/semantics to verified.
    return Member.model_validate(result.model_dump())
