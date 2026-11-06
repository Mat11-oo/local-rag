export type Role = 'admin' | 'knowledge' | 'user';
export type Page = 'overview' | 'knowledge' | 'tasks' | 'assistants' | 'chat' | 'logs' | 'models' | 'tools' | 'insights' | 'settings' | 'evaluation';
export type DocStatus = 'ready' | 'failed' | 'processing' | 'parsed';
export type ModelKind = 'LLM' | 'Embedding' | 'Rerank' | 'OCR' | 'Vision';
export type Provider = '通义千问' | 'OpenRouter' | 'AIHubMix';
export interface Chunk { id: string; title: string; text: string; kind: 'text' | 'table' | 'image'; page?: number; sheet?: string; imageUrl?:string; }
export type MetadataStatus = 'processing' | 'ready' | 'partial' | 'failed' | 'skipped' | 'stale';
export interface MetadataFact {value:string;label:string;chunkId:string;evidence:string;source?:'document'|'manual';}
export interface MetadataTerm {value:string;chunkIds:string[];source?:string;}
export interface MetadataPayload {dates:MetadataFact[];versions:MetadataFact[];subjects:MetadataFact[];owners:MetadataFact[];keywords:MetadataTerm[];questions:MetadataTerm[];}
export interface DocumentMetadata extends MetadataPayload {schemaVersion:number;status:MetadataStatus;method?:'llm'|'manual';revision?:string;sourceFingerprint:string;modelId?:string;modelName?:string;extractedAt?:string;updatedAt?:string;warnings?:string[];error?:string;batchesProcessed?:number;totalBatches?:number;reviewed?:boolean;}
export interface KnowledgeBase { id: string; name: string; description: string; color: string; tags: string[]; embeddingModelId: string; updatedAt: string; }
export interface DocumentRecord { id: string; kbId: string; name: string; type: string; size: string; pages: number; status: DocStatus; chunks: Chunk[]; createdAt: string; error?: string; enabled: boolean; indexMode?:'keyword'|'hybrid'; activeVersion?:string;indexStatus?:string; parseWarnings?:string[]; embeddingConfig?:ModelConfig|null; metadata?:DocumentMetadata;metadataStatus?:MetadataStatus;metadataError?:string;indexedMetadataRevision?:string;contentFingerprint?:string;lastMetadataModelId?:string; }
export interface ImportTask { id: string; kbId: string; docId: string; name: string; status: DocStatus; stage: string; progress: number; createdAt: string; error?: string; warnings?:string[]; action?:'parse'|'build'|'metadata';stages?:{name:string;duration:number;status:string}[]; }
export interface ProviderConfig { id: string; provider: Provider; name: string; baseUrl: string; hasKey: boolean; updatedAt?: string; credentialError?:string; }
export interface ModelConfig { providerConfigId?:string; id: string; provider: Provider; name: string; modelId: string; type: ModelKind; status: 'connected' | 'unconfigured' | 'failed'; baseUrl: string; dimensions?: number; isDefault: boolean; hasKey?:boolean; lastError?:string; }
export interface FlowNode {id:string;type:string;name:string;position?:{x:number;y:number};[key:string]:unknown;}
export interface FlowEdge {source:string;target:string;condition?:string;}
export interface AssistantConfig { type?:'simple'|'chatflow'|'agent'; runtimeSource?:'internal'|'external';runnerId?:string;toolIds?:string[];skillIds?:string[];flow?:{nodes:FlowNode[];edges:FlowEdge[]};publishedVersion?:string;maxSteps?:number;timeout?:number;asTool?:boolean; id: string; name: string; description: string; kbIds: string[]; modelId: string; welcome: string; examples: string[]; prompt: string; rerank: boolean; topK: number; }
export interface Citation { id: string; documentId: string; name: string; title: string; text: string; page?: number; sheet?: string; kind: 'text' | 'table' | 'image'; imageUrl?:string; score?:number; scoreType?:string; metadata?:Record<string,string[]>;suggestedQuestions?:string[]; }
export interface ChatMessage { id: string; role: 'user' | 'assistant'; content: string; createdAt: string; citations?: Citation[]; tokens?: number|null; duration?: number; traceId?: string; feedback?: 'up' | 'down'; stopped?: boolean; }
export interface ChatSession { id: string; assistantId: string; title: string; messages: ChatMessage[]; createdAt: string; }
export interface LogRecord { id: string; kind: 'chat' | 'model' | 'import'; question: string; answer: string; assistantId?: string; kbIds: string[]; model: string; provider: string; status: 'success' | 'failed' | 'stopped'; inputTokens: number|null; outputTokens: number|null; duration: number; firstToken: number|null; createdAt: string; citations: Citation[]; error?: string; stages: { name: string; duration: number; status: 'success' | 'failed' }[]; }
export interface WorkspaceState { providerConfigs: ProviderConfig[]; knowledgeBases: KnowledgeBase[]; documents: DocumentRecord[]; tasks: ImportTask[]; models: ModelConfig[]; assistants: AssistantConfig[]; sessions: ChatSession[]; logs: LogRecord[]; settings?:{allowExternalProcessing:boolean}; }
