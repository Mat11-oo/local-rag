import { Alert } from 'antd';

export function ParsingNotice({ warnings }: { warnings?: string[] }) {
  if (!warnings?.length) return null;
  return <Alert type="warning" showIcon title="请核对解析覆盖范围" style={{ margin: '12px 0' }}
    description={<ul style={{ margin: 0, paddingInlineStart: 18 }}>{warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul>} />;
}
