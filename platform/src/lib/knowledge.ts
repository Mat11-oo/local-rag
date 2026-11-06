import type { ApiChunkConfig, ApiKnowledgeBase, ApiModelOption } from '../api/client';

export type ChunkMethod = ApiKnowledgeBase['chunk_method'];

export const CHUNK_METHODS: Array<{ value: ChunkMethod; label: string; description: string; bestFor: string; needsLlm?: boolean }> = [
  { value: 'recursive', label: '智能分块', description: '按段落、句子逐级递归切到合适长度', bestFor: '大多数文档' },
  { value: 'heading', label: '按标题层级', description: '按 Markdown / Word 标题切分并保留标题路径', bestFor: '手册、制度、规范' },
  { value: 'separator', label: '自定义分隔符', description: '按指定符号切分，可写正则', bestFor: '条款、清单' },
  { value: 'fixed', label: '固定长度', description: '严格按字符长度和重叠切分', bestFor: '转写稿、无结构文本' },
  { value: 'parent_child', label: '父子分块', description: '子块检索、命中后返回父块上下文', bestFor: '长篇研报、技术文档' },
  { value: 'semantic', label: '语义分块', description: '由文本理解模型按主题边界切分，逐字保留原文', bestFor: '主题跳跃的长文', needsLlm: true },
  { value: 'page', label: '按页切分', description: 'PDF 一页一块，保留页码', bestFor: '扫描件、幻灯片' },
  { value: 'table_row', label: '表格按行', description: '每行带表头组合成一块', bestFor: '参数表、价格表' },
  { value: 'qa', label: '问答对', description: '表格前两列直接作为问题与答案', bestFor: 'FAQ、客服话术' },
];

export const METHOD_LABEL = Object.fromEntries(CHUNK_METHODS.map((item) => [item.value, item.label])) as Record<ChunkMethod, string>;

export function recommendedMethod(filename: string): { method: ChunkMethod; reason: string } {
  const name = filename.toLowerCase();
  if (/\.(csv|xlsx|xlsm)$/.test(name)) return { method: 'table_row', reason: '表格文件' };
  if (/\.pdf$/.test(name)) return { method: 'page', reason: 'PDF 保留页码' };
  if (/\.(md|markdown|docx)$/.test(name)) return { method: 'heading', reason: '有标题结构' };
  return { method: 'recursive', reason: '通用文本' };
}

const QA_HEADER = /(问题|提问|question|^q$)/i;
const ANSWER_HEADER = /(答案|回答|答复|answer|^a$)/i;

/** 在按扩展名推荐的基础上读取 CSV 表头：前两列像「问题 / 答案」时按问答对切块。 */
export async function detectRecommendation(file: File): Promise<{ method: ChunkMethod; reason: string }> {
  const base = recommendedMethod(file.name);
  if (!/\.csv$/i.test(file.name)) return base;
  try {
    const head = (await file.slice(0, 4096).text()).replace(/^\uFEFF/, '').split(/\r?\n/)[0] ?? '';
    const [first = '', second = ''] = head.split(/[,\t;]/).map((cell) => cell.trim().replace(/^"|"$/g, ''));
    if (QA_HEADER.test(first) && ANSWER_HEADER.test(second)) return { method: 'qa', reason: '表头为问题 / 答案' };
  } catch {
    // 读取失败时沿用扩展名推荐
  }
  return base;
}

export function defaultChunkConfig(kb: ApiKnowledgeBase, method?: ChunkMethod): ApiChunkConfig {
  return {
    method: method ?? kb.chunk_method,
    chunk_size: kb.chunk_size,
    chunk_overlap: Math.min(kb.chunk_overlap, kb.chunk_size - 1),
    parent_chunk_size: kb.parent_chunk_size,
    child_chunk_size: kb.child_chunk_size,
    separators: ['\n\n'],
    heading_level: 3,
    rows_per_chunk: 1,
    enhance_keywords: false,
    enhance_qa: false,
    qa_per_chunk: 3,
  };
}

export function configProblem(config: ApiChunkConfig, kb: ApiKnowledgeBase): string | null {
  if (config.chunk_overlap >= config.chunk_size) return '重叠长度必须小于块大小';
  if (config.method === 'parent_child' && config.child_chunk_size >= config.parent_chunk_size) return '子块必须小于父块';
  if (config.method === 'semantic' && !kb.semantic_llm_model_id) return '语义分块需要先在知识库配置中设置文本理解模型';
  if (config.method === 'separator' && !config.separators.length) return '至少填写一个分隔符';
  if (config.enhance_qa && !hasTextModel(kb)) return '生成问答对需要先在知识库配置中设置文本理解模型';
  return null;
}

/** 文本理解模型：语义分块、元数据抽取和分块增强共用其一即可。 */
export function hasTextModel(kb: ApiKnowledgeBase) {
  return !!(kb.metadata_llm_model_id || kb.semantic_llm_model_id);
}

export function modelsOf(options: ApiModelOption[], type: ApiModelOption['model_type']) {
  return options.filter((item) => item.model_type === type && item.is_enabled && item.connection_status !== 'error');
}

export const FILE_STATUS: Record<string, { label: string; tone: string }> = {
  queued: { label: '排队中', tone: '' },
  uploading: { label: '校验中', tone: 'blue' },
  parsing: { label: '解析中', tone: 'blue' },
  chunking: { label: '切块中', tone: 'blue' },
  indexing: { label: '索引中', tone: 'blue' },
  completed: { label: '已就绪', tone: 'green' },
  failed: { label: '失败', tone: 'red' },
};

export const ACTIVE_STATUSES = new Set(['queued', 'uploading', 'parsing', 'chunking', 'indexing']);

export const STAGE_LABEL: Record<string, string> = {
  queued: '排队',
  file_validation: '文件校验',
  content_parsing: '内容解析',
  metadata_extraction: '元数据抽取',
  metadata_preserved: '保留人工元数据',
  chunking: '切块',
  chunk_enhancement: '分块增强',
  embedding: '向量化',
  completed: '完成',
  failed: '失败',
};
