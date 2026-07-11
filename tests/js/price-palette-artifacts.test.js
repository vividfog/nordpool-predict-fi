import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const readDeployFile = name => readFileSync(resolve('deploy', name), 'utf8');

describe('deployed Home Assistant price palettes', () => {
  it.each([
    ['npf.yaml', 3],
    ['npf2.yaml', 1]
  ])('uses darker green for the cheaper bands in %s', (filename, bandCount) => {
    const yaml = readDeployFile(filename);
    const consistentPriceScales = yaml.match(
      /color: limegreen\n\s+color_threshold:\n\s+- value: 0\n\s+color: limegreen\n\s+- value: 5\n\s+color: lime/g
    ) || [];

    expect(consistentPriceScales).toHaveLength(bandCount);
    expect(yaml).not.toMatch(
      /- value: 0\n\s+color: lime\n\s+- value: 5\n\s+color: limegreen/
    );
  });
});
