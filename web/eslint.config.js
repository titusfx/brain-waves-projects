// @ts-check
/**
 * ESLint flat config.
 *
 * Angular 22 ships flat config only, and ESLint 10 removed eslintrc, so this file is
 * the only supported shape.
 */
const eslint = require('@eslint/js');
const tseslint = require('typescript-eslint');
const angular = require('angular-eslint');
const prettier = require('eslint-config-prettier');

module.exports = tseslint.config(
  {
    ignores: [
      'dist/**',
      '.angular/**',
      'node_modules/**',
      'coverage/**',
      // Generated from the backend's OpenAPI document by `npm run api:types`. Its shape
      // is dictated by the server, so linting it would fail the build the moment the
      // API grows a construct these rules dislike.
      'src/app/core/api/schema.d.ts',
    ],
  },
  {
    files: ['**/*.ts'],
    extends: [
      eslint.configs.recommended,
      ...tseslint.configs.recommended,
      ...tseslint.configs.stylistic,
      ...angular.configs.tsRecommended,
      prettier,
    ],
    // Required to lint INLINE templates inside components.
    processor: angular.processInlineTemplates,
    rules: {
      '@angular-eslint/directive-selector': [
        'error',
        { type: 'attribute', prefix: 'eeg', style: 'camelCase' },
      ],
      '@angular-eslint/component-selector': [
        'error',
        { type: 'element', prefix: 'eeg', style: 'kebab-case' },
      ],
      // `no-public` rather than `explicit`: the point of this rule is to make the
      // *inner* API explicit — a member is private or protected only on purpose — while
      // a component's inputs, outputs and signals are public by definition, and
      // `public readonly channels = input(...)` on forty declarations is noise that
      // hides the four members that really are internal.
      '@typescript-eslint/explicit-member-accessibility': [
        'error',
        { accessibility: 'no-public', overrides: { constructors: 'no-public' } },
      ],
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
      // The monitor draws to a canvas and reports failures to the operator, so the
      // console is allowed — but only for warnings and errors.
      'no-console': ['warn', { allow: ['warn', 'error'] }],
    },
  },
  {
    files: ['**/*.html'],
    extends: [...angular.configs.templateRecommended, ...angular.configs.templateAccessibility],
    rules: {},
  },
);
