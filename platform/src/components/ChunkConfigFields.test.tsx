import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { expect, test } from 'vitest';
import type { ApiChunkConfig } from '../api/client';
import { ChunkConfigFields } from './ChunkConfigFields';

const base: ApiChunkConfig = { method: 'separator', chunk_size: 800, chunk_overlap: 80, parent_chunk_size: 2000, child_chunk_size: 400, separators: [], heading_level: 3, rows_per_chunk: 1 };

test('separator textarea accepts several lines typed by hand', async () => {
  let latest = base;
  function Harness() {
    const [config, setConfig] = useState(base);
    latest = config;
    return <ChunkConfigFields config={config} patch={(value) => setConfig((current) => ({ ...current, ...value }))} />;
  }
  render(<Harness />);
  const box = screen.getAllByRole('textbox').find((item) => item.tagName === 'TEXTAREA')!;
  await userEvent.type(box, '。{Enter}；');
  expect(box).toHaveValue('。\n；');
  expect(latest.separators).toEqual(['。', '；']);
});
