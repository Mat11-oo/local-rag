import {
  AlertCircle, BookOpen, Bot, CheckCircle2, Headset, Info, LoaderCircle, Megaphone, MessageSquare, NotebookPen, PenLine,
  ShieldCheck, Sparkles, TriangleAlert, X, type LucideIcon,
} from 'lucide-react';
import { createContext, useCallback, useContext, useEffect, useRef, useState, type PropsWithChildren, type ReactNode, useId, cloneElement, isValidElement, type HTMLAttributes } from 'react';

/* -------- 应用图标：按模板 / 类型选择，保证同类应用在各页面一致 -------- */

const TEMPLATE_ICON: Record<string, [LucideIcon, string]> = {
  qa: [BookOpen, '#7a5af8'],
  content: [PenLine, '#dd2590'],
  report: [NotebookPen, '#3370ff'],
  review: [ShieldCheck, '#f79009'],
  customer_service: [Headset, '#12b76a'],
  marketing: [Megaphone, '#dd2590'],
};

export function appVisual(templateKey: string | undefined, type?: string): [LucideIcon, string] {
  if (templateKey && TEMPLATE_ICON[templateKey]) return TEMPLATE_ICON[templateKey];
  return type === 'agent' ? [Bot, '#0e9384'] : [MessageSquare, '#3370ff'];
}

export function AppTile({ templateKey, type, size = 'md' }: { templateKey?: string; type?: string; size?: 'sm' | 'md' | 'lg' }) {
  const [Icon, color] = appVisual(templateKey, type);
  const px = size === 'sm' ? 15 : size === 'lg' ? 22 : 19;
  return <span className={`avatar-tile ${size === 'md' ? '' : size}`} style={{ background: color }}><Icon size={px} aria-hidden="true" /></span>;
}

export function Tag({ tone = '', children, title }: PropsWithChildren<{ tone?: string; title?: string }>) {
  return <span className={`tag ${tone}`} title={title}>{children}</span>;
}

export function Switch({ on, onChange, label, disabled }: { on: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean }) {
  return <button type="button" role="switch" aria-checked={on} aria-label={label} disabled={disabled} className={`switch ${on ? 'on' : ''}`} onClick={() => onChange(!on)} />;
}

export function Spinner({ size = 16 }: { size?: number }) {
  return <LoaderCircle size={size} className="spin" aria-hidden="true" />;
}

export function Notice({ tone = 'info', title, children, action }: PropsWithChildren<{ tone?: 'info' | 'warn' | 'error' | 'success'; title?: ReactNode; action?: ReactNode }>) {
  const Icon = tone === 'error' ? AlertCircle : tone === 'warn' ? TriangleAlert : tone === 'success' ? CheckCircle2 : Info;
  return (
    <div className={`notice ${tone}`} role={tone === 'error' ? 'alert' : undefined}>
      <Icon size={16} aria-hidden="true" />
      <div className="grow">{title ? <strong style={{ display: 'block' }}>{title}</strong> : null}{children}</div>
      {action}
    </div>
  );
}

export function Loading({ text = '加载中' }: { text?: string }) {
  return <div className="empty" aria-busy="true"><Spinner size={22} /><span>{text}</span></div>;
}

/* -------- Toast -------- */

type ToastTone = 'info' | 'error';
const ToastCtx = createContext<(text: string, tone?: ToastTone) => void>(() => undefined);

export function ToastProvider({ children }: PropsWithChildren) {
  const [items, setItems] = useState<{ id: number; text: string; tone: ToastTone }[]>([]);
  const show = useCallback((text: string, tone: ToastTone = 'info') => {
    const id = Date.now() + Math.random();
    setItems((list) => [...list, { id, text, tone }]);
    window.setTimeout(() => setItems((list) => list.filter((i) => i.id !== id)), tone === 'error' ? 5000 : 2600);
  }, []);
  return (
    <ToastCtx.Provider value={show}>
      {children}
      <div className="toast-wrap" aria-live="polite">{items.map((i) => <div className={`toast ${i.tone === 'error' ? 'toast-error' : ''}`} key={i.id}>{i.tone === 'error' ? <AlertCircle size={15} /> : null}{i.text}</div>)}</div>
    </ToastCtx.Provider>
  );
}

export const useToast = () => useContext(ToastCtx);

