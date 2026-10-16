from app.ai.chains.prompt_template import raw_prompt


def test_langchain_template_preserves_quoted_evidence_and_literal_braces():
    source = "O'Reilly & Sons shall pay <fees> within 30 days. {{IGNORE_ME}}"
    template = raw_prompt("Evidence: {{CONTRACT_TEXT}}", "CONTRACT_TEXT")
    rendered = template.format(CONTRACT_TEXT=source)
    assert rendered == f"Evidence: {source}"


def test_question_and_context_are_rendered_once_as_untrusted_text():
    question = "What does {{CONTEXT}} mean?"
    context = "The contract says {{QUESTION}} is only source text."
    template = raw_prompt("Q={{QUESTION}}\nC={{CONTEXT}}", "QUESTION", "CONTEXT")
    assert template.format(QUESTION=question, CONTEXT=context) == (
        f"Q={question}\nC={context}"
    )
