from app.llm.prompt_manager import PromptTemplateManager


def test_prompt_manager_metadata_render_and_hash(tmp_path):
    prompt = tmp_path / "hello.prompt"
    prompt.write_text("Hello {name}, today is {date}.", encoding="utf-8")
    manager = PromptTemplateManager(prompt_dir=tmp_path, version="v-test")

    rendered = manager.render("hello", {"name": "Alice", "date": "Monday"})
    metadata = manager.metadata("hello")

    assert rendered == "Hello Alice, today is Monday."
    assert metadata.prompt_name == "hello"
    assert metadata.version == "v-test"
    assert len(metadata.template_hash) == 64
    assert metadata.variables == ["date", "name"]
    assert metadata.created_at
