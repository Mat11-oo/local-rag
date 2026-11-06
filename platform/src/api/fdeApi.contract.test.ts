import { afterEach, describe, expect, it, vi } from 'vitest';
import { fdeApi, type AppManifest } from './fde';

const manifest: AppManifest = {
  schema_version: 'fde.app/v2',
  type: 'simple',
  name: '内容应用',
  description: '',
  template_key: 'content',
  system_prompt: '生成内容',
  llm_model_id: 'model-1',
  model: { temperature: 0.2, max_tokens: 4096, thinking_mode: 'auto' },
  knowledge_base_ids: [],
  input_fields: [],
  output: { format: 'markdown' },
  tools: [],
  guardrails: { blocked_topics: [], require_citations: false, refuse_without_evidence: false, human_handoff: false, max_output_chars: 8000 },
  memory: { enabled: false, max_turns: 10 },
  delivery: { channel: 'web', show_citations: false, allow_copy: true, allow_export: false },
  agent: { max_steps: 8, require_confirmation_for_side_effects: true, show_tool_steps: true, long_term_memory: false, knowledge_mode: 'tool' },
  experience: { opening: '', suggestions: [] },
};

afterEach(() => vi.unstubAllGlobals());

describe('FDE API contract', () => {
  it('uses the shared manifest endpoint without publishing a draft', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: 'app-1' }), { status: 201 }));
    vi.stubGlobal('fetch', fetchMock);
    await fdeApi.create(manifest);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain('/fde/apps');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body).manifest).toEqual(manifest);
  });

  it('publishes an explicit immutable version', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: 'app-1' }), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    await fdeApi.publish('app-1', 'version-2');
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ version_id: 'version-2' });
  });
});
