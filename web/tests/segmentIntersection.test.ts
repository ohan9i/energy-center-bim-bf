import {it,expect} from 'vitest';
import {intersects} from '../src/geometry';
it('does not confuse small cross products with actual segment intersections',()=>{
 expect(intersects([0,0],[1,0],[0,.00001],[1,.00001])).toBe(false);
 expect(intersects([0,0],[1,0],[.5,-1],[.5,1])).toBe(true);
 expect(intersects([0,0],[1,0],[1,0],[2,0])).toBe(true);
 expect(intersects([0,0],[1,0],[1.001,0],[2,0])).toBe(false);
});
