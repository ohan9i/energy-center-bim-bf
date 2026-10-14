import {defineConfig,mergeConfig} from 'vitest/config';
import viteConfig from './vite.config';

// Integration files parse the complete CAD model. Bound concurrent copies in
// memory and allow their geometry checks to finish on a two-core CI runner.
export default mergeConfig(viteConfig,defineConfig({test:{maxWorkers:2,testTimeout:15000}}));
