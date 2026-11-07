from promofinder.bible import build_bible
from promofinder.schemas import Bible


def test_bible_chunks_leave_room_for_schema_and_output_tokens():
    episodes = [{"number": index, "logline": "A plot note. " * 90,
                 "continuity_notes": "A continuity note. " * 90} for index in range(1, 21)]

    class Client:
        config = {"TOKENS_PER_MINUTE": "5000"}

        def __init__(self):
            self.prompts = []

        def complete_json(self, prompt, schema, **kwargs):
            self.prompts.append(prompt)
            return Bible(premise="A premise.", characters={}, relationships=[], reveals=[])

    client = Client()
    result = build_bible(episodes, client)
    assert not result["degraded"]
    assert len(client.prompts) > 1
    assert max(len(prompt) // 4 for prompt in client.prompts) <= 3500
