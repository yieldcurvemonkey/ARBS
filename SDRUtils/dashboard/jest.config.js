// ABOUTME: Jest configuration for dashboard integration tests.
// ABOUTME: Tests run against actual API endpoints via fetch.

/** @type {import('jest').Config} */
const config = {
  testEnvironment: 'node',
  transform: {
    '^.+\\.tsx?$': ['ts-jest', {
      useESM: true,
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