/* -------- Modal / Drawer -------- */

function useEscape(open: boolean, onClose: () => void, ref: {current: HTMLElement | null}) {
  useEffect(() => {
    if (!open) return undefined;
    const handler = (e: KeyboardEvent) => {
      const dialogs=document.querySelectorAll('[role="dialog"][aria-modal="true"]');
      if(e.key === 'Escape' && dialogs[dialogs.length-1] === ref.current) {e.preventDefault();onClose();}
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [open, onClose, ref]);
}

function useDialogFocus(open: boolean) {
  const lastOutside=useRef<HTMLElement|null>(null);
  useEffect(()=>{
    const track=(event:FocusEvent)=>{const target=event.target;if(target instanceof HTMLElement&&!target.closest('[role="dialog"]'))lastOutside.current=target;};
    document.addEventListener('focusin',track,true);return()=>document.removeEventListener('focusin',track,true);
  },[]);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open || !ref.current) return;
    const current=document.activeElement as HTMLElement|null;
    const previous=lastOutside.current??(current?.closest('[role="dialog"]')?null:current);
    const node = ref.current;
    const selector = 'button:not(:disabled),a[href],input:not(:disabled),select:not(:disabled),textarea:not(:disabled),[tabindex="0"]';
    const focusables = () => Array.from(node.querySelectorAll<HTMLElement>(selector)).filter(el => !el.hidden && el.getAttribute('aria-hidden') !== 'true' && el.getClientRects().length>0);
    (focusables()[0] ?? node).focus();
    const trap = (event: KeyboardEvent) => {
      if (event.key !== 'Tab') return;
      const dialogs = document.querySelectorAll('[role="dialog"][aria-modal="true"]');
      if (dialogs[dialogs.length - 1] !== node) return;
      const items = focusables();
      const first = items[0]; const last = items.at(-1);
      if (!first) {event.preventDefault(); node.focus();}
      else if (event.shiftKey && (document.activeElement === first || !node.contains(document.activeElement))) {event.preventDefault(); last?.focus();}
      else if (!event.shiftKey && (document.activeElement === last || !node.contains(document.activeElement))) {event.preventDefault(); first.focus();}
    };
    document.addEventListener('keydown', trap);
    return () => {document.removeEventListener('keydown', trap); if(previous?.isConnected) previous.focus();};
  }, [open]);
  return ref;
}

export function Modal({ open, title, onClose, children, footer, wide, icon }: PropsWithChildren<{ open: boolean; title: string; onClose: () => void; footer?: ReactNode; wide?: boolean; icon?: ReactNode }>) {
  const ref = useDialogFocus(open);
  useEscape(open, onClose, ref);
  if (!open) return null;
  return (
    <div className="overlay modal-layer" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className={`modal ${wide ? 'wide' : ''}`} role="dialog" aria-modal="true" aria-label={title} tabIndex={-1} ref={ref}>
        <div className="modal-head">{icon}<h3>{title}</h3><button className="btn ghost sm icon" aria-label="关闭" onClick={onClose}><X size={16} /></button></div>
        <div className="modal-body">{children}</div>
        {footer ? <div className="modal-foot">{footer}</div> : null}
      </div>
    </div>
  );
}

