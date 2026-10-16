"""Render trusted prompt templates while leaving contract evidence verbatim."""

from langchain_core.prompts import PromptTemplate


def raw_prompt(template: str, *variables: str) -> PromptTemplate:
    # Mustache's double braces HTML-escape text. Triple braces preserve exact
    # contract quotes, which are validated against the stored source later.
    for name in variables:
        marker = "{{" + name + "}}"
        template = template.replace(marker, "{{{" + name + "}}}")
    return PromptTemplate.from_template(template, template_format="mustache")
