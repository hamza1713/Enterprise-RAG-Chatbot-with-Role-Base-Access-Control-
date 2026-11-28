import test from 'node:test';
import assert from 'node:assert/strict';
import { parseContexts } from '../src/utils/parseContexts.ts';

test('parseContexts returns empty array for undefined or empty values', () => {
  assert.deepEqual(parseContexts(undefined), []);
  assert.deepEqual(parseContexts(''), []);
  assert.deepEqual(parseContexts('   '), []);
});

test('parseContexts passes through string arrays', () => {
  assert.deepEqual(parseContexts(['chunk one', 'chunk two']), ['chunk one', 'chunk two']);
});

test('parseContexts parses valid JSON arrays without alteration', () => {
  assert.deepEqual(
    parseContexts('["FinSolve\'s revenue grew 22%", "Second chunk"]'),
    ["FinSolve's revenue grew 22%", 'Second chunk'],
  );
});

test('parseContexts parses Python list repr preserving inner quotes and apostrophes', () => {
  const pyRepr = `["FinSolve's 2024 EBITDA margin", 'Team "Alpha" policy']`;
  assert.deepEqual(parseContexts(pyRepr), [
    "FinSolve's 2024 EBITDA margin",
    'Team "Alpha" policy',
  ]);
});
