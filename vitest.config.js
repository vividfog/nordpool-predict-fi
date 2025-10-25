import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'jsdom',
    setupFiles: ['tests/js/setup.js'],
    globals: true,
    fakeTimers: {
      enableGlobally: false
    },
    include: ['tests/js/**/*.test.{js,ts}'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'lcov'],
      reportsDirectory: 'coverage',
      include: [
        'deploy/js/**/*.js'
      ],
      exclude: [
        'deploy/**/vendor/**',
        'node_modules/**',
        'private/**',
        'archive/**',
        'data/**',
        'logs/**'
      ]
    }
  }
});