export function Drawer({ open, title, onClose, children, footer, wide }: PropsWithChildren<{ open: boolean; title: ReactNode; onClose: () => void; footer?: ReactNode; wide?: boolean }>) {
  const ref = useDialogFocus(open);
  useEscape(open, onClose, ref);
  if (!open) return null;
  return (
    <>
      <div className="overlay" style={{ background: 'rgba(16,24,40,.18)' }} onMouseDown={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-label={typeof title === 'string' ? title : '详情'} ref={ref} tabIndex={-1} style={wide ? { width: 'min(880px, 100vw)' } : undefined}>
        <div className="modal-head" style={{ borderBottom: '1px solid var(--border)', paddingBottom: 14 }}><h3>{title}</h3><button className="btn ghost sm icon" aria-label="关闭" onClick={onClose}><X size={16} /></button></div>
        <div className="modal-body" style={{ flex: 1, paddingTop: 16 }}>{children}</div>
        {footer ? <div className="modal-foot">{footer}</div> : null}
      </aside>
    </>
  );
}

export function Field({ label, required, hint, children }: PropsWithChildren<{ label: ReactNode; required?: boolean; hint?: ReactNode }>) {
  const id = useId(); const hintId = `${id}-hint`;
  const linked = isValidElement<HTMLAttributes<HTMLElement> & {id?: string; required?: boolean}>(children) && typeof children.type === 'string' && ['input','textarea','select'].includes(children.type);
  const inputId = linked ? children.props.id ?? id : id;
  const groupRef=useRef<HTMLDivElement>(null);
  useEffect(()=>{if(linked)return;const controls=groupRef.current?.querySelectorAll('input,select,textarea');controls?.forEach(control=>{if(!control.getAttribute('aria-label')&&!control.getAttribute('aria-labelledby'))control.setAttribute('aria-labelledby',`${id}-label`);if(hint)control.setAttribute('aria-describedby',hintId);});},[linked,id,hint,hintId,children]);
  return <div className="form-item">
    <label id={`${id}-label`} className="field-label" htmlFor={linked?inputId:undefined}>{label}{required ? <span className="req">*</span> : null}{hint ? <span className="hint" id={hintId}>{hint}</span> : null}</label>
    {linked ? cloneElement(children, {id:inputId, 'aria-required': required || undefined, 'aria-describedby': hint ? hintId : undefined}) : <div ref={groupRef} role="group" aria-label={typeof label === 'string' ? label : undefined}>{children}</div>}
  </div>;
}

export function Slider({ value, min, max, step = 1, onChange, suffix, label }: { value: number; min: number; max: number; step?: number; onChange: (v: number) => void; suffix?: string; label?: string }) {
  return (
    <div className="slider-row">
      <input className="range" type="range" aria-label={label} min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} />
      <div className="row" style={{ flex: 'none' }}>
        <input className="input sm" type="number" aria-label={label} min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} />
        {suffix ? <span className="faint">{suffix}</span> : null}
      </div>
    </div>
  );
}

export function Empty({ icon, title, desc, action }: { icon?: ReactNode; title: string; desc?: string; action?: ReactNode }) {
  return <div className="empty">{icon ?? <Sparkles size={24} />}<strong style={{ color: 'var(--text-1)' }}>{title}</strong>{desc ? <span>{desc}</span> : null}{action}</div>;
}

export function ConfirmModal({ open, title, body, confirmText = '确认', danger, onConfirm, onClose }: { open: boolean; title: string; body: ReactNode; confirmText?: string; danger?: boolean; onConfirm: () => void | Promise<void>; onClose: () => void }) {
  const [busy, setBusy] = useState(false);
  return (
    <Modal open={open} title={title} onClose={onClose} footer={<><button className="btn" onClick={onClose}>取消</button><button className={`btn ${danger ? 'danger-solid' : 'primary'}`} disabled={busy} onClick={async () => { setBusy(true); try { await onConfirm(); onClose(); } finally { setBusy(false); } }}>{busy ? <Spinner /> : null}{confirmText}</button></>}>
      <div className="muted">{body}</div>
    </Modal>
  );
}

/* -------- 格式化 -------- */

export function formatTime(value: string | null | undefined) {
  if (!value) return '—';
  const date = new Date(value);
  const now = new Date();
  const sameDay = date.toDateString() === now.toDateString();
  return new Intl.DateTimeFormat('zh-CN', sameDay ? { hour: '2-digit', minute: '2-digit', second: '2-digit' } : { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(date);
}

export function formatDuration(ms: number | null | undefined) {
  if (ms == null) return '—';
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(2)}s`;
  return `${Math.floor(ms / 60000)}m ${Math.round((ms % 60000) / 1000)}s`;
}

export function formatTokens(n: number | null | undefined) {
  if (n == null) return '—';
  return n >= 1000000 ? `${(n / 1000000).toFixed(2)}M` : n >= 10000 ? `${(n / 1000).toFixed(1)}K` : n.toLocaleString();
}

export function formatCost(value: number | null | undefined, currency = 'USD') {
  if (value == null) return '未计价';
  const symbol = currency === 'CNY' ? '¥' : '$';
  return `${symbol}${value < 0.01 ? value.toFixed(5) : value < 10 ? value.toFixed(4) : value.toFixed(2)}`;
}

export function formatBytes(size: number) {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}
