import { useState } from 'react';
import { Alert, App, Button, Collapse, Empty, Form, Input, Modal, Select, Space, Tabs, Tag, Tooltip } from 'antd';
import { BookOpen, Plus, Sparkles, Trash2 } from 'lucide-react';
import { api } from './api';
import { formatTime, useWorkspace } from './store';
import type { DocumentRecord, MetadataFact, MetadataPayload, MetadataStatus } from './types';
import './metadata.css';

const facts = { dates: '时间', versions: '版本', subjects: '主体信息', owners: '负责人' } as const;
const statuses: Record<MetadataStatus, string> = { processing: '抽取中', ready: '已构建', partial: '部分完成', failed: '抽取失败', skipped: '已跳过', stale: '正文已变更' };
const empty = (): MetadataPayload => ({dates:[],versions:[],subjects:[],owners:[],keywords:[],questions:[]});
type EditorValues = Omit<MetadataPayload,'keywords'> & {keywordsText:string};

export function DocumentMetadataPanel({ document: doc, onBuild, readOnly: previewOnly = false }: { document: DocumentRecord; onBuild?:()=>void; readOnly?:boolean }) {
  const {state,role,refresh,flush,navigate} = useWorkspace();
  const {message} = App.useApp();
  const [editorOpen,setEditorOpen] = useState(false);
  const [extractOpen,setExtractOpen] = useState(false);
  const [saving,setSaving] = useState(false);
  const [submitting,setSubmitting] = useState(false);
  const [modelId,setModelId] = useState<string>();
  const [evidence,setEvidence] = useState<MetadataFact|null>(null);
  const [editingBase,setEditingBase] = useState<{revision?:string;sourceFingerprint?:string}>({});
  const [form] = Form.useForm<EditorValues>();
  const metadata = doc.metadata;
  const status = doc.metadataStatus ?? metadata?.status;
  const busy = doc.status==='processing' || doc.indexStatus==='processing' || status==='processing' || state.tasks.some(task=>task.docId===doc.id&&task.status==='processing');
  const llms = state.models.filter(model=>model.type==='LLM'&&model.modelId.trim()&&model.hasKey&&!state.providerConfigs.find(connection=>connection.id===model.providerConfigId)?.credentialError);
  const sourceOptions = doc.chunks.map((chunk,index)=>({value:chunk.id,label:`${index+1}. ${chunk.title}${chunk.page?` · 第${chunk.page}页`:chunk.sheet?` · ${chunk.sheet}`:''}`}));
  const selectedSource = doc.chunks.find(chunk=>chunk.id===evidence?.chunkId);
  const draft = !!metadata?.revision && metadata.revision!==doc.indexedMetadataRevision && ['ready','partial'].includes(metadata.status);
  const readOnly = previewOnly || role==='user';
  function openEditor(){
    const value=metadata??empty();
    form.resetFields();form.setFieldsValue({...value,keywordsText:value.keywords.map(term=>term.value).join('\n')});
    setEditingBase({revision:metadata?.revision,sourceFingerprint:doc.contentFingerprint??metadata?.sourceFingerprint});
    setEditorOpen(true);
  }
  function openExtraction(){
    setModelId(llms.find(model=>model.id===(doc.lastMetadataModelId??metadata?.modelId))?.id??llms.find(model=>model.isDefault&&model.status==='connected')?.id??llms.find(model=>model.status==='connected')?.id??llms.find(model=>model.isDefault)?.id??llms[0]?.id);
    setExtractOpen(true);
  }
  async function extract(){
    if(!modelId)return;setSubmitting(true);
    try{await flush();await api(`/api/documents/${doc.id}/metadata`,{method:'POST',body:JSON.stringify({modelId})});await refresh();setExtractOpen(false);message.success('元数据抽取已加入任务，完成后请核对并构建索引');}
    catch(error){message.error((error as Error).message);}finally{setSubmitting(false);}
  }
  async function save(){
    try{
      const values=await form.validateFields();setSaving(true);
      const keywords=Array.from(new Set(values.keywordsText.split('\n').map(value=>value.trim()).filter(Boolean))).map(value=>metadata?.keywords.find(item=>item.value===value)??{value,chunkIds:[]});
      if(keywords.length>40){message.warning('关键词最多40项，请精简后保存');return;}
      const payload:MetadataPayload={dates:values.dates??[],versions:values.versions??[],subjects:values.subjects??[],owners:values.owners??[],keywords,questions:values.questions??[]};
      await flush();await api(`/api/documents/${doc.id}/metadata`,{method:'PUT',body:JSON.stringify({payload,...editingBase})});await refresh();setEditorOpen(false);message.success(doc.activeVersion?'元数据已保存，正在更新已发布索引':'元数据已保存，确认后可构建索引');
    }catch(error){if(!(error as {errorFields?:unknown}).errorFields)message.error((error as Error).message);}finally{setSaving(false);}
  }
  const factEditor=(field:keyof typeof facts)=><Form.List name={field}>{(items,{add,remove})=><>
    {items.map(item=><div className="metadata-editor-row" key={item.key}>
      <div className="metadata-editor-main"><Form.Item name={[item.name,'value']} rules={[{required:true,whitespace:true,message:'请输入内容，或删除空白行'},{max:200}]}><Input aria-label={`${facts[field]}内容`} placeholder={facts[field]} maxLength={200}/></Form.Item><Form.Item name={[item.name,'label']}><Input aria-label={`${facts[field]}用途或角色`} placeholder={field==='dates'?'发布日期／生效时间等':field==='owners'?'责任角色／责任部门':'类型／修订说明'} maxLength={60}/></Form.Item><Button type="text" danger aria-label={`删除${facts[field]}项`} icon={<Trash2 size={14}/>} onClick={()=>remove(item.name)}/></div>
      <Form.Item name={[item.name,'chunkId']}><Select allowClear showSearch optionFilterProp="label" placeholder="关联原文分段（可选）" options={sourceOptions}/></Form.Item>
      <Form.Item name={[item.name,'evidence']}><Input.TextArea aria-label={`${facts[field]}原文依据`} rows={2} maxLength={500} placeholder="粘贴支持该值的原文；没有依据的人工补充会单独标明"/></Form.Item>
    </div>)}<Button icon={<Plus size={14}/>} onClick={()=>add({value:'',label:'',chunkId:'',evidence:''})}>添加{facts[field]}</Button>
  </>}</Form.List>;
  return <section className="document-metadata">
    <div className="metadata-heading"><div><h3><Sparkles size={17}/>文档元数据 {status&&<Tag color={status==='failed'?'error':status==='ready'?'green':status==='processing'?'processing':'gold'}>{statuses[status]}</Tag>}{draft&&<Tag color="blue">待发布索引</Tag>}</h3><p>结构化信息辅助检索，候选问题用于召回；回答依据仍是文档原文。</p></div>{!readOnly&&<Space wrap><Button size="small" disabled={!doc.chunks.length||busy} onClick={openEditor}>编辑元数据</Button><Button size="small" icon={<Sparkles size={13}/>} disabled={!doc.chunks.length||busy} onClick={openExtraction}>{metadata?'重新抽取':'抽取元数据'}</Button>{draft&&onBuild&&<Button size="small" type="primary" disabled={busy} onClick={onBuild}>构建索引</Button>}</Space>}</div>
    {(doc.metadataError||metadata?.error)&&<Alert type="warning" showIcon title="元数据抽取未完整完成，正文保留" description={doc.metadataError||metadata?.error} style={{marginBottom:14}}/>}
    {status==='stale'&&<Alert type="warning" showIcon title="正文已修改，旧元数据暂停进入新索引" description="请重新抽取或编辑核对后保存，避免旧版本信息影响召回。" style={{marginBottom:14}}/>}
    {status==='skipped'&&<Alert type="info" showIcon title="导入时未启用自动元数据抽取" description="可使用已配置的LLM补抽，或直接在本机人工填写。" style={{marginBottom:14}}/>}
    {status==='processing'&&<Alert type="info" showIcon title="正在按原文分批抽取元数据" description="任务完成后自动展示结果；可在导入任务中查看阶段。" style={{marginBottom:14}}/>}
    {!metadata&&status!=='processing'&&<Alert type="info" showIcon title="尚无元数据" description="可使用已配置的 LLM 自动抽取，也可直接人工填写；已有文档无需重新上传。" style={{marginBottom:14}}/>}
    <div className="metadata-fact-grid">{Object.entries(facts).map(([field,label])=><div className="metadata-fact-card" key={field}><strong>{label}</strong>{metadata?.[field as keyof typeof facts]?.length?<ul>{metadata[field as keyof typeof facts].map((fact,index)=><li key={index}><span>{fact.value}<small>{fact.label}</small></span>{fact.source==='manual'?<Tag>人工补充</Tag>:<Tooltip title={fact.evidence}><Button size="small" type="text" aria-label={`查看${fact.value}的原文依据`} icon={<BookOpen size={13}/>} onClick={()=>setEvidence(fact)}/></Tooltip>}</li>)}</ul>:<p className="muted">{status==='ready'||status==='partial'?'本次未提取到明确值':'尚未提取'}</p>}</div>)}</div>
    <div className="metadata-keywords"><strong>检索关键词</strong><div>{metadata?.keywords?.length?metadata.keywords.map(term=><Tag key={term.value} color="blue">{term.value}</Tag>):<span className="muted">暂无关键词</span>}</div></div>
    <Collapse size="small" items={[{key:'questions',label:`候选问题 · ${metadata?.questions?.length??0} 项（辅助召回）`,children:metadata?.questions?.length?<ol className="metadata-questions">{metadata.questions.map((term,index)=><li key={index}>{term.value}<small>{term.chunkIds.length?`关联 ${term.chunkIds.length} 个原文分段`:'人工补充'}</small></li>)}</ol>:<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无候选问题"/>}]}/>
    {!!metadata?.warnings?.length&&<Alert type="warning" showIcon title="抽取范围提醒" description={<ul>{metadata.warnings.map((warning,index)=><li key={index}>{warning}</li>)}</ul>} style={{marginTop:12}}/>}
    {(metadata?.method||metadata?.totalBatches!==undefined)&&<p className="metadata-footnote">{metadata.method==='manual'?'人工核对保存':metadata.modelName?`抽取模型：${metadata.modelName}`:'自动抽取'}{metadata.totalBatches!==undefined?` · 完成 ${metadata.batchesProcessed??0}/${metadata.totalBatches} 批`:''}{metadata.updatedAt||metadata.extractedAt?` · ${formatTime((metadata.updatedAt||metadata.extractedAt)!)}`:''}</p>}

    <Modal open={extractOpen} title="自动抽取文档元数据" onCancel={()=>!submitting&&setExtractOpen(false)} onOk={()=>void extract()} okText="开始抽取" cancelText="取消" confirmLoading={submitting} okButtonProps={{disabled:!modelId||!state.settings?.allowExternalProcessing}} width={590} destroyOnHidden>
      <p>{doc.name}</p><Alert type="info" showIcon title="使用已配置的 LLM，无需新增密钥" description="会将解析后的正文分批发送给所选服务商并产生对应调用用量；只提取有原文依据的信息。长文档最多32批、每批约8000字，超出范围会明确标为部分完成。"/>
      {!state.settings?.allowExternalProcessing&&<Alert type="warning" showIcon title="管理员尚未允许云端资料处理" style={{marginTop:14}}/>}
      <label className="metadata-field-label">元数据抽取模型</label><Select aria-label="选择元数据抽取模型" value={modelId} onChange={setModelId} placeholder="选择已配置的 LLM" style={{width:'100%'}} options={llms.map(model=>({value:model.id,label:`${model.name} · ${model.provider}${model.status==='failed'?' · 上次调用异常':''}`}))}/>
      {!llms.length&&<p className="muted">请管理员先连接一个可用 LLM。元数据也可在本机人工填写。</p>}{role==='admin'&&<Button type="link" onClick={()=>{setExtractOpen(false);navigate('models');}}>管理模型服务</Button>}
    </Modal>
    <Modal open={editorOpen} title="核对与编辑文档元数据" width={760} onCancel={()=>!saving&&setEditorOpen(false)} onOk={()=>void save()} okText="保存元数据" cancelText="取消" confirmLoading={saving} destroyOnHidden>
      <Alert type="info" showIcon title="缺失信息可留空，候选问题需关联可回答它的原文" description={doc.activeVersion?'保存后会重建当前索引，发布前保留旧版本。没有原文依据的事实字段会标为人工补充。':'保存后返回预览，确认构建索引后用于检索。没有原文依据的事实字段会标为人工补充。'} style={{marginBottom:16}}/>
      <Form form={form} layout="vertical" preserve>
        <Tabs items={[...Object.entries(facts).map(([field,label])=>({key:field,label,forceRender:true,children:factEditor(field as keyof typeof facts)})),{key:'keywords',label:'关键词',forceRender:true,children:<Form.Item name="keywordsText" label="便于检索的关键词（每行一项，最多40项）"><Input.TextArea rows={10} maxLength={6000}/></Form.Item>},{key:'questions',label:'候选问题',forceRender:true,children:<Form.List name="questions">{(items,{add,remove})=><>{items.map(item=><div className="metadata-editor-row" key={item.key}><div className="metadata-editor-main"><Form.Item name={[item.name,'value']} rules={[{required:true,whitespace:true,message:'请输入问题'},{max:250}]}><Input.TextArea rows={2} placeholder="使用者可能问的问题" maxLength={250}/></Form.Item><Button type="text" danger aria-label="删除候选问题" icon={<Trash2 size={14}/>} onClick={()=>remove(item.name)}/></div><Form.Item name={[item.name,'chunkIds']} rules={[{required:true,type:'array',min:1,message:'请关联至少一个可回答该问题的原文分段'}]}><Select mode="multiple" maxCount={12} showSearch optionFilterProp="label" placeholder="关联可回答该问题的原文分段" options={sourceOptions}/></Form.Item></div>)}<Button icon={<Plus size={14}/>} disabled={items.length>=30} onClick={()=>add({value:'',chunkIds:[]})}>添加候选问题</Button></>}</Form.List>}]}/>
      </Form>
    </Modal>
    <Modal open={!!evidence} title="元数据原文依据" onCancel={()=>setEvidence(null)} footer={<Button onClick={()=>setEvidence(null)}>关闭</Button>} width={650} destroyOnHidden>{evidence&&<><p><strong>{evidence.label} {evidence.value}</strong></p><blockquote className="metadata-evidence">{evidence.evidence}</blockquote>{selectedSource&&<>{selectedSource.imageUrl&&<><Alert type="info" showIcon title="此依据包含OCR或图片理解结果，请结合原图核对"/><figure><img style={{maxWidth:'100%',maxHeight:360,objectFit:'contain'}} src={selectedSource.imageUrl} alt="元数据依据对应原图"/></figure></>}<p className="muted">{selectedSource.title}{selectedSource.page?` · 第${selectedSource.page}页`:selectedSource.sheet?` · ${selectedSource.sheet}`:''}</p><pre className="metadata-source">{selectedSource.text.slice(0,10000)}</pre></>}<Button href={`/api/documents/${doc.id}/file${selectedSource?.page?`#page=${selectedSource.page}`:''}`} target="_blank" rel="noopener noreferrer">打开原始文件</Button></>}</Modal>
  </section>;
}
