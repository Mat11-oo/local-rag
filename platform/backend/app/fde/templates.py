from __future__ import annotations

from typing import Any

from pydantic import Field

from .manifest import Delivery, FDEModel, Guardrails, InputField, Manifest, Memory, OutputSpec, Tool


class KnowledgeBaseRule(FDEModel):
    required: bool = False
    min_items: int = Field(default=0, ge=0, le=20)
    max_items: int = Field(default=20, ge=1, le=20)


class AppTemplate(FDEModel):
    key: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=180)
    description: str = Field(min_length=1, max_length=4000)
    icon: str = Field(min_length=1, max_length=80)
    system_prompt: str = Field(min_length=1, max_length=12000)
    input_fields: list[InputField] = Field(min_length=1, max_length=30)
    output: OutputSpec
    knowledge_bases: KnowledgeBaseRule = Field(default_factory=KnowledgeBaseRule)
    tools: list[Tool] = Field(default_factory=list, max_length=10)
    guardrails: Guardrails = Field(default_factory=Guardrails)
    memory: Memory = Field(default_factory=Memory)
    delivery: Delivery = Field(default_factory=Delivery)


_TEMPLATES = [
    AppTemplate(
        key="qa",
        name="知识库问答",
        description="基于企业知识库回答问题，并提供可追溯的引用。",
        icon="MessageCircleQuestion",
        system_prompt="你是企业知识助手。仅依据检索到的知识回答；信息不足时明确说明，不要编造，并标注来源。",
        input_fields=[
            InputField(key="question", label="问题", type="textarea", placeholder="请输入需要查询的问题")
        ],
        output=OutputSpec(format="markdown"),
        knowledge_bases=KnowledgeBaseRule(required=True, min_items=1),
        tools=[Tool(name="knowledge_retrieval")],
        guardrails=Guardrails(require_citations=True, refuse_without_evidence=True),
        delivery=Delivery(show_citations=True),
    ),
    AppTemplate(
        key="content",
        name="通用内容创作",
        description="面向产品、活动、特色菜等主题生成适配不同渠道的内容，无需知识库。",
        icon="PenLine",
        system_prompt="你是内容创作助手。根据用户提供的主题、素材、卖点、渠道和语气生成真实、清晰、有吸引力的内容，不虚构事实。",
        input_fields=[
            InputField(
                key="dish_name",
                label="菜品名 / 内容主体",
                placeholder="例如：招牌菜、产品、活动或品牌主题",
            ),
            InputField(
                key="ingredients_taste",
                label="食材口味 / 材料特点",
                type="textarea",
                required=False,
                description="可填写食材与口味，也可填写其他产品的材料、功能或体验特点。",
            ),
            InputField(key="selling_points", label="核心卖点", type="textarea"),
            InputField(
                key="channel",
                label="发布渠道",
                type="select",
                options=["公众号", "小红书", "短视频", "海报", "官网", "其他"],
                default="公众号",
            ),
            InputField(
                key="tone",
                label="内容语气",
                type="select",
                options=["专业", "亲切", "活泼", "高级", "朴实"],
                default="亲切",
            ),
            InputField(key="word_count", label="目标字数", type="number", minimum=50, maximum=10000, default=800),
            InputField(key="audience", label="目标受众", required=False, default="大众消费者"),
        ],
        output=OutputSpec(format="markdown"),
        knowledge_bases=KnowledgeBaseRule(required=False),
        guardrails=Guardrails(blocked_topics=["虚假功效", "绝对化宣传"], max_output_chars=15000),
        memory=Memory(enabled=False),
        delivery=Delivery(allow_export=True),
    ),
    AppTemplate(
        key="report",
        name="结构化报告",
        description="根据主题、受众和结构要求生成报告，可选择结合知识库补充依据。",
        icon="FileChartColumn",
        system_prompt="你是报告写作助手。围绕主题和目标受众，按指定结构组织内容，区分事实、推断和建议，不编造数据。",
        input_fields=[
            InputField(key="topic", label="报告主题", type="textarea"),
            InputField(key="audience", label="目标受众"),
            InputField(
                key="structure",
                label="报告结构",
                type="textarea",
                default="摘要\n背景与现状\n核心分析\n结论与建议",
            ),
            InputField(key="word_count", label="目标字数", type="number", minimum=100, maximum=30000, default=2000),
        ],
        output=OutputSpec(format="markdown"),
        knowledge_bases=KnowledgeBaseRule(required=False),
        tools=[Tool(name="knowledge_retrieval")],
        guardrails=Guardrails(max_output_chars=30000),
        delivery=Delivery(show_citations=True, allow_export=True),
    ),
    AppTemplate(
        key="review",
        name="知识审校",
        description="依据知识库检查内容的事实一致性、遗漏和表达风险。",
        icon="ClipboardCheck",
        system_prompt="你是内容审校助手。以知识库为依据逐项检查待审内容，指出问题、依据和修改建议；没有依据时不要断言。",
        input_fields=[
            InputField(key="content_to_review", label="待审内容", type="textarea"),
            InputField(
                key="review_focus",
                label="审校重点",
                type="select",
                options=["事实准确性", "合规风险", "完整性", "综合审校"],
                default="综合审校",
            ),
        ],
        output=OutputSpec(format="markdown"),
        knowledge_bases=KnowledgeBaseRule(required=True, min_items=1),
        tools=[Tool(name="knowledge_retrieval")],
        guardrails=Guardrails(require_citations=True, refuse_without_evidence=True),
        delivery=Delivery(show_citations=True, allow_export=True),
    ),
    AppTemplate(
        key="customer_service",
        name="智能客服",
        description="结合服务知识库回答客户问题，并在低置信或敏感场景转接人工。",
        icon="Headphones",
        system_prompt="你是客服助手。依据服务知识库准确、简洁地回答问题；涉及投诉升级、退款争议、人身财产安全或知识不足时，说明需要人工处理并发起转接。",
        input_fields=[
            InputField(key="customer_question", label="客户问题", type="textarea"),
            InputField(key="order_context", label="订单或服务背景", type="textarea", required=False),
            InputField(
                key="customer_tier",
                label="客户类型",
                type="select",
                options=["普通客户", "会员客户", "企业客户"],
                default="普通客户",
                required=False,
            ),
        ],
        output=OutputSpec(format="markdown"),
        knowledge_bases=KnowledgeBaseRule(required=True, min_items=1),
        tools=[Tool(name="knowledge_retrieval"), Tool(name="human_handoff")],
        guardrails=Guardrails(
            blocked_topics=["未经核实的赔偿承诺"],
            require_citations=True,
            refuse_without_evidence=True,
            human_handoff=True,
        ),
        delivery=Delivery(show_citations=True),
    ),
]

