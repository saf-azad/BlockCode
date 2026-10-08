import { describe, expect, it } from 'vitest';
import { plotFields } from './make';

const cols = [
  { name: 'dept', type: 'text' },
  { name: 'avg_grade', type: 'float' },
  { name: 'n', type: 'int' },
];

describe('plotFields', () => {
  it('keeps settings that already fit', () => {
    expect(plotFields({ chart: 'bar', x: 'dept', y: 'n' }, cols)).toEqual({ chart: 'bar', x: 'dept', y: 'n' });
  });
  it('moves a histogram off a text column', () => {
    expect(plotFields({ chart: 'hist', x: 'dept', y: 'avg_grade' }, cols).x).toBe('avg_grade');
  });
  it('gives a scatter two different number columns', () => {
    expect(plotFields({ chart: 'scatter', x: 'dept', y: 'avg_grade' }, cols)).toEqual({ chart: 'scatter', x: 'n', y: 'avg_grade' });
  });
  it('puts bars on a label and a number', () => {
    expect(plotFields({ chart: 'bar' }, cols)).toEqual({ chart: 'bar', x: 'dept', y: 'avg_grade' });
  });
  it('replaces columns the rows no longer have', () => {
    expect(plotFields({ chart: 'line', x: 'term', y: 'grade' }, cols)).toEqual({ chart: 'line', x: 'dept', y: 'avg_grade' });
  });
});
