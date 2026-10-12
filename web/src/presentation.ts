import type { Model } from './model';

export const SITE_NAME = 'BIM 기반 BF개선';

// Display formatting only: model IDs, evidence, hashes and exports stay intact.
export function displayText(value: string | null | undefined): string {
  return (value ?? '').replace(/[ \t]*[\u00b7\u2022\u2219\u22c5][ \t]*/g, ' ');
}

export function modelLabel(model: Model): string {
  return model.provenance.coordination_draft
    ? displayText(model.name.split('\u00b7')[0]).trim()
    : displayText(model.name);
}

const uncertaintyNames: Record<string, string> = {
  native_beam_outline: '보의 원본 외곽', individual_SL_level: '구간별 구조 기준 높이',
  beam_member_assignment: '보 부호와 부재의 연결', local_joint_detail: '접합 상세', reinforcement: '배근 상세',
  member_identity: '부재 식별', material: '재료', member_bottom: '부재 하단', member_top: '부재 상단',
  design_revision: '도면 개정', structural_assignment: '구조 부재 분류', wall_top: '벽 상단',
  structural_role: '구조 역할', finish_assignment: '마감 규격', slab_thickness: '슬래브 두께',
  structural_boundary: '구조 경계', opening_assignment: '개구부 위치', individual_roof_level_assignment: '구간별 지붕 높이',
  slope: '경사', penthouse_wall_assignment: '옥탑 벽체', parapet_height: '파라펫 높이',
};

export function uncertaintyLabel(value: string): string {
  return uncertaintyNames[value] ?? displayText(value);
}
