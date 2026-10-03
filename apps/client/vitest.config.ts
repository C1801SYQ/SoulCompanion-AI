import { defineConfig } from 'vitest/config';

export default defineConfig({
  define: { PUBLIC_API_URL: JSON.stringify(''), PUBLIC_DEMO_ONLY: 'false' },
  test: { environment: 'node', include: ['tests/**/*.test.ts'], clearMocks: true },
});
