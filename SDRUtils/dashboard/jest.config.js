// ABOUTME: Jest configuration for dashboard integration tests.
// ABOUTME: Tests run against actual API endpoints via fetch.

/** @type {import('jest').Config} */
const config = {
  testEnvironment: 'node',
  transform: {
    '^.+\\.tsx?$': ['ts-jest', {
      useESM: true,
      // Override tsconfig's jsx="preserve" (which Next.js owns) so that
      // ts-jest emits runnable JSX during tests. Tests still see normal
      // TS strictness from the project tsconfig — only the JSX factory
      // mode is overridden.
      tsconfig: {
        jsx: 'react-jsx',
      },
    }],
  },
  extensionsToTreatAsEsm: ['.ts', '.tsx'],
  moduleNameMapper: {
    '^@/(.*)$': '<rootDir>/src/$1',
  },
  testMatch: [
    '**/__tests__/**/*.test.ts',
    '**/__tests__/**/*.test.tsx',
    '**/*.route.test.ts',
    '**/*.route.test.tsx',
  ],
  testTimeout: 30000,
  verbose: true,
}

module.exports = config
