"""
Cliente assincrono para a API REST do Home Assistant.

Fluxo: ferramentas MCP / main.py chamam metodos aqui -> POST/GET na API do HA.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from thina.core.config import get_settings

logger = logging.getLogger(__name__)


class HAError(Exception):
    """Erro base na comunicacao com o Home Assistant."""


class HAConnectionError(HAError):
    """Falha de rede ou timeout ao contactar o HA."""


class HAAuthError(HAError):
    """Token invalido ou sem permissao."""


class HANotFoundError(HAError):
    """Entidade ou recurso nao encontrado."""


class HomeAssistantClient:
    """Encapsula chamadas REST ao Home Assistant."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._client: httpx.AsyncClient | None = None

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._settings.home_assistant_token}",
            "Content-Type": "application/json",
        }

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._settings.home_assistant_url,
                headers=self._headers(),
                timeout=httpx.Timeout(self._settings.ha_timeout),
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _request(
        self,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        client = await self._get_client()
        try:
            response = await client.request(method, path, json=json_body)
        except httpx.TimeoutException as exc:
            raise HAConnectionError(
                "Timeout ao contactar o Home Assistant. Verifique URL e rede."
            ) from exc
        except httpx.RequestError as exc:
            raise HAConnectionError(
                f"Nao foi possivel ligar ao Home Assistant: {exc}"
            ) from exc

        if response.status_code in (401, 403):
            raise HAAuthError(
                "Autenticacao no Home Assistant falhou. Verifique HOME_ASSISTANT_TOKEN."
            )

        if response.status_code == 404:
            raise HANotFoundError(f"Recurso nao encontrado: {path}")

        if response.status_code >= 400:
            detail = response.text[:500]
            raise HAError(
                f"Home Assistant retornou {response.status_code}: {detail}"
            )

        if response.status_code == 204 or not response.content:
            return None

        try:
            return response.json()
        except ValueError:
            return response.text

    async def call_service(
        self,
        domain: str,
        service: str,
        data: dict[str, Any] | None = None,
    ) -> Any:
        """Dispara um servico HA (ex: light.turn_on)."""
        payload = data or {}
        logger.debug("HA service %s.%s payload=%s", domain, service, payload)
        return await self._request(
            "POST",
            f"/api/services/{domain}/{service}",
            json_body=payload,
        )

    async def get_state(self, entity_id: str) -> dict[str, Any]:
        """Le estado e atributos de uma entidade."""
        result = await self._request("GET", f"/api/states/{entity_id}")
        if not isinstance(result, dict):
            raise HAError(f"Resposta inesperada para estado de {entity_id}")
        return result

    async def get_states(self) -> list[dict[str, Any]]:
        """Lista todos os estados (usado para filtrar entidades nas tools MCP)."""
        result = await self._request("GET", "/api/states")
        if not isinstance(result, list):
            raise HAError("Resposta inesperada ao listar estados")
        return result

    async def play_media(
        self,
        entity_id: str,
        media_url: str,
        content_type: str = "music",
        announce: bool = True,
    ) -> Any:
        """
        Reproduz midia no media_player de destino (ReSpeaker do comodo).

        O media_url deve ser acessivel pelo host do Home Assistant.
        """
        payload: dict[str, Any] = {
            "entity_id": entity_id,
            "media_content_id": media_url,
            "media_content_type": content_type,
        }
        if announce:
            payload["announce"] = True

        logger.info("Reproduzindo audio em %s: %s", entity_id, media_url)
        return await self.call_service("media_player", "play_media", payload)

    async def turn_on(self, entity_id: str, **extra: Any) -> Any:
        domain = entity_id.split(".", 1)[0]
        return await self.call_service(domain, "turn_on", {"entity_id": entity_id, **extra})

    async def turn_off(self, entity_id: str, **extra: Any) -> Any:
        domain = entity_id.split(".", 1)[0]
        return await self.call_service(domain, "turn_off", {"entity_id": entity_id, **extra})

    async def set_temperature(self, entity_id: str, temperature: float) -> Any:
        return await self.call_service(
            "climate",
            "set_temperature",
            {"entity_id": entity_id, "temperature": temperature},
        )


_ha_client: HomeAssistantClient | None = None


def get_ha_client() -> HomeAssistantClient:
    """Singleton do cliente HA (compartilhado entre main e subprocess MCP)."""
    global _ha_client
    if _ha_client is None:
        _ha_client = HomeAssistantClient()
    return _ha_client
