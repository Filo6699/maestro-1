from __future__ import annotations

from typing import Any

import yaml
from pydantic import BaseModel, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    bot_token: SecretStr

    # alias -> server
    servers: dict[str, Server] = {}
    # who can use the whole servers
    allowed_chat_ids: list[int] = []

    model_config = SettingsConfigDict(
        extra="ignore",
        env_file=".env",
        env_nested_delimiter="_",
        env_file_encoding="utf-8",
    )

    def model_post_init(self, __context: Any) -> None:
        for key, value in self.servers.items():
            if not value.name:
                value.name = key

    @classmethod
    def using_yaml(cls, filename: str = "servers.yaml"):
        with open(filename, "r") as file:
            data = yaml.safe_load(file) or {}

        # global access users
        allowed_chat_ids = data.pop("allowed_chat_ids", [])

        servers = {
            alias: Server.model_validate(server)
            for alias, server in data.items()
            if isinstance(server, dict)
        }

        return cls(servers=servers, allowed_chat_ids=allowed_chat_ids)


class Server(BaseModel):
    name: str = ""
    host: str
    port: int = 22
    user: str = "root"

    # who can run actions of this server
    allowed_chat_ids: list[int] = []
    actions: dict[str, Action | str] = {}
    # show the run all button
    allow_run_all: bool = True

    def model_post_init(self, __context: Any) -> None:
        for key, value in self.actions.items():
            if isinstance(value, str):
                self.actions[key] = value = Action(command=value)
            if isinstance(value, Action) and not value.name:
                value.name = key


class Action(BaseModel):
    name: str = ""
    command: str
    description: str = ""


if __name__ == "__main__":
    config = Config.using_yaml()
    print(config.model_dump_json(indent=4))
