from app.llm.prompt_manager import prompt_template_manager


def load_prompt(name: str) -> str:
    return prompt_template_manager.load_template(name)
