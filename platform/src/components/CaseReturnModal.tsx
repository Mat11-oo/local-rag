import { ThumbsDown, ThumbsUp } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { errorMessage, type ApiEvaluationSet } from '../api/client';
import { evalApi, splitList } from '../api/evaluation';
import { Field, Modal, Notice, Spinner, useToast } from './ui';

export type CaseReturn = { traceIds: string[]; appId: string; appName: string | null; type: 'good' | 'bad' };

/** 把线上 Trace 回流为评测集 Case。评测集与应用绑定，只能回流同一应用的 Trace。 */
export function CaseReturnModal({ value, onClose, onDone }: { value: CaseReturn | null; onClose: () => void; onDone?: () => void }) {
  const toast = useToast();
  const navigate = useNavigate();
  const [sets, setSets] = useState<ApiEvaluationSet[] | null>(null);
  const [type, setType] = useState<'good' | 'bad'>('bad');
  const [target, setTarget] = useState('');
  const [newName, setNewName] = useState('');
  const [tags, setTags] = useState('线上回流');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!value) return;
    setType(value.type);
    setSets(null);
    evalApi.list(value.appId).then((list) => { setSets(list); setTarget(list[0]?.id ?? '__new__'); setNewName(`${value.appName ?? '应用'}回归集`); }).catch((caught) => toast(errorMessage(caught), 'error'));
  }, [value, toast]);

  const submit = async () => {
    if (!value) return;
    setBusy(true);
    try {
      let setId = target;
      if (target === '__new__') setId = (await evalApi.create({ app_id: value.appId, name: newName.trim(), description: '由线上日志回流创建' })).id;
      const result = await evalApi.fromLogs(setId, { trace_ids: value.traceIds, case_type: type, tags: splitList(tags) });
      toast(`已回流 ${result.created_count} 条 ${type === 'good' ? 'Good' : 'Bad'} Case`);
      onDone?.();
      onClose();
      if (type === 'bad') navigate(`/evaluation-sets?set=${setId}`);
    } catch (caught) {
      toast(errorMessage(caught), 'error');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={!!value} title={`回流 ${value?.traceIds.length ?? 0} 条线上 Case`} onClose={onClose}
      footer={<><button className="btn" onClick={onClose}>取消</button><button className="btn primary" disabled={busy || !sets || (target === '__new__' && !newName.trim())} onClick={() => void submit()}>{busy ? <Spinner /> : null}确认回流</button></>}>
      <div className="case-type-picker">
        <button type="button" className={type === 'good' ? 'active good' : ''} onClick={() => setType('good')}><ThumbsUp size={18} /><span><strong>Good Case</strong><small>线上结果已确认正确，作为参考答案</small></span></button>
        <button type="button" className={type === 'bad' ? 'active bad' : ''} onClick={() => setType('bad')}><ThumbsDown size={18} /><span><strong>Bad Case</strong><small>线上结果有问题，需要补充期望标准</small></span></button>
      </div>
      <Field label="目标评测集" required hint={`仅显示「${value?.appName ?? ''}」的评测集`}>
        <select className="select" value={target} onChange={(event) => setTarget(event.target.value)}>
          {sets?.map((set) => <option key={set.id} value={set.id}>{set.name}（{set.case_count} 条）</option>)}
          <option value="__new__">+ 新建评测集</option>
        </select>
      </Field>
      {target === '__new__' ? <Field label="新评测集名称" required><input className="input" value={newName} onChange={(event) => setNewName(event.target.value)} /></Field> : null}
      <Field label="标签" hint="逗号分隔"><input className="input" value={tags} onChange={(event) => setTags(event.target.value)} /></Field>
      {type === 'bad' ? <Notice tone="warn">Bad Case 回流后为「待补标准」，补齐期望输出或判定规则后才会参与自动评测；在此之前不影响评测运行和发布门禁。</Notice> : null}
    </Modal>
  );
}
