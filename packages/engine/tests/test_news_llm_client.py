# packages/engine/tests/test_news_llm_client.py
import json
import pytest
from unittest.mock import AsyncMock, patch


class TestCallLlm:
    @pytest.mark.asyncio
    async def test_call_llm_returns_text(self):
        from engine.pipelines.news_collector.llm_client import call_llm

        mock_response = AsyncMock()
        mock_response.choices = [AsyncMock()]
        mock_response.choices[0].message = AsyncMock()
        mock_response.choices[0].message.content = '{"results": []}'

        with patch("engine.pipelines.news_collector.llm_client._acompletion",
                    new_callable=AsyncMock, return_value=mock_response):
            result = await call_llm("test prompt", system="test system")
            assert result == '{"results": []}'

    @pytest.mark.asyncio
    async def test_call_llm_json_parse(self):
        from engine.pipelines.news_collector.llm_client import call_llm_json

        mock_response = AsyncMock()
        mock_response.choices = [AsyncMock()]
        mock_response.choices[0].message = AsyncMock()
        mock_response.choices[0].message.content = '{"decision": "pass", "score": 8.0}'

        with patch("engine.pipelines.news_collector.llm_client._acompletion",
                    new_callable=AsyncMock, return_value=mock_response):
            result = await call_llm_json("test prompt")
            assert result["decision"] == "pass"
            assert result["score"] == 8.0

    @pytest.mark.asyncio
    async def test_call_llm_json_strips_markdown(self):
        from engine.pipelines.news_collector.llm_client import call_llm_json

        mock_response = AsyncMock()
        mock_response.choices = [AsyncMock()]
        mock_response.choices[0].message = AsyncMock()
        mock_response.choices[0].message.content = '```json\n{"decision": "pass"}\n```'

        with patch("engine.pipelines.news_collector.llm_client._acompletion",
                    new_callable=AsyncMock, return_value=mock_response):
            result = await call_llm_json("test prompt")
            assert result["decision"] == "pass"