TEMPLATES: dict[str, AppTemplate] = {template.key: template for template in _TEMPLATES}
LEGACY_SCENARIO_TEMPLATE_KEYS = {
    "qa": "qa",
    "report": "report",
    "content": "content",
    "review": "review",
}


def list_templates() -> list[AppTemplate]:
    return [template.model_copy(deep=True) for template in _TEMPLATES]


def get_template(template_key: str) -> AppTemplate | None:
    template = TEMPLATES.get(template_key)
    return template.model_copy(deep=True) if template else None


def require_template(template_key: str) -> AppTemplate:
    template = get_template(template_key)
    if template is None:
        raise KeyError(f"Unknown FDE template: {template_key}")
    return template


def create_manifest(template_key: str, **overrides: Any) -> Manifest:
    template = require_template(template_key)
    values: dict[str, Any] = {
        "name": overrides.pop("name", template.name),
        "description": overrides.pop("description", template.description),
        "template_key": template.key,
        "system_prompt": overrides.pop("system_prompt", template.system_prompt),
        "input_fields": overrides.pop("input_fields", template.input_fields),
        "output": overrides.pop("output", template.output),
        "tools": overrides.pop("tools", template.tools),
        "guardrails": overrides.pop("guardrails", template.guardrails),
        "memory": overrides.pop("memory", template.memory),
        "delivery": overrides.pop("delivery", template.delivery),
    }
    values.update(overrides)
    return Manifest.model_validate(values)
