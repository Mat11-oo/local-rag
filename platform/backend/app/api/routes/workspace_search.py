"""Bounded, workspace-scoped resource search without model calls."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from ...db import get_session
from ...models import AppVersion, KnowledgeBase, KnowledgeFile, QAApp
from ...security import AuthContext, require_roles

router = APIRouter()


@router.get('')
async def search(q: str = Query(default='', max_length=120),
                 context: AuthContext = Depends(require_roles('admin', 'manager', 'user')),
                 session: AsyncSession = Depends(get_session)) -> dict:
    term = q.strip()
    if not term:
        return {'items': []}
    pattern = '%' + term.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
    results = []
    scopes = context.scopes or frozenset()
    def may_read(namespace):
        return context.auth_type != 'api_client' or bool({namespace+':read', namespace+':*', '*'} & scopes)
    if may_read('apps'):
        if context.role == 'user':
            rows = (await session.execute(select(QAApp, AppVersion).join(AppVersion, AppVersion.id == QAApp.published_version_id).where(QAApp.workspace_id == context.workspace_id, QAApp.is_enabled.is_(True), AppVersion.manifest['name'].as_string().ilike(pattern, escape='\\')).limit(10))).all()
            for app, version in rows:
                name = version.manifest.get('name', app.name)
                if term.casefold() in name.casefold():
                    results.append({'id': app.id, 'kind': 'app', 'name': name, 'path': f'/chat/{app.id}'})
        else:
            rows = await session.scalars(select(QAApp).where(QAApp.workspace_id == context.workspace_id, or_(QAApp.name.ilike(pattern, escape='\\'), QAApp.description.ilike(pattern, escape='\\'))).order_by(QAApp.updated_at.desc()).limit(10))
            results += [{'id': app.id, 'kind': 'app', 'name': app.name, 'path': f'/apps/{app.id}'} for app in rows]
    if context.role != 'user' and may_read('knowledge'):
        bases = await session.scalars(select(KnowledgeBase).where(KnowledgeBase.workspace_id == context.workspace_id, KnowledgeBase.name.ilike(pattern, escape='\\')).order_by(KnowledgeBase.updated_at.desc()).limit(10))
        results += [{'id': kb.id, 'kind': 'knowledge', 'name': kb.name, 'path': f'/knowledge/{kb.id}'} for kb in bases]
        files = await session.scalars(select(KnowledgeFile).join(KnowledgeBase).where(KnowledgeBase.workspace_id == context.workspace_id, KnowledgeFile.filename.ilike(pattern, escape='\\')).order_by(KnowledgeFile.updated_at.desc()).limit(10))
        results += [{'id': file.id, 'kind': 'file', 'name': file.filename, 'path': f'/knowledge/{file.knowledge_base_id}/files/{file.id}'} for file in files]
    return {'items': results[:30]}
